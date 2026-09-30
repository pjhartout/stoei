use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::Duration,
};

use chrono::{DateTime, Local, TimeZone};
use stoei::slurm::*;

type Call = (String, Vec<String>, Duration);

#[derive(Default)]
struct FakeRunner {
    outputs: Mutex<BTreeMap<String, String>>,
    errors: Mutex<BTreeMap<String, CommandError>>,
    calls: Mutex<Vec<Call>>,
}

impl FakeRunner {
    fn output(&self, name: &str, output: &str) {
        self.outputs
            .lock()
            .unwrap()
            .insert(name.into(), output.into());
    }

    fn fail(&self, name: &str, cause: CommandErrorCause, stderr: &str) {
        self.errors
            .lock()
            .unwrap()
            .insert(name.into(), CommandError::new(name, cause, stderr));
    }

    fn recover(&self, name: &str) {
        self.errors.lock().unwrap().remove(name);
    }

    fn last(&self) -> Call {
        self.calls.lock().unwrap().last().unwrap().clone()
    }

    fn count(&self, name: &str) -> usize {
        self.calls
            .lock()
            .unwrap()
            .iter()
            .filter(|call| call.0 == name)
            .count()
    }
}

impl Runner for FakeRunner {
    fn run(&self, name: &str, args: &[String], timeout: Duration) -> Result<String, CommandError> {
        self.calls
            .lock()
            .unwrap()
            .push((name.into(), args.to_vec(), timeout));
        if let Some(error) = self.errors.lock().unwrap().get(name) {
            return Err(error.clone());
        }
        Ok(self
            .outputs
            .lock()
            .unwrap()
            .get(name)
            .cloned()
            .unwrap_or_default())
    }
}

struct FixedClock(Mutex<DateTime<Local>>);

impl FixedClock {
    fn new() -> Self {
        Self(Mutex::new(
            Local.with_ymd_and_hms(2026, 9, 30, 12, 0, 0).unwrap(),
        ))
    }
    fn set(&self, now: DateTime<Local>) {
        *self.0.lock().unwrap() = now;
    }
}

impl Clock for FixedClock {
    fn now(&self) -> DateTime<Local> {
        *self.0.lock().unwrap()
    }
}

fn client(runner: &Arc<FakeRunner>) -> Client {
    Client::new(runner.clone(), "alice".into(), PathBuf::new())
        .with_clock(Arc::new(FixedClock::new()))
}

fn assert_call(runner: &FakeRunner, name: &str, args: &[&str], timeout: u64) {
    let call = runner.last();
    assert_eq!(call.0, name);
    assert_eq!(call.1, args);
    assert_eq!(call.2, Duration::from_secs(timeout));
}

#[test]
fn commands_have_explicit_scopes_formats_and_budgets() {
    let runner = Arc::new(FakeRunner::default());
    let client = client(&runner);
    client.available().unwrap();
    assert_eq!(runner.count("squeue"), 1);
    assert_call(&runner, "scontrol", &["--version"], 30);
    client.running_jobs().unwrap();
    assert_call(
        &runner,
        "squeue",
        &["-u", "alice", "-o", "%i|%j|%T|%M|%D|%R|%V|%S"],
        30,
    );
    client.all_users_jobs().unwrap();
    assert_call(
        &runner,
        "squeue",
        &[
            "-O",
            ALL_USERS_FORMAT,
            "-a",
            "-t",
            "RUNNING,PENDING",
            "--noheader",
        ],
        30,
    );
    client.cluster_nodes().unwrap();
    assert_call(&runner, "scontrol", &["show", "nodes"], 30);
    client.fair_share().unwrap();
    assert_call(
        &runner,
        "sshare",
        &[
            "-a",
            "-P",
            "--noheader",
            "--format=Account,User,RawShares,NormShares,RawUsage,NormUsage,EffectvUsage,FairShare",
        ],
        30,
    );
    client.pending_priority().unwrap();
    assert_call(&runner, "sprio", &["-o", PRIORITY_FORMAT, "--noheader"], 30);
    client.priority_config().unwrap();
    assert_call(&runner, "scontrol", &["show", "config"], 30);
    client.job_usage("123_7", true).unwrap();
    assert_call(
        &runner,
        "sstat",
        &["-a", "-n", "-P", "-j", "123_7", "-o", SSTAT_USAGE_FORMAT],
        15,
    );
    client.job_usage("123_7", false).unwrap();
    assert_call(
        &runner,
        "sacct",
        &[
            "--allusers",
            "-n",
            "-P",
            "-j",
            "123_7",
            "-o",
            SACCT_USAGE_FORMAT,
        ],
        15,
    );
}

