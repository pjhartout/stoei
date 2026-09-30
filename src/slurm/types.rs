use std::{collections::BTreeMap, time::Duration};

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GPUEntry {
    pub gpu_type: String,
    pub count: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RunningJob {
    pub id: String,
    pub name: String,
    pub state: String,
    pub time: String,
    pub nodes: String,
    pub node_list: String,
    pub submit_time: String,
    pub start_time: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AllUsersJob {
    pub id: String,
    pub name: String,
    pub user: String,
    pub partition: String,
    pub state: String,
    pub time: String,
    pub num_nodes: String,
    pub node_list: String,
    pub reason: String,
    pub tres: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HistoryJob {
    pub id: String,
    pub name: String,
    pub state: String,
    pub restart: String,
    pub elapsed: String,
    pub exit_code: String,
    pub node_list: String,
    pub submit: String,
    pub start: String,
    pub end: String,
    pub std_out: String,
    pub std_err: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HistoryStats {
    pub total_jobs: usize,
    pub total_requeues: u64,
    pub max_requeues: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HistoryResult {
    pub jobs: Vec<HistoryJob>,
    pub stats: HistoryStats,
    pub warning: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Node {
    pub name: String,
    pub state: String,
    pub cpu_tot: String,
    pub cpu_alloc: String,
    pub real_mem: String,
    pub alloc_mem: String,
    pub cfg_tres: String,
    pub alloc_tres: String,
    pub gres: String,
    pub reason: String,
    pub fields: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct JobDetail {
    pub fields: BTreeMap<String, String>,
    pub source: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FairShareEntry {
    pub account: String,
    pub user: String,
    pub raw_shares: String,
    pub norm_shares: String,
    pub raw_usage: String,
    pub norm_usage: String,
    pub effectv_usage: String,
    pub fair_share: String,
}

impl FairShareEntry {
    pub fn is_account(&self) -> bool {
        self.user.is_empty()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PriorityEntry {
    pub job_id: String,
    pub user: String,
    pub account: String,
    pub partition: String,
    pub qos: String,
    pub priority: i64,
    pub factors: PriorityFactors,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PriorityFactors {
    pub age: i64,
    pub fair_share: i64,
    pub job_size: i64,
    pub partition: i64,
    pub qos: i64,
    pub tres: i64,
    pub assoc: i64,
    pub site: i64,
    pub nice: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PriorityFactor {
    pub name: String,
    pub value: i64,
}

impl PriorityFactors {
    pub fn add(&mut self, other: &Self) {
        self.age = self.age.saturating_add(other.age);
        self.fair_share = self.fair_share.saturating_add(other.fair_share);
        self.job_size = self.job_size.saturating_add(other.job_size);
        self.partition = self.partition.saturating_add(other.partition);
        self.qos = self.qos.saturating_add(other.qos);
        self.tres = self.tres.saturating_add(other.tres);
        self.assoc = self.assoc.saturating_add(other.assoc);
        self.site = self.site.saturating_add(other.site);
        self.nice = self.nice.saturating_add(other.nice);
    }

    pub fn contributions(&self) -> Vec<PriorityFactor> {
        let mut values: Vec<_> = [
            ("FairShare", self.fair_share),
            ("Age", self.age),
            ("JobSize", self.job_size),
            ("Partition", self.partition),
            ("QOS", self.qos),
            ("TRES", self.tres),
            ("Assoc", self.assoc),
            ("Site", self.site),
            ("Nice", self.nice),
        ]
        .into_iter()
        .filter(|(_, v)| *v != 0)
        .map(|(name, value)| PriorityFactor {
            name: name.into(),
            value,
        })
        .collect();
        values.sort_by_key(|v| std::cmp::Reverse(v.value.unsigned_abs()));
        values
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PriorityWeights {
    pub age: i64,
    pub assoc: i64,
    pub fair_share: i64,
    pub job_size: i64,
    pub partition: i64,
    pub qos: i64,
    pub tres: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PriorityConfig {
    pub priority_type: String,
    pub weights: PriorityWeights,
    pub max_age: Duration,
    pub decay_half_life: Duration,
    pub favor_small: bool,
}

impl PriorityConfig {
    pub fn multifactor(&self) -> bool {
        self.priority_type == "priority/multifactor"
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct ControllerJob {
    #[serde(rename = "ID")]
    pub id: String,
    #[serde(rename = "User")]
    pub user: String,
    #[serde(rename = "Name")]
    pub name: String,
    #[serde(rename = "State")]
    pub state: String,
    #[serde(rename = "Partition")]
    pub partition: String,
    #[serde(rename = "Submit")]
    pub submit: String,
    #[serde(rename = "Start")]
    pub start: String,
    #[serde(rename = "End")]
    pub end: String,
    #[serde(rename = "Elapsed")]
    pub elapsed: String,
    #[serde(rename = "ExitCode")]
    pub exit_code: String,
    #[serde(rename = "Restart")]
    pub restart: String,
    #[serde(rename = "NodeList")]
    pub node_list: String,
    #[serde(rename = "NCPUS")]
    pub ncpus: String,
    #[serde(rename = "AllocTRES")]
    pub alloc_tres: String,
    #[serde(rename = "StdOut")]
    pub std_out: String,
    #[serde(rename = "StdErr")]
    pub std_err: String,
}

impl From<ControllerJob> for HistoryJob {
    fn from(j: ControllerJob) -> Self {
        Self {
            id: j.id,
            name: j.name,
            state: j.state,
            restart: j.restart,
            elapsed: j.elapsed,
            exit_code: j.exit_code,
            node_list: j.node_list,
            submit: j.submit,
            start: j.start,
            end: j.end,
            std_out: j.std_out,
            std_err: j.std_err,
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct JobUsage {
    pub source: String,
    pub elapsed_sec: f64,
    pub alloc_cpus: u64,
    pub cpu_time_sec: f64,
    pub gpus: Vec<GPUEntry>,
    pub max_rss_bytes: u64,
    pub disk_read_bytes: u64,
    pub disk_write_bytes: u64,
    pub gpu_util_percent: f64,
    pub gpu_util_known: bool,
    pub gpu_mem_bytes: u64,
    pub gpu_mem_known: bool,
    pub sampled: bool,
}
