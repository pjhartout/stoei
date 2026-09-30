use std::time::Duration;

use super::{PartitionStanding, PriorityFactors};

pub fn format_percent(fraction: &str) -> String {
    let Some(value) = fraction
        .trim()
        .parse::<f64>()
        .ok()
        .filter(|value| value.is_finite())
    else {
        return String::new();
    };
    let percent = value * 100.0;
    if percent < 10.0 {
        format!("{percent:.2}%")
    } else {
        format!("{percent:.1}%")
    }
}

pub fn format_ratio(ratio: f64, valid: bool) -> String {
    if !valid || !ratio.is_finite() || ratio <= 0.0 {
        String::new()
    } else if ratio < 1.0 {
        format!("{ratio:.2}×")
    } else {
        format!("{ratio:.1}×")
    }
}

pub fn format_rank(rank: usize, total: usize, noun: &str) -> String {
    if total == 0 || rank == 0 {
        return String::new();
    }
    let percent = rank.saturating_mul(100) / total;
    let position = if percent <= 50 {
        format!("top {}%", percent.max(1))
    } else {
        format!("bottom {}%", 100usize.saturating_sub(percent).max(1))
    };
    format!("{rank} of {total} {noun} ({position})")
}

pub fn format_days(duration: Duration) -> String {
    let seconds = duration.as_secs();
    if seconds >= 86_400 {
        format!("{}d", seconds.saturating_add(43_200) / 86_400)
    } else if seconds < 3_600 {
        "<1h".into()
    } else {
        format!("{}h", seconds.saturating_add(1_800) / 3_600)
    }
}

pub fn format_queue(position: usize, total: usize) -> String {
    format!("#{position}/{total}")
}

pub fn format_breakdown(factors: &PriorityFactors) -> String {
    factors
        .contributions()
        .into_iter()
        .map(|factor| format!("{} {}", factor.name, factor.value))
        .collect::<Vec<_>>()
        .join(" · ")
}

pub fn format_standing(standing: &PartitionStanding) -> String {
    let ahead = if standing.best.partition == 1 {
        "first in line".into()
    } else {
        format!("{} ahead of you", standing.best.partition.saturating_sub(1))
    };
    let mut result = format!(
        "best at #{} of {} · {ahead}",
        standing.best.partition, standing.best.partition_total
    );
    if standing.jobs > 1 {
        result.push_str(&format!(" · {} jobs", standing.jobs));
    }
    result
}

pub fn state_role(state: &str) -> &'static str {
    let state = state
        .split_whitespace()
        .next()
        .unwrap_or("")
        .to_ascii_uppercase();
    match state.as_str() {
        "RUNNING" | "R" | "COMPLETING" | "CG" | "COMPLETED" | "CD" | "IDLE" => "success",
        "PENDING" | "PD" | "PREEMPTED" | "PR" | "SUSPENDED" | "S" | "REQUEUED" | "RQ"
        | "ALLOCATED" | "ALLOC" | "MIXED" | "MIX" | "CONFIGURING" | "CF" | "DRAINING" => "warning",
        "FAILED" | "F" | "TIMEOUT" | "TO" | "NODE_FAIL" | "NF" | "OUT_OF_MEMORY" | "OOM"
        | "BOOT_FAIL" | "BF" | "DOWN" | "DRAIN" | "DRAINED" => "error",
        "CANCELLED" | "CA" | "CANCELED" => "muted",
        _ => "",
    }
}
