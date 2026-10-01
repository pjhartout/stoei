use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::Duration,
};

use chrono::{DateTime, Days, Local, NaiveDateTime, TimeZone};

use super::journal::JOURNAL_RETENTION_DAYS;
use super::selection::PendingSelection;
use super::*;

const FETCH_TIMEOUT: Duration = Duration::from_secs(30);
const DETAIL_TIMEOUT: Duration = Duration::from_secs(15);
const ACTION_TIMEOUT: Duration = Duration::from_secs(10);
const ACCT_TIMEOUT: Duration = Duration::from_secs(10);
const JOURNAL_THROTTLE_SECONDS: i64 = 20;

#[derive(Default)]
struct ClientState {
    last_fetch: Option<DateTime<Local>>,
    last_acct: Option<DateTime<Local>>,
    acct_failing: bool,
    warning: Option<String>,
}

pub struct Client {
    runner: Arc<dyn Runner>,
    username: String,
    journal: Option<Journal>,
    clock: Arc<dyn Clock>,
    acct_slot_minute: u32,
    state: Mutex<ClientState>,
}

impl Client {
    pub fn new(runner: Arc<dyn Runner>, username: String, journal_path: PathBuf) -> Self {
        let clock: Arc<dyn Clock> = Arc::new(SystemClock);
        let journal = (!journal_path.as_os_str().is_empty())
            .then(|| Journal::new(journal_path, clock.clone()));
        Self {
            runner,
            acct_slot_minute: acct_slot_minute_for(&username),
            username,
            journal,
            clock,
            state: Mutex::new(ClientState::default()),
        }
    }

    pub fn with_clock(mut self, clock: Arc<dyn Clock>) -> Self {
        if let Some(journal) = self.journal.take() {
            self.journal = Some(Journal::new(journal.path().to_owned(), clock.clone()));
        }
        self.clock = clock;
        self
    }

    pub fn username(&self) -> &str {
        &self.username
    }

    fn run(&self, name: &str, args: &[&str], timeout: Duration) -> Result<String, CommandError> {
        self.runner.run(
            name,
            &args.iter().map(|v| (*v).to_owned()).collect::<Vec<_>>(),
            timeout,
        )
    }

    pub fn available(&self) -> Result<(), String> {
        for name in ["squeue", "scontrol"] {
            self.run(name, &["--version"], FETCH_TIMEOUT)
                .map_err(|error| format!("SLURM command {name:?} not available: {error}"))?;
        }
        Ok(())
    }

    pub fn running_jobs(&self) -> Result<Vec<RunningJob>, String> {
        validate_name(&self.username, "username")?;
        self.run(
            "squeue",
            &["-u", &self.username, "-o", "%i|%j|%T|%M|%D|%R|%V|%S"],
            FETCH_TIMEOUT,
        )
        .map(|raw| parse_running_jobs(&raw))
        .map_err(|e| e.to_string())
    }

    pub fn all_users_jobs(&self) -> Result<Vec<AllUsersJob>, String> {
        self.run(
            "squeue",
            &[
                "-O",
                ALL_USERS_FORMAT,
                "-a",
                "-t",
                "RUNNING,PENDING",
                "--noheader",
            ],
            FETCH_TIMEOUT,
        )
        .map(|raw| parse_all_users_jobs(&raw))
        .map_err(|e| e.to_string())
    }

    pub fn cluster_nodes(&self) -> Result<Vec<Node>, String> {
        self.run("scontrol", &["show", "nodes"], FETCH_TIMEOUT)
            .map(|raw| parse_nodes(&raw))
            .map_err(|e| e.to_string())
    }

    pub fn fair_share(&self) -> Result<Vec<FairShareEntry>, String> {
        self.run("sshare", &["-a", "-P", "--noheader",
            "--format=Account,User,RawShares,NormShares,RawUsage,NormUsage,EffectvUsage,FairShare"], FETCH_TIMEOUT)
            .map(|raw| parse_fair_share(&raw)).map_err(|e| e.to_string())
    }

