use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, SyncSender, TrySendError};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use crate::config;
use crate::slurm::Client;
use crate::store::{Dataset, JobDetail, Section, is_pending_state, is_terminal_state};
use crate::ui::{ActionResult, Effect, JobSnapshot};
use crate::update::ReleaseClient;

use super::{Event, io, send_event};

pub enum Work {
    Fetch {
        section: Section,
        generation: u64,
        days: u32,
        force: bool,
    },
    Action(Effect),
    Completed(String),
    Available,
    Latest,
}

pub struct Workers {
    fast: Option<SyncSender<Work>>,
    slow: Option<SyncSender<Work>>,
    handles: Vec<JoinHandle<()>>,
    shutdown: Arc<AtomicBool>,
}

impl Workers {
    pub fn new(
        client: Arc<Client>,
        config_path: PathBuf,
        events: SyncSender<Event>,
        shutdown: Arc<AtomicBool>,
    ) -> Result<Self, String> {
        let mut workers = Self {
            fast: None,
            slow: None,
            handles: Vec::new(),
            shutdown,
        };
        for fast in [true, false] {
            let (sender, receiver) = mpsc::sync_channel(8);
            let client = client.clone();
            let config_path = config_path.clone();
            let events = events.clone();
            let stopped = workers.shutdown.clone();
            let handle = thread::Builder::new()
                .name(
                    if fast {
                        "stoei-interactive"
                    } else {
                        "stoei-background"
                    }
                    .into(),
                )
                .stack_size(512 * 1024)
                .spawn(move || {
                    while let Ok(work) = receiver.recv() {
                        if stopped.load(Ordering::Relaxed) {
                            break;
                        }
                        let event = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                            perform(work, &client, &config_path, &stopped)
                        }))
                        .unwrap_or_else(|_| {
                            Event::WorkerError("background worker panicked".into())
                        });
                        if !send_event(&events, event, &stopped) {
                            break;
                        }
                    }
                })
                .map_err(|err| err.to_string())?;
            if fast {
                workers.fast = Some(sender);
            } else {
                workers.slow = Some(sender);
            }
            workers.handles.push(handle);
        }
        Ok(workers)
    }

    pub fn enqueue(&self, work: Work) -> Result<(), String> {
        let slow = matches!(
            &work,
            Work::Fetch {
                section: Section::History
                    | Section::Nodes
                    | Section::AllUsersJobs
                    | Section::FairShare
                    | Section::PendingPrio
                    | Section::PriorityConfig,
                ..
            } | Work::Latest
                | Work::Action(Effect::FetchLog { .. })
        );
        let sender = if slow { &self.slow } else { &self.fast };
        match sender.as_ref().ok_or("worker stopped")?.try_send(work) {
            Ok(()) => Ok(()),
            Err(TrySendError::Full(_)) => {
                Err("background queue is full; try again after the current operation".into())
            }
            Err(TrySendError::Disconnected(_)) => Err("background worker stopped".into()),
        }
    }
}

impl Drop for Workers {
    fn drop(&mut self) {
        self.shutdown.store(true, Ordering::Relaxed);
        self.fast.take();
        self.slow.take();
        let deadline = Instant::now() + Duration::from_secs(2);
        while self.handles.iter().any(|handle| !handle.is_finished()) && Instant::now() < deadline {
            thread::park_timeout(Duration::from_millis(10));
        }
        for handle in self.handles.drain(..) {
            if handle.is_finished() {
                let _ = handle.join();
            }
        }
    }
}

fn perform(
    work: Work,
    client: &Client,
    config_path: &std::path::Path,
    stopped: &AtomicBool,
) -> Event {
    match work {
        Work::Fetch {
            section,
            generation,
            days,
            force,
        } => Event::Data {
            section,
            generation,
            result: fetch(client, section, days, force),
        },
        Work::Action(effect) => action(effect, client, config_path, stopped),
        Work::Completed(id) => Event::Completed(client.completed_job_record(&id)),
        Work::Available => Event::Available(client.available()),
        Work::Latest => Event::Latest(ReleaseClient::default().latest_cached_with_cancel(stopped)),
    }
}

