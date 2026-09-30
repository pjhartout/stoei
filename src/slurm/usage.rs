use super::*;

pub const SACCT_USAGE_FORMAT: &str = "JobID,ElapsedRaw,AllocCPUS,TotalCPU,AllocTRES,MaxRSS,TRESUsageInTot,TRESUsageInAve,TRESUsageInMax,TRESUsageOutTot";
pub const SSTAT_USAGE_FORMAT: &str =
    "JobID,MaxRSS,TRESUsageInTot,TRESUsageInAve,TRESUsageInMax,TRESUsageOutTot";

pub fn parse_sacct_usage(job_id: &str, raw: &str) -> JobUsage {
    let mut usage = JobUsage {
        source: "sacct".into(),
        ..JobUsage::default()
    };
    let prefix = format!("{job_id}.");
    for line in raw.lines() {
        let f: Vec<_> = line.splitn(10, '|').collect();
        if f.len() < 10 {
            continue;
        }
        let id = f[0].trim();
        if id == job_id {
            usage.elapsed_sec = parse_elapsed_to_seconds(f[1]);
            usage.alloc_cpus = f[2].trim().parse().unwrap_or(0);
            usage.cpu_time_sec = parse_elapsed_to_seconds(f[3]);
            usage.gpus = parse_gpu_entries(f[4]);
        } else if id.starts_with(&prefix) && !id.ends_with(".extern") {
            merge_step_usage(&mut usage, f[5], f[6], f[7], f[8], f[9]);
        }
    }
    usage
}

pub fn parse_sstat_usage(job_id: &str, raw: &str) -> JobUsage {
    let mut usage = JobUsage {
        source: "sstat".into(),
        ..JobUsage::default()
    };
    let prefix = format!("{job_id}.");
    for line in raw.lines() {
        let f: Vec<_> = line.splitn(6, '|').collect();
        if f.len() < 6 || !f[0].trim().starts_with(&prefix) || f[0].trim().ends_with(".extern") {
            continue;
        }
        merge_step_usage(&mut usage, f[1], f[2], f[3], f[4], f[5]);
        usage.cpu_time_sec += parse_elapsed_to_seconds(
            &parse_tres_pairs(f[2])
                .get("cpu")
                .cloned()
                .unwrap_or_default(),
        );
    }
    usage
}

fn merge_step_usage(
    u: &mut JobUsage,
    rss: &str,
    in_tot: &str,
    in_ave: &str,
    in_max: &str,
    out_tot: &str,
) {
    u.sampled |= !rss.trim().is_empty() || !in_ave.trim().is_empty();
    u.max_rss_bytes = u.max_rss_bytes.max(parse_size_bytes(rss));
    let reads = parse_tres_pairs(in_tot);
    let writes = parse_tres_pairs(out_tot);
    u.disk_read_bytes = u
        .disk_read_bytes
        .saturating_add(parse_size_bytes(field(&reads, "fs/disk")));
    u.disk_write_bytes = u
        .disk_write_bytes
        .saturating_add(parse_size_bytes(field(&writes, "fs/disk")));
    let ave = parse_tres_pairs(in_ave);
    if let Some(util) = ave
        .get("gres/gpuutil")
        .and_then(|v| v.parse::<f64>().ok())
        .filter(|v| v.is_finite())
    {
        u.gpu_util_known = true;
        u.gpu_util_percent = u.gpu_util_percent.max(util);
    }
    let max = parse_tres_pairs(in_max);
    let memory = max
        .get("gres/gpumem")
        .filter(|v| !v.trim().is_empty())
        .or_else(|| ave.get("gres/gpumem"));
    if let Some(memory) = memory.filter(|v| !v.trim().is_empty()) {
        u.gpu_mem_known = true;
        u.gpu_mem_bytes = u.gpu_mem_bytes.max(parse_size_bytes(memory));
    }
}