#[test]
fn mutations_normalize_array_leaders_and_preserve_single_arguments() {
    let runner = Arc::new(FakeRunner::default());
    let client = client(&runner);
    client.cancel_job("123_[0-99]").unwrap();
    assert_call(&runner, "scancel", &["123"], 10);
    client.hold_job("123_[0-99]", true).unwrap();
    assert_call(&runner, "scontrol", &["hold", "123"], 10);
    client.hold_job("123_7", false).unwrap();
    assert_call(&runner, "scontrol", &["release", "123_7"], 10);
    client
        .update_job("123_7", "Comment", " words $(not-executed) ")
        .unwrap();
    assert_call(
        &runner,
        "scontrol",
        &["update", "JobId=123_7", "Comment=words $(not-executed)"],
        10,
    );
    let calls = runner.calls.lock().unwrap().len();
    for id in ["", "123_", "123_1_2", "123;evil", "$(whoami)"] {
        assert!(client.cancel_job(id).is_err(), "{id}");
    }
    assert!(client.update_job("123", "jObId", "456").is_err());
    assert!(client.update_job("123", "A=B", "x").is_err());
    assert!(client.update_job("123", "Name", " ").is_err());
    assert!(client.node_detail("node;evil").is_err());
    assert_eq!(runner.calls.lock().unwrap().len(), calls);
}

#[test]
fn controller_array_detail_prefers_active_record() {
    let runner = Arc::new(FakeRunner::default());
    runner.output("scontrol", include_str!("fixtures/scontrol_job_array.txt"));
    let client = client(&runner);
    let detail = client.job_detail("123_[0-99]").unwrap();
    assert_eq!(detail.source, "scontrol");
    assert!(!is_terminal_state(&detail.fields["JobState"]));
    assert_call(&runner, "scontrol", &["show", "jobid", "123"], 15);
    assert!(client.completed_job_record("123").unwrap().is_none());
    assert_eq!(runner.count("sacct"), 0);
}

#[test]
fn purged_detail_falls_back_only_for_invalid_job_errors() {
    let runner = Arc::new(FakeRunner::default());
    runner.fail(
        "scontrol",
        CommandErrorCause::Exit(Some(1)),
        "slurm_load_jobs error: Invalid job id specified",
    );
    runner.output("sacct", "123|alice|COMPLETED|p|s|b|e|1:00|0:0|n01|4|cpu=4,mem=2G||/logs/%j|job\n124|alice|COMPLETED|p|s|b|e|1:00|0:0|n01|4|cpu=4||||\n");
    let client = client(&runner);
    let detail = client.job_detail("123").unwrap();
    assert_eq!(detail.source, "sacct");
    assert_eq!(detail.fields["JobId"], "123");
    assert_eq!(detail.fields["StdOut"], "/logs/123");
    assert_call(
        &runner,
        "sacct",
        &[
            "--allusers",
            "-n",
            "-P",
            "-X",
            "-j",
            "123",
            &format!("--format={ACCT_FORMAT}"),
        ],
        10,
    );
    let calls = runner.count("sacct");
    runner.fail(
        "scontrol",
        CommandErrorCause::TimedOut,
        "Invalid job id left over",
    );
    assert!(client.job_detail("123").unwrap_err().contains("timed out"));
    assert_eq!(runner.count("sacct"), calls);
    runner.fail(
        "scontrol",
        CommandErrorCause::Exit(Some(1)),
        "controller unavailable",
    );
    assert!(
        client
            .job_detail("123")
            .unwrap_err()
            .contains("controller unavailable")
    );
    assert_eq!(runner.count("sacct"), calls);
}