    pub fn pending_priority(&self) -> Result<Vec<PriorityEntry>, String> {
        self.run(
            "sprio",
            &["-o", PRIORITY_FORMAT, "--noheader"],
            FETCH_TIMEOUT,
        )
        .map(|raw| parse_priority(&raw))
        .map_err(|e| e.to_string())
    }

    pub fn priority_config(&self) -> Result<PriorityConfig, String> {
        self.run("scontrol", &["show", "config"], FETCH_TIMEOUT)
            .map(|raw| parse_priority_config(&raw))
            .map_err(|e| e.to_string())
    }

    pub fn node_detail(&self, name: &str) -> Result<JobDetail, String> {
        let name = name.trim();
        validate_name(name, "node name")?;
        let raw = self
            .run("scontrol", &["show", "node", name], DETAIL_TIMEOUT)
            .map_err(|e| format!("scontrol show node {name}: {e}"))?;
        let fields = parse_node_fields(&raw);
        if fields.is_empty() {
            return Err(format!("node {name}: no information available"));
        }
        Ok(JobDetail {
            fields,
            source: "scontrol".into(),
        })
    }

    pub fn job_detail(&self, id: &str) -> Result<JobDetail, String> {
        let normalized = checked_job_id(id)?;
        let raw = match self.run("scontrol", &["show", "jobid", &normalized], DETAIL_TIMEOUT) {
            Ok(raw) => raw,
            Err(error)
                if error.stderr.to_ascii_lowercase().contains("invalid job id")
                    && matches!(
                        error.cause,
                        CommandErrorCause::Exit(_) | CommandErrorCause::HardFailure
                    ) =>
            {
                return self
                    .accounting_job_detail(&normalized)
                    .map_err(|e| format!("job {id} accounting detail: {e}"))?
                    .ok_or_else(|| format!("job {id} not found: {error}"));
            }
            Err(error) => return Err(format!("job {id}: {error}")),
        };
        let fields = pick_active_record(parse_scontrol_job_records(&raw))
            .ok_or_else(|| format!("job {id}: could not parse scontrol output"))?;
        Ok(JobDetail {
            fields,
            source: "scontrol".into(),
        })
    }

    pub fn completed_job_record(&self, id: &str) -> Result<Option<HistoryJob>, String> {
        let normalized = checked_job_id(id)?;
        let raw = self
            .run("scontrol", &["show", "jobid", &normalized], DETAIL_TIMEOUT)
            .map_err(|e| e.to_string())?;
        let Some(fields) = pick_active_record(parse_scontrol_job_records(&raw)) else {
            return Ok(None);
        };
        if field(&fields, "JobId").is_empty() || !is_terminal_state(field(&fields, "JobState")) {
            return Ok(None);
        }
        let job = controller_job_from_fields(&fields);
        if let Some(journal) = &self.journal {
            let _ = journal.upsert(vec![job.clone()]);
        }
        let mut history = HistoryJob::from(job);
        history.id = id.into();
        Ok(Some(history))
    }

    pub fn job_usage(&self, id: &str, running: bool) -> Result<JobUsage, String> {
        let normalized = checked_job_id(id)?;
        if running {
            self.run(
                "sstat",
                &[
                    "-a",
                    "-n",
                    "-P",
                    "-j",
                    &normalized,
                    "-o",
                    SSTAT_USAGE_FORMAT,
                ],
                DETAIL_TIMEOUT,
            )
            .map(|raw| parse_sstat_usage(&normalized, &raw))
            .map_err(|e| format!("job {id} usage: {e}"))
        } else {
            self.run(
                "sacct",
                &[
                    "--allusers",
                    "-n",
                    "-P",
                    "-j",
                    &normalized,
                    "-o",
                    SACCT_USAGE_FORMAT,
                ],
                DETAIL_TIMEOUT,
            )
            .map(|raw| parse_sacct_usage(&normalized, &raw))
            .map_err(|e| format!("job {id} usage: {e}"))
        }
    }