fn fetch(client: &Client, section: Section, days: u32, force: bool) -> Result<Dataset, String> {
    match section {
        Section::RunningJobs => client.running_jobs().map(Dataset::RunningJobs),
        Section::History => client.job_history(days, force).map(Dataset::History),
        Section::Nodes => client.cluster_nodes().map(Dataset::Nodes),
        Section::AllUsersJobs => client.all_users_jobs().map(Dataset::AllUsersJobs),
        Section::FairShare => client.fair_share().map(Dataset::FairShare),
        Section::PendingPrio => client.pending_priority().map(Dataset::PendingPrio),
        Section::PriorityConfig => client.priority_config().map(Dataset::PriorityConfig),
    }
}

fn action(
    effect: Effect,
    client: &Client,
    config_path: &std::path::Path,
    stopped: &AtomicBool,
) -> Event {
    let result = match effect {
        Effect::FetchJob {
            token,
            job_id,
            state,
            fallback,
        } => {
            let result = job_snapshot(client, &job_id, &state, fallback);
            ActionResult::Job {
                token,
                job_id,
                result,
            }
        }
        Effect::FetchNode { token, name } => {
            let result = client.node_detail(&name);
            ActionResult::Node {
                token,
                name,
                result,
            }
        }
        Effect::FetchLog {
            token,
            path,
            max_lines,
        } => ActionResult::Log {
            token,
            result: io::read_tail(&path, max_lines, stopped),
        },
        Effect::Cancel { job_id } => {
            let result = client.cancel_job(&job_id);
            ActionResult::Cancel { job_id, result }
        }
        Effect::Modify { job_id, fields } => {
            let result = if fields.len() > 16 {
                Err("too many job fields".into())
            } else {
                fields
                    .into_iter()
                    .try_for_each(|(key, value)| client.update_job(&job_id, &key, &value))
            };
            ActionResult::Modify { job_id, result }
        }
        Effect::Hold { job_id, hold } => {
            let result = client.hold_job(&job_id, hold);
            ActionResult::Modify { job_id, result }
        }
        Effect::SaveConfig(config) => ActionResult::ConfigSaved(config::save(config_path, &config)),
        Effect::Copy(text) => {
            let result = io::copy(&text, stopped);
            return Event::Copy { text, result };
        }
        _ => return Event::WorkerError("unsupported worker request".into()),
    };
    Event::Action(result)
}

