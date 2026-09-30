use std::collections::{BTreeMap, BTreeSet};

use super::{
    AllUsersJob, GPUEntry, Node, aggregate_gpu_counts, calculate_total_gpus, expand_node_list,
    format_gpu_types, parse_array_size, parse_gpu_entries, parse_gpu_from_gres,
    parse_tres_resources,
};

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PendingPartitionStats {
    pub jobs_count: u64,
    pub cpus: u64,
    pub memory_gb: f64,
    pub gpus: u64,
    pub gpus_by_type: BTreeMap<String, u64>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GPUTotalAlloc {
    pub total: u64,
    pub allocated: u64,
    pub unavail: u64,
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
    pub total_gpus: u64,
    pub allocated_gpus: u64,
    pub unavail_gpus: u64,
    pub gpus_by_type: BTreeMap<String, GPUTotalAlloc>,
    pub draining_nodes: u64,
    pub offline_nodes: u64,
    pub pending_jobs_count: u64,
    pub pending_cpus: u64,
    pub pending_memory_gb: f64,
    pub pending_gpus: u64,
    pub pending_gpus_by_type: BTreeMap<String, u64>,
    pub pending_by_partition: BTreeMap<String, PendingPartitionStats>,
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
    pub fn free_gpus_pct(&self) -> f64 {
        percent(
            self.total_gpus.saturating_sub(self.allocated_gpus) as f64,
            self.total_gpus.saturating_add(self.unavail_gpus) as f64,
        )
    }
    pub fn gpu_type_free_pct(&self, gpu_type: &str) -> f64 {
        self.gpus_by_type.get(gpu_type).map_or(0.0, |gpu| {
            percent(
                gpu.total.saturating_sub(gpu.allocated) as f64,
                gpu.total.saturating_add(gpu.unavail) as f64,
            )
        })
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
    pub gpus_alloc: u64,
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
    pub fn gpu_usage_pct(&self) -> f64 {
        percent(self.gpus_alloc as f64, self.gpus_total as f64)
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

fn allocated(state: &str) -> bool {
    state.contains("ALLOCATED") || state.contains("MIXED")
}

pub fn node_gpu_model(node: &Node) -> String {
    let mut models = parse_gpu_from_gres(&node.gres)
        .into_iter()
        .filter(|gpu| !gpu.gpu_type.eq_ignore_ascii_case("gpu"));
    let Some(first) = models.next() else {
        return String::new();
    };
    if models.all(|gpu| gpu.gpu_type.eq_ignore_ascii_case(&first.gpu_type)) {
        first.gpu_type.to_ascii_uppercase()
    } else {
        String::new()
    }
}

fn relabel_generic(mut entries: Vec<GPUEntry>, model: &str) -> Vec<GPUEntry> {
    if !model.is_empty()
        && !entries
            .iter()
            .any(|gpu| !gpu.gpu_type.eq_ignore_ascii_case("gpu"))
    {
        for gpu in &mut entries {
            gpu.gpu_type = model.into();
        }
    }
    entries
}

fn configured_gpus(node: &Node, model: &str) -> Vec<GPUEntry> {
    let entries = parse_gpu_entries(&node.cfg_tres);
    if entries.is_empty() {
        relabel_generic(parse_gpu_from_gres(&node.gres), model)
    } else {
        relabel_generic(entries, model)
    }
}

pub fn derive_cluster_stats(nodes: &[Node], jobs: &[AllUsersJob]) -> ClusterStats {
    let mut stats = ClusterStats::default();
    for node in nodes {
        let state = node.state.to_ascii_uppercase();
        let model = node_gpu_model(node);
        if node_offline(&state) {
            stats.offline_nodes += 1;
            record_gpus(
                &mut stats,
                configured_gpus(node, &model),
                GPUKind::Unavailable,
            );
            continue;
        }
        let draining = state.contains("DRAIN");
        if draining {
            stats.draining_nodes += 1;
        } else {
            stats.total_nodes += 1;
            if state.contains("IDLE") {
                stats.free_nodes += 1;
            }
            stats.total_cpus = stats.total_cpus.saturating_add(number(&node.cpu_tot));
            stats.total_memory_gb += number(&node.real_mem) as f64 / 1024.0;
            if allocated(&state) {
                stats.allocated_nodes += 1;
            }
            stats.allocated_cpus = stats.allocated_cpus.saturating_add(number(&node.cpu_alloc));
            stats.allocated_memory_gb += number(&node.alloc_mem) as f64 / 1024.0;
        }
        if draining {
            record_gpus(
                &mut stats,
                configured_gpus(node, &model),
                GPUKind::Unavailable,
            );
            continue;
        }
        let total = configured_gpus(node, &model);
        let allocation = if !node.alloc_tres.is_empty() {
            relabel_generic(parse_gpu_entries(&node.alloc_tres), &model)
        } else if node.cfg_tres.is_empty() && allocated(&state) {
            total.clone()
        } else {
            Vec::new()
        };
        record_gpus(&mut stats, total, GPUKind::Total);
        record_gpus(&mut stats, allocation, GPUKind::Allocated);
    }
    aggregate_pending(jobs, &mut stats);
    stats
}

enum GPUKind {
    Total,
    Allocated,
    Unavailable,
}

fn record_gpus(stats: &mut ClusterStats, entries: Vec<GPUEntry>, kind: GPUKind) {
    for (gpu_type, count) in aggregate_gpu_counts(&entries, true) {
        let gpu = stats.gpus_by_type.entry(gpu_type).or_default();
        match kind {
            GPUKind::Total => {
                gpu.total = gpu.total.saturating_add(count);
                stats.total_gpus = stats.total_gpus.saturating_add(count);
            }
            GPUKind::Allocated => {
                gpu.allocated = gpu.allocated.saturating_add(count);
                stats.allocated_gpus = stats.allocated_gpus.saturating_add(count);
            }
            GPUKind::Unavailable => {
                gpu.unavail = gpu.unavail.saturating_add(count);
                stats.unavail_gpus = stats.unavail_gpus.saturating_add(count);
            }
        }
    }
}

fn aggregate_pending(jobs: &[AllUsersJob], stats: &mut ClusterStats) {
    for job in jobs.iter().filter(|job| is_pending_state(&job.state)) {
        let tasks = parse_array_size(job.id.trim()) as u64;
        let resources = parse_tres_resources(&job.tres);
        let partition = if job.partition.trim().is_empty() {
            "unknown"
        } else {
            job.partition.trim()
        };
        let group = stats
            .pending_by_partition
            .entry(partition.into())
            .or_default();
        stats.pending_jobs_count = stats.pending_jobs_count.saturating_add(tasks);
        group.jobs_count = group.jobs_count.saturating_add(tasks);
        let cpus = resources.cpus.saturating_mul(tasks);
        stats.pending_cpus = stats.pending_cpus.saturating_add(cpus);
        group.cpus = group.cpus.saturating_add(cpus);
        let memory = resources.memory_gb * tasks as f64;
        stats.pending_memory_gb += memory;
        group.memory_gb += memory;
        for (gpu_type, count) in aggregate_gpu_counts(&resources.gpus, true) {
            let count = count.saturating_mul(tasks);
            stats.pending_gpus = stats.pending_gpus.saturating_add(count);
            group.gpus = group.gpus.saturating_add(count);
            add_count(&mut stats.pending_gpus_by_type, gpu_type.clone(), count);
            add_count(&mut group.gpus_by_type, gpu_type, count);
        }
    }
}

pub fn derive_node_displays(nodes: &[Node]) -> Vec<NodeDisplay> {
    nodes
        .iter()
        .filter(|node| !node.name.trim().is_empty())
        .map(|node| {
            let state = if node.state.trim().is_empty() {
                "UNKNOWN"
            } else {
                node.state.trim()
            };
            let model = node_gpu_model(node);
            let total = configured_gpus(node, &model);
            let gpus_total = calculate_total_gpus(&total, true);
            let gpus_alloc = if node.alloc_tres.is_empty() {
                if allocated(&state.to_ascii_uppercase()) {
                    gpus_total
                } else {
                    0
                }
            } else {
                calculate_total_gpus(&parse_gpu_entries(&node.alloc_tres), true)
            };
            NodeDisplay {
                name: node.name.trim().into(),
                state: state.into(),
                cpus_alloc: number(&node.cpu_alloc),
                cpus_total: number(&node.cpu_tot),
                memory_alloc_gb: number(&node.alloc_mem) as f64 / 1024.0,
                memory_total_gb: number(&node.real_mem) as f64 / 1024.0,
                gpus_alloc,
                gpus_total,
                gpu_types: format_gpu_counts(&aggregate_gpu_counts(&total, true)),
                partitions: node
                    .fields
                    .get("Partitions")
                    .filter(|value| !value.trim().is_empty())
                    .cloned()
                    .unwrap_or_else(|| "N/A".into()),
                reason: node.reason.trim().into(),
            }
        })
        .collect()
}

pub fn node_gpu_models(nodes: &[Node]) -> BTreeMap<String, String> {
    nodes
        .iter()
        .filter_map(|node| {
            let model = node_gpu_model(node);
            (!node.name.trim().is_empty() && !model.is_empty())
                .then(|| (node.name.trim().into(), model))
        })
        .collect()
}

pub fn format_gpu_counts(counts: &BTreeMap<String, u64>) -> String {
    format_gpu_types(counts)
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
        accumulate_user(user, job, models);
    }
    let mut rows: Vec<UserStats> = users
        .into_iter()
        .map(|(username, mut user)| {
            user.stats.username = username;
            user.stats.gpu_types = format_gpu_counts(&user.gpu_types);
            user.stats.total_nodes = user.node_names.len() as u64;
            user.stats.node_names = user.node_names.into_iter().collect::<Vec<_>>().join(",");
            user.stats.array_count = user.array_ids.len();
            user.stats
        })
        .collect();
    rows.sort_by(|a, b| {
        b.total_cpus
            .cmp(&a.total_cpus)
            .then_with(|| a.username.cmp(&b.username))
    });
    rows
}

fn accumulate_user(
    user: &mut UserAccumulator,
    job: &AllUsersJob,
    models: &BTreeMap<String, String>,
) {
    user.stats.job_count += 1;
    if let Some((base, _)) = job.id.split_once('_') {
        user.array_ids.insert(base.into());
    } else {
        user.stats.plain_job_count += 1;
    }
    let nodes = expand_node_list(&job.node_list);
    user.node_names.extend(nodes.iter().cloned());
    let resources = parse_tres_resources(&job.tres);
    let cpus = if resources.cpus > 0 {
        resources.cpus
    } else {
        parse_node_count(&job.num_nodes)
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
                stats.pending_gpu_types = format_gpu_counts(&gpus);
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