#[test]
fn completion_persists_terminal_record_without_accounting_query() {
    let temporary = tempfile::tempdir().unwrap();
    let path = temporary.path().join("jobs.jsonl");
    let runner = Arc::new(FakeRunner::default());
    runner.output("scontrol", "JobId=123 JobName=done UserId=alice(1) JobState=COMPLETED Restarts=2 RunTime=01:00 ExitCode=0:0 NodeList=n01 SubmitTime=2026-09-30T00:00:00 StdOut=/logs/123");
    let clock = Arc::new(FixedClock::new());
    let client =
        Client::new(runner.clone(), "alice".into(), path.clone()).with_clock(clock.clone());
    let history = client.completed_job_record("123").unwrap().unwrap();
    assert_eq!(history.id, "123");
    assert_eq!(history.restart, "2");
    let jobs = Journal::new(path, clock).all();
    assert_eq!(jobs.len(), 1);
    assert_eq!(jobs[0].state, "COMPLETED");
    assert_eq!(runner.count("sacct"), 0);
}

#[test]
fn journal_refresh_is_user_scoped_throttled_and_forceable() {
    let temporary = tempfile::tempdir().unwrap();
    let runner = Arc::new(FakeRunner::default());
    let clock = Arc::new(FixedClock::new());
    let client = Client::new(
        runner.clone(),
        "alice".into(),
        temporary.path().join("jobs.jsonl"),
    )
    .with_clock(clock.clone());
    client.job_history(7, false).unwrap();
    assert_call(
        &runner,
        "squeue",
        &[
            "-u",
            "alice",
            "-t",
            "all",
            "--noheader",
            "-O",
            JOURNAL_SQUEUE_FORMAT,
        ],
        30,
    );
    client.job_history(7, false).unwrap();
    assert_eq!(runner.count("squeue"), 1);
    client.job_history(7, true).unwrap();
    assert_eq!(runner.count("squeue"), 2);
    clock.set(clock.now() + chrono::Duration::seconds(20));
    client.job_history(7, false).unwrap();
    assert_eq!(runner.count("squeue"), 3);
    assert_eq!(runner.count("sacct"), 1);
}

#[test]
fn accounting_success_stamp_caps_cross_session_queries_until_next_slot() {
    let temporary = tempfile::tempdir().unwrap();
    let path = temporary.path().join("jobs.jsonl");
    let clock = Arc::new(FixedClock::new());
    let runner = Arc::new(FakeRunner::default());
    runner.output("sacct", "123|alice|COMPLETED|p|2026-09-30T00:00:00|2026-09-30T01:00:00|2026-09-30T02:00:00|1:00|0:0|n01|4|cpu=4,mem=2G||/logs/%j|job\n");
    let first = Client::new(runner.clone(), "alice".into(), path.clone()).with_clock(clock.clone());
    assert!(first.acct_due());
    let result = first.job_history(7, false).unwrap();
    assert_eq!(result.jobs.len(), 1);
    assert_eq!(result.jobs[0].std_out, "/logs/123");
    assert!(!first.acct_due());
    let second = Client::new(runner.clone(), "alice".into(), path).with_clock(clock.clone());
    second.job_history(7, false).unwrap();
    assert_eq!(runner.count("sacct"), 1);
    let due = next_acct_slot(clock.now(), acct_slot_minute_for("alice"));
    clock.set(due);
    assert!(second.acct_due());
    second.job_history(7, false).unwrap();
    assert_eq!(runner.count("sacct"), 2);
}

#[test]
fn accounting_warning_reappears_only_after_recovery() {
    let temporary = tempfile::tempdir().unwrap();
    let runner = Arc::new(FakeRunner::default());
    runner.fail(
        "sacct",
        CommandErrorCause::HardFailure,
        "connection refused",
    );
    let clock = Arc::new(FixedClock::new());
    let client = Client::new(
        runner.clone(),
        "alice".into(),
        temporary.path().join("jobs.jsonl"),
    )
    .with_clock(clock.clone());
    assert!(client.job_history(7, false).unwrap().warning.is_some());
    assert!(client.job_history(7, false).unwrap().warning.is_none());
    clock.set(next_acct_slot(clock.now(), acct_slot_minute_for("alice")));
    assert!(client.job_history(7, false).unwrap().warning.is_none());
    runner.recover("sacct");
    clock.set(next_acct_slot(clock.now(), acct_slot_minute_for("alice")));
    assert!(client.job_history(7, false).unwrap().warning.is_none());
    runner.fail(
        "sacct",
        CommandErrorCause::HardFailure,
        "connection refused",
    );
    clock.set(next_acct_slot(clock.now(), acct_slot_minute_for("alice")));
    assert!(client.job_history(7, false).unwrap().warning.is_some());
}