pub fn job_snapshot(
    client: &Client,
    job_id: &str,
    state: &str,
    fallback: Option<JobDetail>,
) -> Result<JobSnapshot, String> {
    let (detail, mut note) = match client.job_detail(job_id) {
        Ok(detail) => (detail, None),
        Err(err) => match fallback {
            Some(detail) => (detail, Some(format!("Using recorded details: {err}"))),
            None => return Err(err),
        },
    };
    let current = detail
        .fields
        .get("JobState")
        .map(String::as_str)
        .unwrap_or(state);
    let live = !is_terminal_state(current) && !is_pending_state(current);
    let user = detail
        .fields
        .get("UserId")
        .map(|value| value.split('(').next().unwrap_or(value));
    if live && user != Some(client.username()) {
        note = Some("Live efficiency is available only for your own jobs".into());
        return Ok(JobSnapshot {
            detail,
            usage: None,
            note,
        });
    }
    if is_pending_state(current) {
        return Ok(JobSnapshot {
            detail,
            usage: None,
            note,
        });
    }
    let usage_id = if live {
        detail
            .fields
            .get("JobId")
            .map(String::as_str)
            .unwrap_or(job_id)
    } else {
        job_id
    };
    let usage = match client.job_usage(usage_id, live) {
        Ok(usage) => Some(usage),
        Err(err) => {
            note = Some(format!("Efficiency unavailable: {err}"));
            None
        }
    };
    Ok(JobSnapshot {
        detail,
        usage,
        note,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::slurm::{CommandError, Runner};
    use std::sync::Mutex;
    use std::time::Duration;

    struct DetailRunner {
        calls: Mutex<Vec<(String, Vec<String>)>>,
        user: &'static str,
        state: &'static str,
    }

    impl Runner for DetailRunner {
        fn run(
            &self,
            name: &str,
            arguments: &[String],
            _: Duration,
        ) -> Result<String, CommandError> {
            self.calls
                .lock()
                .unwrap()
                .push((name.into(), arguments.to_vec()));
            match name {
                "scontrol" => Ok(format!("JobId=70001 ArrayJobId=123 ArrayTaskId=7 JobName=demo UserId={}(1000) JobState={} RunTime=00:10:00 NumCPUs=4 AllocTRES=cpu=4,mem=4G StdOut=/tmp/demo", self.user, self.state)),
                "sstat" => Ok("70001.batch|100M|cpu=00:20:00,fs/disk=60000|gres/gpuutil=100|gres/gpumem=30M|fs/disk=120000\n".into()),
                name => panic!("unexpected scheduler command in fake: {name}"),
            }
        }
    }

    #[test]
    fn live_array_usage_uses_fresh_controller_allocation_and_numeric_id() {
        let directory = tempfile::tempdir().unwrap();
        let runner = Arc::new(DetailRunner {
            calls: Mutex::new(Vec::new()),
            user: "alice",
            state: "RUNNING",
        });
        let client = Client::new(
            runner.clone(),
            "alice".into(),
            directory.path().join("jobs.jsonl"),
        );
        let snapshot = job_snapshot(&client, "123_7", "RUNNING", None).unwrap();
        let calls = runner.calls.lock().unwrap();
        assert_eq!(calls[0].0, "scontrol");
        assert_eq!(calls[1].0, "sstat");
        let job_argument = calls[1]
            .1
            .iter()
            .position(|argument| argument == "-j")
            .unwrap();
        assert_eq!(calls[1].1[job_argument + 1], "70001");
        let efficiency = crate::store::derive_job_efficiency(
            snapshot.usage.as_ref().unwrap(),
            &snapshot.detail.fields,
        );
        assert!((efficiency.cpu_percent - 50.0).abs() < 0.001);
        assert!((efficiency.read_bytes_per_sec - 100.0).abs() < 0.001);
    }

    #[test]
    fn foreign_live_and_pending_jobs_never_issue_usage_queries() {
        for (user, state) in [
            ("bob", "RUNNING"),
            ("bob", "COMPLETING"),
            ("alice", "PENDING"),
            ("alice", "PD"),
        ] {
            let directory = tempfile::tempdir().unwrap();
            let runner = Arc::new(DetailRunner {
                calls: Mutex::new(Vec::new()),
                user,
                state,
            });
            let client = Client::new(
                runner.clone(),
                "alice".into(),
                directory.path().join("jobs.jsonl"),
            );
            let snapshot = job_snapshot(&client, "123_7", state, None).unwrap();
            assert!(snapshot.usage.is_none());
            assert_eq!(runner.calls.lock().unwrap().len(), 1);
        }
    }

    #[test]
    fn own_nonterminal_jobs_use_live_controller_usage() {
        for state in ["COMPLETING", "SUSPENDED", "CONFIGURING"] {
            let directory = tempfile::tempdir().unwrap();
            let runner = Arc::new(DetailRunner {
                calls: Mutex::new(Vec::new()),
                user: "alice",
                state,
            });
            let client = Client::new(
                runner.clone(),
                "alice".into(),
                directory.path().join("jobs.jsonl"),
            );
            let snapshot = job_snapshot(&client, "123_7", state, None).unwrap();
            assert!(snapshot.usage.is_some());
            let calls = runner.calls.lock().unwrap();
            assert_eq!(calls.len(), 2);
            assert_eq!(calls[1].0, "sstat");
            assert!(calls[1].1.windows(2).any(|pair| pair == ["-j", "70001"]));
        }
    }
}