    pub fn cancel_job(&self, id: &str) -> Result<(), String> {
        let id = checked_job_id(id)?;
        self.run("scancel", &[&id], ACTION_TIMEOUT)
            .map(|_| ())
            .map_err(|e| format!("scancel error: {e}"))
    }

    pub fn update_job(&self, id: &str, key: &str, value: &str) -> Result<(), String> {
        let normalized = checked_job_id(id)?;
        let key = key.trim();
        if !key.as_bytes().first().is_some_and(u8::is_ascii_alphabetic)
            || !key.bytes().all(|b| b.is_ascii_alphanumeric())
        {
            return Err(format!("invalid scontrol field name: {key:?}"));
        }
        if key.eq_ignore_ascii_case("jobid") {
            return Err(format!("field {key:?} cannot be set via update"));
        }
        let value = value.trim();
        if value.is_empty() {
            return Err("value cannot be empty".into());
        }
        let target = if key.eq_ignore_ascii_case("partition") {
            let selection = PendingSelection::parse(id)?;
            let pending = self
                .run(
                    "squeue",
                    &[
                        "--noheader",
                        "--array",
                        &format!("--jobs={}", selection.query_id),
                        "--states",
                        "PENDING",
                        "--format",
                        "%i|%A",
                    ],
                    DETAIL_TIMEOUT,
                )
                .map_err(|error| format!("could not check pending jobs: {error}"))?;
            selection.target(&pending)?
        } else {
            normalized
        };
        self.run(
            "scontrol",
            &["update", &format!("JobId={target}"), &format!("{key}={value}")],
            ACTION_TIMEOUT,
        )
        .map(|_| ())
        .map_err(|error| {
            if key.eq_ignore_ascii_case("partition") {
                format!("Partition update failed; some array tasks may already have changed. Tasks that started running cannot change partition. {error}")
            } else {
                format!("scontrol update error: {error}")
            }
        })
    }

    pub fn hold_job(&self, id: &str, hold: bool) -> Result<(), String> {
        let id = checked_job_id(id)?;
        let verb = if hold { "hold" } else { "release" };
        self.run("scontrol", &[verb, &id], ACTION_TIMEOUT)
            .map(|_| ())
            .map_err(|e| format!("scontrol {verb} error: {e}"))
    }

    fn accounting_job_detail(&self, id: &str) -> Result<Option<JobDetail>, String> {
        let raw = self
            .run(
                "sacct",
                &[
                    "--allusers",
                    "-n",
                    "-P",
                    "-X",
                    "-j",
                    id,
                    &format!("--format={ACCT_FORMAT}"),
                ],
                ACCT_TIMEOUT,
            )
            .map_err(|e| e.to_string())?;
        Ok(parse_acct_jobs(&raw)
            .into_iter()
            .find(|job| job.id == id)
            .map(|job| JobDetail {
                fields: accounting_detail_fields(job),
                source: "sacct".into(),
            }))
    }

    fn query_journal_jobs(&self) -> Result<Vec<ControllerJob>, String> {
        self.run(
            "squeue",
            &[
                "-u",
                &self.username,
                "-t",
                "all",
                "--noheader",
                "-O",
                JOURNAL_SQUEUE_FORMAT,
            ],
            FETCH_TIMEOUT,
        )
        .map(|raw| parse_journal_jobs(&raw))
        .map_err(|e| e.to_string())
    }

    fn journal_jobs(&self, force: bool) -> Result<Vec<ControllerJob>, String> {
        let Some(journal) = &self.journal else {
            return self.query_journal_jobs();
        };
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        let now = self.clock.now();
        if force
            || state
                .last_fetch
                .is_none_or(|last| (now - last).num_seconds() >= JOURNAL_THROTTLE_SECONDS)
        {
            let jobs = self.query_journal_jobs()?;
            state.last_fetch = Some(self.clock.now());
            journal.upsert(jobs)?;
        }
        drop(state);
        journal.try_all()
    }