#[test]
fn accounting_merge_keeps_paths_and_restarts_and_prunes_only_owned_live_ids() {
    let existing = vec![
        ControllerJob {
            id: "1".into(),
            user: "alice".into(),
            state: "RUNNING".into(),
            restart: "3".into(),
            std_out: "/expanded".into(),
            ..Default::default()
        },
        ControllerJob {
            id: "2".into(),
            user: "alice".into(),
            state: "RUNNING".into(),
            ..Default::default()
        },
        ControllerJob {
            id: "3".into(),
            user: "bob".into(),
            state: "RUNNING".into(),
            ..Default::default()
        },
        ControllerJob {
            id: "4".into(),
            user: "alice".into(),
            state: "FAILED".into(),
            ..Default::default()
        },
    ];
    let jobs = vec![ControllerJob {
        id: "1".into(),
        user: "alice".into(),
        state: "COMPLETED".into(),
        std_out: "/%j".into(),
        ..Default::default()
    }];
    let merged = merge_acct(&existing, &jobs);
    assert_eq!(merged[0].restart, "3");
    assert_eq!(merged[0].std_out, "/expanded");
    assert_eq!(stale_owned_ids(&existing, &jobs, "alice"), ["2"]);
    assert!(stale_owned_ids(&existing, &[], "alice").is_empty());
}

#[test]
fn history_window_uses_latest_valid_timestamp_and_keeps_undated_jobs() {
    let jobs = vec![
        ControllerJob {
            id: "1".into(),
            user: "alice".into(),
            submit: "2026-01-01T00:00:00".into(),
            end: "2026-09-30T00:00:00".into(),
            restart: "2".into(),
            ..Default::default()
        },
        ControllerJob {
            id: "2".into(),
            user: "alice".into(),
            submit: "2026-01-01T00:00:00".into(),
            ..Default::default()
        },
        ControllerJob {
            id: "3".into(),
            user: "alice".into(),
            restart: "3".into(),
            ..Default::default()
        },
        ControllerJob {
            id: "4".into(),
            user: "bob".into(),
            ..Default::default()
        },
    ];
    let (jobs, stats) =
        history_jobs_for(jobs, "alice", parse_slurm_timestamp("2026-09-01T00:00:00"));
    assert_eq!(
        jobs.iter().map(|job| job.id.as_str()).collect::<Vec<_>>(),
        ["1", "3"]
    );
    assert_eq!(stats.total_jobs, 2);
    assert_eq!(stats.total_requeues, 5);
    assert_eq!(stats.max_requeues, 3);
}

#[test]
fn concurrent_sessions_share_an_accounting_query_in_flight() {
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        mpsc,
    };
    struct BlockingRunner {
        calls: AtomicUsize,
        entered: mpsc::SyncSender<()>,
        release: Mutex<mpsc::Receiver<()>>,
    }
    impl Runner for BlockingRunner {
        fn run(&self, name: &str, _: &[String], _: Duration) -> Result<String, CommandError> {
            if name == "sacct" {
                self.calls.fetch_add(1, Ordering::Relaxed);
                self.entered.send(()).unwrap();
                self.release.lock().unwrap().recv().unwrap();
            }
            Ok(String::new())
        }
    }
    let temporary = tempfile::tempdir().unwrap();
    let path = temporary.path().join("jobs.jsonl");
    let (entered_send, entered_recv) = mpsc::sync_channel(1);
    let (release_send, release_recv) = mpsc::sync_channel(1);
    let runner = Arc::new(BlockingRunner {
        calls: AtomicUsize::new(0),
        entered: entered_send,
        release: Mutex::new(release_recv),
    });
    let clock = Arc::new(FixedClock::new());
    let first = Client::new(runner.clone(), "alice".into(), path.clone()).with_clock(clock.clone());
    let second = Client::new(runner.clone(), "alice".into(), path).with_clock(clock);
    let handle = std::thread::spawn(move || first.job_history(7, false).unwrap());
    entered_recv.recv().unwrap();
    second.job_history(7, false).unwrap();
    assert_eq!(runner.calls.load(Ordering::Relaxed), 1);
    release_send.send(()).unwrap();
    handle.join().unwrap();
}
