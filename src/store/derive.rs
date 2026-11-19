use std::collections::{BTreeMap, BTreeSet};
use std::ops::RangeInclusive;

use super::{
    AllUsersJob, Node, RunningJob, aggregate_gpu_counts, calculate_total_gpus, expand_node_list,
    format_gpu_types, is_terminal_state, parse_array_size, parse_gpu_entries, parse_gpu_from_gres,
    parse_tres_resources,
};

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PendingPartitionStats {
    pub jobs_count: u64,
    pub cpus: u64,
    pub memory_gb: f64,
    pub gpus_by_type: BTreeMap<String, u64>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GpuCapacity {
    pub total: u64,
    pub allocated: u64,
    pub unavailable: u64,
    pub unknown: u64,
}

impl GpuCapacity {
    pub fn known_free(&self) -> u64 {
        self.total
            .saturating_sub(self.unavailable)
            .saturating_sub(self.unknown)
            .saturating_sub(self.allocated)
    }

    fn add_node(&mut self, total: u64, allocated: RangeInclusive<u64>, available: bool) {
        self.total = self.total.saturating_add(total);
        if available {
            self.allocated = self.allocated.saturating_add(*allocated.start());
            self.unknown = self
                .unknown
                .saturating_add(allocated.end() - allocated.start());
        } else {
            self.unavailable = self.unavailable.saturating_add(total);
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ClusterStats {
    pub total_nodes: u64,
    pub free_nodes: u64,
    pub allocated_nodes: u64,
    pub total_cpus: u64,
    pub allocated_cpus: u64,
    pub total_memory_gb: f64,
    pub allocated_memory_gb: f64,
    pub gpus: GpuCapacity,
    pub gpus_by_type: BTreeMap<String, GpuCapacity>,
    pub draining_nodes: u64,
    pub offline_nodes: u64,
}

impl ClusterStats {
    pub fn free_nodes_pct(&self) -> f64 {
        percent(self.free_nodes as f64, self.total_nodes as f64)
    }
    pub fn free_cpus_pct(&self) -> f64 {
        percent(
            self.total_cpus.saturating_sub(self.allocated_cpus) as f64,
            self.total_cpus as f64,
        )
    }
    pub fn free_memory_pct(&self) -> f64 {
        percent(
            (self.total_memory_gb - self.allocated_memory_gb).max(0.0),
            self.total_memory_gb,
        )
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct NodeDisplay {
    pub name: String,
    pub state: String,
    pub cpus_alloc: u64,
    pub cpus_total: u64,
    pub memory_alloc_gb: f64,
    pub memory_total_gb: f64,
    pub gpus_alloc: Option<u64>,
    pub gpus_total: u64,
    pub gpu_types: String,
    pub partitions: String,
    pub reason: String,
}

impl NodeDisplay {
    pub fn cpu_usage_pct(&self) -> f64 {
        percent(self.cpus_alloc as f64, self.cpus_total as f64)
    }
    pub fn memory_usage_pct(&self) -> f64 {
        percent(self.memory_alloc_gb, self.memory_total_gb)
    }
    pub fn gpu_usage_pct(&self) -> Option<f64> {
        self.gpus_alloc
            .filter(|_| self.gpus_total > 0)
            .map(|allocated| percent(allocated as f64, self.gpus_total as f64))
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct UserStats {
    pub username: String,
    pub job_count: usize,
    pub total_cpus: u64,
    pub total_memory_gb: f64,
    pub total_gpus: u64,
    pub total_nodes: u64,
    pub gpu_types: String,
    pub node_names: String,
    pub array_count: usize,
    pub plain_job_count: usize,
    pub generic_gpu_jobs: usize,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct UserPendingStats {
    pub username: String,
    pub pending_job_count: u64,
    pub pending_cpus: u64,
    pub pending_memory_gb: f64,
    pub pending_gpus: u64,
    pub pending_gpu_types: String,
    pub pending_reasons: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AccountResourceUsage {
    pub total_cpus: u64,
    pub total_memory_gb: f64,
    pub total_gpus: u64,
    pub unique_nodes: u64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NodeJob {
    pub id: String,
    pub name: String,
    pub user: String,
    pub time: String,
    pub cpus: u64,
    pub gpus: u64,
}

fn percent(value: f64, total: f64) -> f64 {
    if total <= 0.0 {
        0.0
    } else {
        value / total * 100.0
    }
}

fn number(value: &str) -> u64 {
    value.trim().parse().unwrap_or(0)
}

pub fn is_pending_state(state: &str) -> bool {
    matches!(state.trim().to_ascii_uppercase().as_str(), "PENDING" | "PD")
}

pub fn node_offline(state: &str) -> bool {
    let upper = state.to_ascii_uppercase();
    upper.contains('*')
        || [
            "DOWN",
            "NOT_RESPONDING",
            "MAINT",
            "POWER",
            "FUTURE",
            "INVAL",
            "UNKNOWN",
        ]
        .iter()
        .any(|marker| upper.contains(marker))
}

fn gpu_total(counts: &BTreeMap<String, u64>) -> u64 {
    counts.values().copied().fold(0, u64::saturating_add)
}

fn single_gpu_model(counts: &BTreeMap<String, u64>) -> Option<&String> {
    counts
        .keys()
        .next()
        .filter(|model| counts.len() == 1 && model.as_str() != "GPU")
}

fn configured_gpus(node: &Node) -> BTreeMap<String, u64> {
    let configured = aggregate_gpu_counts(&parse_gpu_entries(&node.cfg_tres), true);
    if !configured.is_empty() && !configured.contains_key("GPU") {
        return configured;
    }
    let gres = aggregate_gpu_counts(&parse_gpu_from_gres(&node.gres), true);
    let Some(&total) = configured.get("GPU") else {
        return gres;
    };
    if let Some(model) = single_gpu_model(&gres) {
        return BTreeMap::from([(model.clone(), total)]);
    }
    if !gres.is_empty() && gpu_total(&gres) == total {
        return gres;
    }
    configured
}

#[derive(Clone, Debug, Default)]
pub(super) struct NodeInventory {
    pub rows: Vec<NodeDisplay>,
    pub models: BTreeMap<String, String>,
    pub cluster: ClusterStats,
}

impl NodeInventory {
    pub fn from_nodes(nodes: &[Node]) -> Self {
        let mut inventory = Self::default();
        for node in nodes {
            let state = node.state.trim();
            let state = if state.is_empty() { "UNKNOWN" } else { state };
            let upper = state.to_ascii_uppercase();
            let configured = configured_gpus(node);
            let allocated = crate::slurm::reported_gpu_counts(&node.alloc_tres)
                .or_else(|| (upper.split('+').next() == Some("IDLE")).then(BTreeMap::new));
            let row = NodeDisplay {
                name: node.name.trim().into(),
                state: state.into(),
                cpus_alloc: number(&node.cpu_alloc),
                cpus_total: number(&node.cpu_tot),
                memory_alloc_gb: number(&node.alloc_mem) as f64 / 1024.0,
                memory_total_gb: number(&node.real_mem) as f64 / 1024.0,
                gpus_alloc: allocated.as_ref().map(gpu_total),
                gpus_total: gpu_total(&configured),
                gpu_types: format_gpu_types(&configured),
                partitions: node
                    .fields
                    .get("Partitions")
                    .filter(|value| !value.trim().is_empty())
                    .cloned()
                    .unwrap_or_else(|| "N/A".into()),
                reason: node.reason.trim().into(),
            };
            inventory
                .cluster
                .add_node(&row, &upper, &configured, allocated.as_ref());
            if !row.name.is_empty() {
                if let Some(model) = single_gpu_model(&configured) {
                    inventory.models.insert(row.name.clone(), model.clone());
                }
                inventory.rows.push(row);
            }
        }
        inventory
    }
}

impl ClusterStats {
    fn add_node(
        &mut self,
        row: &NodeDisplay,
        state: &str,
        configured: &BTreeMap<String, u64>,
        allocated: Option<&BTreeMap<String, u64>>,
    ) {
        let offline = node_offline(state);
        let draining = state.contains("DRAIN");
        let available = !offline && !draining;
        let total = row.gpus_total;
        let bounds = row.gpus_alloc.map_or(0..=total, |n| n..=n);
        self.gpus.add_node(total, bounds.clone(), available);
        for (model, &count) in configured {
            let model_bounds = if configured.len() == 1 {
                bounds.clone()
            } else if let Some(counts) = allocated {
                if let Some(&generic) = counts.get("GPU") {
                    // A generic allocation can occupy at most the installed count of each model.
                    generic.min(total).saturating_sub(total - count)..=generic.min(count)
                } else {
                    let n = counts.get(model).copied().unwrap_or_default();
                    n..=n
                }
            } else {
                0..=count
            };
            self.gpus_by_type
                .entry(model.clone())
                .or_default()
                .add_node(count, model_bounds, available);
        }
        if offline {
            self.offline_nodes += 1;
            return;
        }
        if draining {
            self.draining_nodes += 1;
            return;
        }
        self.total_nodes += 1;
        self.free_nodes += u64::from(state.contains("IDLE"));
        self.allocated_nodes += u64::from(state.contains("ALLOCATED") || state.contains("MIXED"));
        self.total_cpus = self.total_cpus.saturating_add(row.cpus_total);
        self.allocated_cpus = self.allocated_cpus.saturating_add(row.cpus_alloc);
        self.total_memory_gb += row.memory_total_gb;
        self.allocated_memory_gb += row.memory_alloc_gb;
    }
}

pub fn aggregate_pending_queue(jobs: &[AllUsersJob]) -> BTreeMap<String, PendingPartitionStats> {
    let mut queue = BTreeMap::<String, PendingPartitionStats>::new();
    for job in jobs.iter().filter(|job| is_pending_state(&job.state)) {
        let tasks = parse_array_size(job.id.trim()) as u64;
        let resources = parse_tres_resources(&job.tres);
        let partition = match job.partition.trim() {
            "" => "unknown",
            name => name,
        };
        let group = queue.entry(partition.into()).or_default();
        group.jobs_count = group.jobs_count.saturating_add(tasks);
        group.cpus = group
            .cpus
            .saturating_add(resources.cpus.saturating_mul(tasks));
        group.memory_gb += resources.memory_gb * tasks as f64;
        for (gpu_type, count) in aggregate_gpu_counts(&resources.gpus, true) {
            add_count(
                &mut group.gpus_by_type,
                gpu_type,
                count.saturating_mul(tasks),
            );
        }
    }
    queue
}

fn add_count(counts: &mut BTreeMap<String, u64>, key: String, count: u64) {
    let current = counts.entry(key).or_default();
    *current = current.saturating_add(count);
}

#[derive(Default)]
struct UserAccumulator {
    stats: UserStats,
    gpu_types: BTreeMap<String, u64>,
    node_names: BTreeSet<String>,
    array_ids: BTreeSet<String>,
}

pub fn aggregate_user_stats(
    jobs: &[AllUsersJob],
    models: &BTreeMap<String, String>,
) -> Vec<UserStats> {
    let mut users: BTreeMap<String, UserAccumulator> = BTreeMap::new();
    for job in jobs
        .iter()
        .filter(|job| !is_pending_state(&job.state) && !job.user.trim().is_empty())
    {
        let user = users.entry(job.user.trim().into()).or_default();
        accumulate_user(
            user,
            &job.id,
            &job.node_list,
            &job.num_nodes,
            &job.tres,
            models,
        );
    }
    let mut rows: Vec<UserStats> = users
        .into_iter()
        .map(|(username, user)| finish_user_stats(username, user))
        .collect();
    rows.sort_by(|a, b| {
        b.total_cpus
            .cmp(&a.total_cpus)
            .then_with(|| a.username.cmp(&b.username))
    });
    rows
}

pub fn aggregate_running_job_stats(
    username: &str,
    jobs: &[RunningJob],
    models: &BTreeMap<String, String>,
) -> UserStats {
    let mut user = UserAccumulator::default();
    for job in jobs
        .iter()
        .filter(|job| !is_pending_state(&job.state) && !is_terminal_state(&job.state))
    {
        accumulate_user(
            &mut user,
            &job.id,
            &job.node_list,
            &job.nodes,
            &job.tres,
            models,
        );
    }
    finish_user_stats(username.into(), user)
}

fn finish_user_stats(username: String, mut user: UserAccumulator) -> UserStats {
    user.stats.username = username;
    user.stats.gpu_types = format_gpu_types(&user.gpu_types);
    user.stats.total_nodes = user.node_names.len() as u64;
    user.stats.node_names = user.node_names.into_iter().collect::<Vec<_>>().join(",");
    user.stats.array_count = user.array_ids.len();
    user.stats
}

fn accumulate_user(
    user: &mut UserAccumulator,
    id: &str,
    node_list: &str,
    num_nodes: &str,
    tres: &str,
    models: &BTreeMap<String, String>,
) {
    user.stats.job_count += 1;
    if let Some((base, _)) = id.split_once('_') {
        user.array_ids.insert(base.into());
    } else {
        user.stats.plain_job_count += 1;
    }
    let nodes = expand_node_list(node_list);
    user.node_names.extend(nodes.iter().cloned());
    let resources = parse_tres_resources(tres);
    let cpus = if resources.cpus > 0 {
        resources.cpus
    } else {
        parse_node_count(num_nodes)
    };
    user.stats.total_cpus = user.stats.total_cpus.saturating_add(cpus);
    user.stats.total_memory_gb += resources.memory_gb;
    let mut counts = aggregate_gpu_counts(&resources.gpus, true);
    if let Some(generic) = counts.get("GPU").copied() {
        user.stats.generic_gpu_jobs += 1;
        if let Some(model) = single_node_model(&nodes, models) {
            counts.remove("GPU");
            add_count(&mut counts, model, generic);
        }
    }
    for (gpu_type, count) in counts {
        user.stats.total_gpus = user.stats.total_gpus.saturating_add(count);
        add_count(&mut user.gpu_types, gpu_type, count);
    }
}

fn single_node_model(nodes: &[String], models: &BTreeMap<String, String>) -> Option<String> {
    let model = models.get(nodes.first()?)?;
    nodes
        .iter()
        .all(|node| models.get(node) == Some(model))
        .then(|| model.clone())
}

pub fn parse_node_count(nodes: &str) -> u64 {
    number(nodes.split_once('-').map_or(nodes, |(first, _)| first))
}

pub fn aggregate_pending_user_stats(jobs: &[AllUsersJob]) -> Vec<UserPendingStats> {
    let mut users: BTreeMap<String, PendingAccumulator> = BTreeMap::new();
    for job in jobs
        .iter()
        .filter(|job| is_pending_state(&job.state) && !job.user.trim().is_empty())
    {
        let PendingAccumulator {
            stats,
            gpus,
            reasons,
        } = users.entry(job.user.trim().into()).or_default();
        let tasks = parse_array_size(&job.id) as u64;
        let resources = parse_tres_resources(&job.tres);
        stats.pending_job_count = stats.pending_job_count.saturating_add(tasks);
        stats.pending_cpus = stats
            .pending_cpus
            .saturating_add(resources.cpus.saturating_mul(tasks));
        stats.pending_memory_gb += resources.memory_gb * tasks as f64;
        let reason = job.reason.split(',').next().unwrap_or("").trim();
        if !reason.is_empty() {
            add_count(reasons, reason.into(), tasks);
        }
        for (gpu_type, count) in aggregate_gpu_counts(&resources.gpus, true) {
            let count = count.saturating_mul(tasks);
            stats.pending_gpus = stats.pending_gpus.saturating_add(count);
            add_count(gpus, gpu_type, count);
        }
    }
    let mut rows: Vec<UserPendingStats> = users
        .into_iter()
        .map(
            |(
                username,
                PendingAccumulator {
                    mut stats,
                    gpus,
                    reasons,
                },
            )| {
                stats.username = username;
                stats.pending_gpu_types = format_gpu_types(&gpus);
                stats.pending_reasons = format_pending_reasons(&reasons);
                stats
            },
        )
        .collect();
    rows.sort_by(|a, b| {
        b.pending_cpus
            .cmp(&a.pending_cpus)
            .then_with(|| a.username.cmp(&b.username))
    });
    rows
}

#[derive(Default)]
struct PendingAccumulator {
    stats: UserPendingStats,
    gpus: BTreeMap<String, u64>,
    reasons: BTreeMap<String, u64>,
}

pub fn format_pending_reasons(counts: &BTreeMap<String, u64>) -> String {
    let mut reasons: Vec<_> = counts.iter().collect();
    reasons.sort_by(|(a, ac), (b, bc)| bc.cmp(ac).then_with(|| a.cmp(b)));
    reasons
        .into_iter()
        .map(|(reason, count)| format!("{count}x {reason}"))
        .collect::<Vec<_>>()
        .join(", ")
}

pub fn find_user_stats<'a>(users: &'a [UserStats], username: &str) -> Option<&'a UserStats> {
    users.iter().find(|user| user.username == username)
}

pub fn aggregate_account_resources(jobs: &[AllUsersJob]) -> AccountResourceUsage {
    let mut usage = AccountResourceUsage::default();
    let mut nodes = BTreeSet::new();
    for job in jobs {
        let resources = parse_tres_resources(&job.tres);
        usage.total_cpus = usage.total_cpus.saturating_add(resources.cpus);
        usage.total_memory_gb += resources.memory_gb;
        usage.total_gpus = usage
            .total_gpus
            .saturating_add(calculate_total_gpus(&resources.gpus, true));
        nodes.extend(expand_node_list(&job.node_list));
    }
    usage.unique_nodes = nodes.len() as u64;
    usage
}

pub fn jobs_on_node(jobs: &[AllUsersJob], node: &str) -> Vec<NodeJob> {
    let mut rows: Vec<_> = jobs
        .iter()
        .filter(|job| {
            expand_node_list(&job.node_list)
                .iter()
                .any(|name| name == node.trim())
        })
        .map(|job| {
            let resources = parse_tres_resources(&job.tres);
            NodeJob {
                id: job.id.trim().into(),
                name: job.name.trim().into(),
                user: job.user.trim().into(),
                time: job.time.trim().into(),
                cpus: resources.cpus,
                gpus: calculate_total_gpus(&resources.gpus, true),
            }
        })
        .collect();
    rows.sort_by(|a, b| a.user.cmp(&b.user).then_with(|| a.id.cmp(&b.id)));
    rows
}