    pub fn job_history(&self, days: u32, force: bool) -> Result<HistoryResult, String> {
        validate_name(&self.username, "username")?;
        self.reconcile_acct();
        let jobs = self.journal_jobs(force)?;
        let cutoff = if days == 0 {
            None
        } else {
            self.clock
                .now()
                .checked_sub_days(Days::new(u64::from(days)))
                .map(|now| now.to_utc())
        };
        let (jobs, stats) = history_jobs_for(jobs, &self.username, cutoff);
        let warning = self
            .state
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .warning
            .take();
        Ok(HistoryResult {
            jobs,
            stats,
            warning,
        })
    }

    pub fn acct_due(&self) -> bool {
        if self.journal.is_none() {
            return false;
        }
        let state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        self.acct_due_since(state.last_acct)
    }

    fn acct_due_since(&self, last: Option<DateTime<Local>>) -> bool {
        last.is_none_or(|last| self.clock.now() >= next_acct_slot(last, self.acct_slot_minute))
    }

    fn reconcile_acct(&self) {
        let Some(journal) = &self.journal else { return };
        {
            let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
            if !self.acct_due_since(state.last_acct) {
                return;
            }
            state.last_acct = Some(self.clock.now());
        }
        let _accounting_lock = match journal.try_acct_lock() {
            Ok(Some(lock)) => lock,
            Ok(None) => return,
            Err(error) => {
                self.finish_reconcile(Err(error));
                return;
            }
        };
        if let Ok(time) =
            fs::metadata(acct_stamp_path(journal.path())).and_then(|file| file.modified())
        {
            let last = DateTime::<Local>::from(time);
            if !self.acct_due_since(Some(last)) {
                self.state
                    .lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .last_acct = Some(last);
                return;
            }
        }
        if self.finish_reconcile(self.reconcile_query(journal)) {
            journal.touch_acct_stamp();
        }
    }

    fn finish_reconcile(&self, result: Result<(), String>) -> bool {
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        if result.is_err() {
            if !state.acct_failing {
                state.warning = Some(
                    "sacct reconcile failed — job history reflects only jobs stoei has observed"
                        .into(),
                );
            }
            state.acct_failing = true;
            false
        } else {
            state.acct_failing = false;
            true
        }
    }

    fn reconcile_query(&self, journal: &Journal) -> Result<(), String> {
        let start = (self.clock.now() - chrono::Duration::days(JOURNAL_RETENTION_DAYS))
            .format("%Y-%m-%d")
            .to_string();
        let raw = self
            .run(
                "sacct",
                &[
                    "-u",
                    &self.username,
                    "-n",
                    "-P",
                    "-X",
                    "-S",
                    &start,
                    &format!("--format={ACCT_FORMAT}"),
                ],
                ACCT_TIMEOUT,
            )
            .map_err(|e| e.to_string())?;
        let jobs = parse_acct_jobs(&raw);
        let existing = journal.try_all()?;
        let merged = merge_acct(&existing, &jobs);
        journal.upsert(merged)?;
        journal.remove(&stale_owned_ids(&journal.try_all()?, &jobs, &self.username))
    }
}

pub fn validate_name(name: &str, label: &str) -> Result<(), String> {
    if name.is_empty() {
        return Err(format!("{label} cannot be empty"));
    }
    if !name
        .bytes()
        .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'.' || b == b'-')
    {
        return Err(format!("unsafe characters detected in {label}: {name:?}"));
    }
    Ok(())
}

