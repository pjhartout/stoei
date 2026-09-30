use std::collections::BTreeMap;

use super::{
    JobUsage, calculate_total_gpus, is_mig_type, parse_elapsed_to_seconds, parse_gpu_entries,
    parse_gpu_from_gres, parse_tres_resources,
};

#[derive(Clone, Debug, Default, PartialEq)]
pub struct JobEfficiency {
    pub live: bool,
    pub sampled: bool,
    pub cpu_percent: f64,
    pub cpu_known: bool,
    pub cpu_time_sec: f64,
    pub cpu_avail_sec: f64,
    pub alloc_cpus: u64,
    pub max_rss_bytes: u64,
    pub req_mem_bytes: u64,
    pub mem_percent: f64,
    pub mem_known: bool,
    pub gpu_count: u64,
    pub gpu_is_mig: bool,
    pub gpu_util_percent: f64,
    pub gpu_util_known: bool,
    pub gpu_mem_bytes: u64,
    pub gpu_mem_known: bool,
    pub disk_read_bytes: u64,
    pub disk_write_bytes: u64,
    pub read_bytes_per_sec: f64,
    pub write_bytes_per_sec: f64,
    pub elapsed_sec: f64,
}

pub fn derive_job_efficiency(usage: &JobUsage, fields: &BTreeMap<String, String>) -> JobEfficiency {
    let mut efficiency = JobEfficiency {
        live: usage.source == "sstat",
        sampled: usage.sampled,
        cpu_time_sec: usage.cpu_time_sec,
        max_rss_bytes: usage.max_rss_bytes,
        gpu_mem_bytes: usage.gpu_mem_bytes,
        gpu_mem_known: usage.gpu_mem_known,
        disk_read_bytes: usage.disk_read_bytes,
        disk_write_bytes: usage.disk_write_bytes,
        ..JobEfficiency::default()
    };
    fill_allocation(&mut efficiency, usage, fields);
    fill_percentages(&mut efficiency, usage);
    efficiency
}

fn fill_allocation(
    efficiency: &mut JobEfficiency,
    usage: &JobUsage,
    fields: &BTreeMap<String, String>,
) {
    let field = |key: &str| fields.get(key).map_or("", String::as_str);
    efficiency.elapsed_sec = if usage.elapsed_sec > 0.0 {
        usage.elapsed_sec
    } else {
        parse_elapsed_to_seconds(field("RunTime"))
    };
    efficiency.alloc_cpus = if usage.alloc_cpus > 0 {
        usage.alloc_cpus
    } else {
        field("NumCPUs").trim().parse().unwrap_or(0)
    };
    let memory = ["TRES", "AllocTRES", "ReqTRES"]
        .iter()
        .map(|key| parse_tres_resources(field(key)).memory_gb)
        .find(|memory| *memory > 0.0)
        .unwrap_or(0.0);
    let fallback;
    let gpus = if usage.gpus.is_empty() {
        fallback = ["TRES", "AllocTRES", "ReqTRES"]
            .iter()
            .map(|key| parse_gpu_entries(field(key)))
            .find(|gpus| !gpus.is_empty())
            .unwrap_or_else(|| parse_gpu_from_gres(field("TresPerNode")));
        &fallback
    } else {
        &usage.gpus
    };
    efficiency.gpu_count = calculate_total_gpus(gpus, true);
    efficiency.gpu_is_mig = gpus.iter().any(|gpu| is_mig_type(&gpu.gpu_type));
    efficiency.req_mem_bytes = (memory * (1u64 << 30) as f64) as u64;
}

fn fill_percentages(efficiency: &mut JobEfficiency, usage: &JobUsage) {
    efficiency.cpu_known =
        efficiency.sampled && efficiency.elapsed_sec > 0.0 && efficiency.alloc_cpus > 0;
    if efficiency.cpu_known {
        efficiency.cpu_avail_sec = efficiency.elapsed_sec * efficiency.alloc_cpus as f64;
        efficiency.cpu_percent = 100.0 * efficiency.cpu_time_sec / efficiency.cpu_avail_sec;
    }
    efficiency.mem_known =
        efficiency.sampled && efficiency.req_mem_bytes > 0 && efficiency.max_rss_bytes > 0;
    if efficiency.mem_known {
        efficiency.mem_percent =
            100.0 * efficiency.max_rss_bytes as f64 / efficiency.req_mem_bytes as f64;
    }
    efficiency.gpu_util_known = usage.gpu_util_known && !efficiency.gpu_is_mig;
    if efficiency.gpu_count > 0 {
        efficiency.gpu_util_percent =
            (usage.gpu_util_percent / efficiency.gpu_count as f64).clamp(0.0, 100.0);
    }
    if efficiency.elapsed_sec > 0.0 {
        efficiency.read_bytes_per_sec = efficiency.disk_read_bytes as f64 / efficiency.elapsed_sec;
        efficiency.write_bytes_per_sec =
            efficiency.disk_write_bytes as f64 / efficiency.elapsed_sec;
    }
}
