mod derive;
mod display;
mod efficiency;
mod priority;
mod timeline;

pub use crate::slurm::{
    AllUsersJob, FairShareEntry, GPUEntry, GpuDevice, GpuSnapshot, HistoryJob, HistoryResult,
    HistoryStats, JobDetail, JobUsage, Node, PriorityConfig, PriorityEntry, PriorityFactor,
    PriorityFactors, PriorityWeights, RunningJob, TRESResources, aggregate_gpu_counts,
    calculate_total_gpus, expand_node_list, expand_std_io_path, format_gpu_types,
    has_specific_gpu_types, is_mig_type, is_terminal_state, job_std_io, normalize_array_job_id,
    parse_array_size, parse_cpu_count_from_tres, parse_elapsed_to_seconds, parse_gpu_entries,
    parse_gpu_from_gres, parse_size_bytes, parse_slurm_timestamp, parse_tres_pairs,
    parse_tres_resources, short_gpu_label, try_expand_node_list, wait_time_seconds,
};
pub use derive::*;
pub use display::*;
pub use efficiency::*;
pub use priority::*;
pub use timeline::*;

use std::collections::{BTreeMap, BTreeSet};
use std::time::Instant;

const MAX_ROWS: usize = 100_000;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum State {
    #[default]
    Idle,
    Loading,
    Loaded,
    Error,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Section {
    RunningJobs,
    History,
    Nodes,
    AllUsersJobs,
    FairShare,
    PendingPrio,
    PriorityConfig,
}

impl Section {
    pub const ALL: [Self; 7] = [
        Self::RunningJobs,
        Self::History,
        Self::Nodes,
        Self::AllUsersJobs,
        Self::FairShare,
        Self::PendingPrio,
        Self::PriorityConfig,
    ];

    pub fn name(self) -> &'static str {
        match self {
            Self::RunningJobs => "running_jobs",
            Self::History => "history",
            Self::Nodes => "nodes",
            Self::AllUsersJobs => "all_users_jobs",
            Self::FairShare => "fair_share",
            Self::PendingPrio => "pending_priority",
            Self::PriorityConfig => "priority_config",
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct Meta {
    pub state: State,
    pub last_updated: Option<Instant>,
    pub last_success: Option<Instant>,
    pub err: Option<String>,
    pub generation: u64,
    failing: bool,
}

#[derive(Clone, Debug)]
pub enum Dataset {
    RunningJobs(Vec<RunningJob>),
    History(HistoryResult),
    Nodes(Vec<Node>),
    AllUsersJobs(Vec<AllUsersJob>),
    FairShare(Vec<FairShareEntry>),
    PendingPrio(Vec<PriorityEntry>),
    PriorityConfig(PriorityConfig),
}

impl Dataset {
    pub fn section(&self) -> Section {
        match self {
            Self::RunningJobs(_) => Section::RunningJobs,
            Self::History(_) => Section::History,
            Self::Nodes(_) => Section::Nodes,
            Self::AllUsersJobs(_) => Section::AllUsersJobs,
            Self::FairShare(_) => Section::FairShare,
            Self::PendingPrio(_) => Section::PendingPrio,
            Self::PriorityConfig(_) => Section::PriorityConfig,
        }
    }

    fn row_count(&self) -> usize {
        match self {
            Self::RunningJobs(rows) => rows.len(),
            Self::History(result) => result.jobs.len(),
            Self::Nodes(rows) => rows.len(),
            Self::AllUsersJobs(rows) => rows.len(),
            Self::FairShare(rows) => rows.len(),
            Self::PendingPrio(rows) => rows.len(),
            Self::PriorityConfig(_) => 1,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct ApplyOutcome {
    pub accepted: bool,
    pub notification: Option<String>,
    pub completed_ids: Vec<String>,
}

#[derive(Clone, Debug, Default)]
pub struct MergedJob {
    pub id: String,
    pub name: String,
    pub state: String,
    pub time: String,
    pub nodes: String,
    pub node_list: String,
    pub active: bool,
    pub submit_time: String,
    pub start_time: String,
    pub end_time: String,
    pub restarts: u64,
}

#[derive(Clone, Debug, Default)]
pub struct Store {
    pub user: String,
    pub running_jobs: Vec<RunningJob>,
    pub history_jobs: Vec<HistoryJob>,
    pub history_stats: HistoryStats,
    pub nodes: Vec<Node>,
    pub all_users_jobs: Vec<AllUsersJob>,
    pub fair_share: Vec<FairShareEntry>,
    pub pending_prio: Vec<PriorityEntry>,
    pub priority_config: PriorityConfig,
    pub cluster_stats: ClusterStats,
    meta: [Meta; 7],
    running_loaded: bool,
    completed: Vec<HistoryJob>,
    merged: Vec<MergedJob>,
    node_rows: Vec<NodeDisplay>,
    running_users: Vec<UserStats>,
    pending_users: Vec<UserPendingStats>,
    users_ranked: Vec<RankedShare>,
    accounts_ranked: Vec<RankedShare>,
    pending_ranked: Vec<RankedPriority>,
}

impl Store {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn meta(&self, section: Section) -> &Meta {
        &self.meta[section as usize]
    }

    pub fn generation(&self, section: Section) -> u64 {
        self.meta(section).generation
    }

    pub fn begin(&mut self, section: Section) -> u64 {
        let meta = &mut self.meta[section as usize];
        meta.generation = meta
            .generation
            .checked_add(1)
            .expect("request generation exhausted");
        meta.state = State::Loading;
        meta.generation
    }

    pub fn settled(&self, section: Section) -> bool {
        self.meta(section).last_updated.is_some()
    }

    pub fn has_data(&self, section: Section) -> bool {
        self.meta(section).last_success.is_some()
    }

    pub fn any_loading(&self) -> bool {
        self.meta.iter().any(|meta| meta.state == State::Loading)
    }

    pub fn apply(
        &mut self,
        section: Section,
        generation: u64,
        result: Result<Dataset, String>,
        now: Instant,
    ) -> ApplyOutcome {
        if generation < self.generation(section) {
            return ApplyOutcome::default();
        }
        let result = result.and_then(|data| validate_dataset(section, data));
        let error = result.as_ref().err().cloned();
        let completed_ids = match result {
            Ok(data) => self.apply_data(data),
            Err(_) => Vec::new(),
        };
        let notification = self.apply_meta(section, generation, error, now);
        ApplyOutcome {
            accepted: true,
            notification,
            completed_ids,
        }
    }

    fn apply_meta(
        &mut self,
        section: Section,
        generation: u64,
        error: Option<String>,
        now: Instant,
    ) -> Option<String> {
        let meta = &mut self.meta[section as usize];
        let failing = error.is_some();
        let notification = match (meta.failing, failing) {
            (false, true) => Some(format!("{}: data refresh failed", section.name())),
            (true, false) => Some(format!("{}: data refresh recovered", section.name())),
            _ => None,
        };
        meta.failing = failing;
        meta.generation = generation;
        meta.state = if failing { State::Error } else { State::Loaded };
        meta.err = error;
        meta.last_updated = Some(now);
        if !failing {
            meta.last_success = Some(now);
        }
        notification
    }

    fn apply_data(&mut self, data: Dataset) -> Vec<String> {
        match data {
            Dataset::RunningJobs(jobs) => return self.apply_running(jobs),
            Dataset::History(result) => {
                self.history_stats = result.stats;
                self.rebuild_history(result.jobs);
            }
            Dataset::Nodes(nodes) => {
                self.nodes = nodes;
                self.node_rows = derive_node_displays(&self.nodes);
                self.rebuild_resources();
            }
            Dataset::AllUsersJobs(jobs) => {
                self.all_users_jobs = jobs;
                self.rebuild_resources();
            }
            Dataset::FairShare(entries) => {
                self.fair_share = entries;
                self.users_ranked = rank_active_users(&self.fair_share);
                self.accounts_ranked = rank_accounts(&self.fair_share);
            }
            Dataset::PendingPrio(entries) => {
                self.pending_prio = entries;
                self.pending_ranked = rank_pending(&self.pending_prio);
            }
            Dataset::PriorityConfig(config) => self.priority_config = config,
        }
        Vec::new()
    }

    fn apply_running(&mut self, jobs: Vec<RunningJob>) -> Vec<String> {
        let current: BTreeSet<&str> = jobs.iter().map(|job| job.id.as_str()).collect();
        let vanished = self
            .running_jobs
            .iter()
            .filter(|job| !current.contains(job.id.as_str()))
            .map(|job| job.id.clone())
            .collect();
        self.running_jobs = jobs;
        self.running_loaded = true;
        self.rebuild_merged();
        vanished
    }

    fn rebuild_resources(&mut self) {
        self.cluster_stats = derive_cluster_stats(&self.nodes, &self.all_users_jobs);
        let models = node_gpu_models(&self.nodes);
        self.running_users = aggregate_user_stats(&self.all_users_jobs, &models);
        self.pending_users = aggregate_pending_user_stats(&self.all_users_jobs);
    }

    pub fn add_completed_job(&mut self, job: HistoryJob) -> Result<(), String> {
        if !is_terminal_state(&job.state) {
            return Err(format!("completion record for {} is not terminal", job.id));
        }
        self.completed.retain(|previous| previous.id != job.id);
        if self.completed.len() >= MAX_ROWS {
            return Err("session completion history exceeds row limit".into());
        }
        self.history_jobs.retain(|previous| previous.id != job.id);
        self.history_jobs.insert(0, job.clone());
        self.completed.insert(0, job);
        self.rebuild_merged();
        Ok(())
    }

    fn rebuild_history(&mut self, base: Vec<HistoryJob>) {
        let terminal: BTreeSet<&str> = base
            .iter()
            .filter(|job| is_terminal_state(&job.state))
            .map(|job| job.id.as_str())
            .collect();
        self.completed
            .retain(|job| !terminal.contains(job.id.as_str()));
        let overlay: BTreeSet<&str> = self.completed.iter().map(|job| job.id.as_str()).collect();
        self.history_jobs = self
            .completed
            .iter()
            .cloned()
            .chain(
                base.into_iter()
                    .filter(|job| !overlay.contains(job.id.as_str())),
            )
            .collect();
        self.rebuild_merged();
    }

    fn rebuild_merged(&mut self) {
        self.merged = merge_jobs(&self.running_jobs, &self.history_jobs, self.running_loaded);
    }

    pub fn merged_jobs(&self) -> &[MergedJob] {
        &self.merged
    }
    pub fn node_displays(&self) -> &[NodeDisplay] {
        &self.node_rows
    }
    pub fn running_user_stats(&self) -> &[UserStats] {
        &self.running_users
    }
    pub fn pending_user_stats(&self) -> &[UserPendingStats] {
        &self.pending_users
    }
    pub fn ranked_users(&self) -> &[RankedShare] {
        &self.users_ranked
    }
    pub fn ranked_accounts(&self) -> &[RankedShare] {
        &self.accounts_ranked
    }
    pub fn ranked_pending(&self) -> &[RankedPriority] {
        &self.pending_ranked
    }

    pub fn journal_detail(&self, job_id: &str) -> Option<JobDetail> {
        self.history_jobs
            .iter()
            .find(|job| job.id == job_id)
            .map(journal_detail)
    }
}

fn validate_dataset(section: Section, data: Dataset) -> Result<Dataset, String> {
    if data.section() != section {
        return Err(format!(
            "{} received {} dataset",
            section.name(),
            data.section().name()
        ));
    }
    if data.row_count() > MAX_ROWS {
        return Err(format!("{} exceeds row limit", section.name()));
    }
    Ok(data)
}

pub fn journal_detail(job: &HistoryJob) -> JobDetail {
    let mut fields = BTreeMap::from([
        ("JobId".into(), job.id.clone()),
        ("JobName".into(), job.name.clone()),
        ("JobState".into(), job.state.clone()),
        ("Restarts".into(), job.restart.clone()),
        ("RunTime".into(), job.elapsed.clone()),
        ("ExitCode".into(), job.exit_code.clone()),
        ("NodeList".into(), job.node_list.clone()),
        ("SubmitTime".into(), job.submit.clone()),
        ("StartTime".into(), job.start.clone()),
        ("EndTime".into(), job.end.clone()),
    ]);
    for (key, value) in [("StdOut", &job.std_out), ("StdErr", &job.std_err)] {
        if !value.is_empty() {
            fields.insert(key.into(), value.clone());
        }
    }
    JobDetail {
        fields,
        source: "journal".into(),
    }
}

pub fn merge_jobs(
    running: &[RunningJob],
    history: &[HistoryJob],
    running_loaded: bool,
) -> Vec<MergedJob> {
    let mut live = BTreeSet::new();
    let mut merged = Vec::with_capacity(running.len() + history.len());
    for job in running {
        live.insert(job.id.clone());
        live.insert(normalize_array_job_id(&job.id));
        merged.push(MergedJob {
            id: job.id.clone(),
            name: job.name.clone(),
            state: job.state.clone(),
            time: job.time.clone(),
            nodes: job.nodes.clone(),
            node_list: job.node_list.clone(),
            active: true,
            submit_time: job.submit_time.clone(),
            start_time: job.start_time.clone(),
            ..MergedJob::default()
        });
    }
    for job in history.iter().filter(|job| !live.contains(&job.id)) {
        let state = if running_loaded && !is_terminal_state(&job.state) {
            "UNKNOWN"
        } else {
            &job.state
        };
        merged.push(MergedJob {
            id: job.id.clone(),
            name: job.name.clone(),
            state: state.into(),
            time: job.elapsed.clone(),
            node_list: job.node_list.clone(),
            submit_time: job.submit.clone(),
            start_time: job.start.clone(),
            end_time: job.end.clone(),
            restarts: parse_restarts(&job.restart),
            ..MergedJob::default()
        });
    }
    merged.sort_by(|a, b| {
        status_rank(a)
            .cmp(&status_rank(b))
            .then_with(|| start_key(b).cmp(&start_key(a)))
            .then_with(|| a.id.cmp(&b.id))
    });
    merged
}

fn status_rank(job: &MergedJob) -> u8 {
    let state = job
        .state
        .split_whitespace()
        .next()
        .unwrap_or("")
        .to_uppercase();
    match state.as_str() {
        "PENDING" | "PD" => 0,
        "RUNNING" | "R" => 1,
        _ if job.active && !is_terminal_state(&state) => 2,
        _ => 3,
    }
}

fn start_key(job: &MergedJob) -> Option<chrono::NaiveDateTime> {
    [&job.start_time, &job.submit_time]
        .into_iter()
        .find_map(|value| chrono::NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S").ok())
}

#[cfg(test)]
mod tests;