pub fn checked_job_id(id: &str) -> Result<String, String> {
    let id = normalize_array_job_id(id);
    if id.is_empty() {
        return Err("job ID cannot be empty".into());
    }
    let mut components = id.split('_');
    let number = |part: &str| !part.is_empty() && part.bytes().all(|b| b.is_ascii_digit());
    if !number(components.next().unwrap_or(""))
        || components.next().is_some_and(|part| !number(part))
        || components.next().is_some()
    {
        return Err(format!(
            "invalid job ID format: {id:?} (expected 12345 or 12345_0)"
        ));
    }
    Ok(id)
}

fn pick_active_record(
    mut records: Vec<BTreeMap<String, String>>,
) -> Option<BTreeMap<String, String>> {
    if records.is_empty() {
        return None;
    }
    let index = records
        .iter()
        .position(|fields| !is_terminal_state(field(fields, "JobState")))
        .unwrap_or(0);
    Some(records.swap_remove(index))
}

fn accounting_detail_fields(job: ControllerJob) -> BTreeMap<String, String> {
    [
        ("JobId", job.id),
        ("JobName", job.name),
        ("UserId", job.user),
        ("JobState", job.state),
        ("Partition", job.partition),
        ("SubmitTime", job.submit),
        ("StartTime", job.start),
        ("EndTime", job.end),
        ("RunTime", job.elapsed),
        ("ExitCode", job.exit_code),
        ("NodeList", job.node_list),
        ("NumCPUs", job.ncpus),
        ("AllocTRES", job.alloc_tres),
        ("StdOut", job.std_out),
        ("StdErr", job.std_err),
    ]
    .into_iter()
    .filter(|(_, value)| !value.trim().is_empty())
    .map(|(key, value)| (key.into(), value))
    .collect()
}

pub fn acct_slot_minute_for(user: &str) -> u32 {
    let hash = user.bytes().fold(2166136261_u32, |hash, byte| {
        (hash ^ u32::from(byte)).wrapping_mul(16777619)
    });
    hash % 240
}

pub fn next_acct_slot(last: DateTime<Local>, minute: u32) -> DateTime<Local> {
    debug_assert!(minute < 240);
    let today = local_slot(last.date_naive(), minute);
    if today > last {
        return today;
    }
    local_slot(
        last.date_naive()
            .checked_add_days(Days::new(1))
            .expect("supported date"),
        minute,
    )
}

fn local_slot(date: chrono::NaiveDate, minute: u32) -> DateTime<Local> {
    let slot = date
        .and_hms_opt(1 + minute / 60, minute % 60, 0)
        .expect("valid nightly slot");
    let convert = |slot: NaiveDateTime| Local.from_local_datetime(&slot).earliest();
    convert(slot)
        .or_else(|| convert(slot + chrono::Duration::hours(1)))
        .expect("supported local time")
}

pub fn merge_acct(existing: &[ControllerJob], jobs: &[ControllerJob]) -> Vec<ControllerJob> {
    let prior: BTreeMap<_, _> = existing.iter().map(|job| (&job.id, job)).collect();
    jobs.iter()
        .filter(|job| is_terminal_state(&job.state))
        .map(|job| {
            let mut job = job.clone();
            if let Some(old) = prior.get(&job.id) {
                if job.restart.is_empty() {
                    job.restart.clone_from(&old.restart);
                }
                if !old.std_out.is_empty() {
                    job.std_out.clone_from(&old.std_out);
                }
                if !old.std_err.is_empty() {
                    job.std_err.clone_from(&old.std_err);
                }
            }
            job
        })
        .collect()
}

pub fn stale_owned_ids(
    journal: &[ControllerJob],
    acct: &[ControllerJob],
    user: &str,
) -> Vec<String> {
    if acct.is_empty() {
        return Vec::new();
    }
    let ids: BTreeSet<_> = acct.iter().map(|job| &job.id).collect();
    journal
        .iter()
        .filter(|job| job.user == user && !is_terminal_state(&job.state) && !ids.contains(&job.id))
        .map(|job| job.id.clone())
        .collect()
}
