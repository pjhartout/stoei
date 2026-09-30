use std::collections::{BTreeMap, BTreeSet};

use super::GPUEntry;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TRESResources {
    pub cpus: u64,
    pub memory_gb: f64,
    pub gpus: Vec<GPUEntry>,
}

pub fn normalize_array_job_id(id: &str) -> String {
    id.split_once("_[").map_or(id, |(base, _)| base).into()
}

pub fn parse_array_size(id: &str) -> usize {
    let Some((_, spec)) = id.split_once("_[") else {
        return 1;
    };
    let Some((spec, _)) = spec.split_once(']') else {
        return 1;
    };
    let spec = match spec.rsplit_once('%') {
        Some((spec, throttle)) if throttle.parse::<u64>().is_ok() => spec,
        _ => spec,
    };
    let count = spec.split(',').fold(0_usize, |sum, part| {
        let count = match part.trim().split_once('-') {
            Some((start, end)) => match (start.parse::<usize>(), end.parse::<usize>()) {
                (Ok(start), Ok(end)) if end >= start => end.saturating_sub(start).saturating_add(1),
                _ => 1,
            },
            None => usize::from(part.trim().parse::<u64>().is_ok()),
        };
        sum.saturating_add(count)
    });
    count.max(1)
}

pub fn parse_tres_pairs(raw: &str) -> BTreeMap<String, String> {
    raw.split(',')
        .filter_map(|part| part.split_once('='))
        .map(|(key, value)| (key.trim().into(), value.trim().into()))
        .collect()
}

pub fn parse_gpu_entries(raw: &str) -> Vec<GPUEntry> {
    raw.split(',')
        .filter_map(|part| {
            let (key, count) = part.trim().split_once('=')?;
            let lower = key.to_ascii_lowercase();
            let gpu_type = if lower == "gres/gpu" {
                "gpu"
            } else if lower.starts_with("gres/gpu:") {
                &key[9..]
            } else {
                return None;
            };
            Some(GPUEntry {
                gpu_type: gpu_type.into(),
                count: count.parse().ok()?,
            })
        })
        .collect()
}

pub fn parse_gpu_from_gres(raw: &str) -> Vec<GPUEntry> {
    raw.split(',')
        .filter_map(|part| {
            let part = part.trim();
            let start = part.to_ascii_lowercase().find("gpu:")?;
            let body = part[start + 4..].split('(').next().unwrap_or("");
            let (gpu_type, count) = body.split_once(':').unwrap_or(("gpu", body));
            Some(GPUEntry {
                gpu_type: gpu_type.to_ascii_uppercase(),
                count: count.parse().ok()?,
            })
        })
        .collect()
}

pub fn has_specific_gpu_types(entries: &[GPUEntry]) -> bool {
    entries
        .iter()
        .any(|entry| !entry.gpu_type.eq_ignore_ascii_case("gpu"))
}

pub fn aggregate_gpu_counts(entries: &[GPUEntry], prefer_specific: bool) -> BTreeMap<String, u64> {
    let specific = prefer_specific && has_specific_gpu_types(entries);
    let mut counts: BTreeMap<String, u64> = BTreeMap::new();
    for entry in entries {
        if specific && entry.gpu_type.eq_ignore_ascii_case("gpu") {
            continue;
        }
        let count = counts
            .entry(entry.gpu_type.to_ascii_uppercase())
            .or_default();
        *count = count.saturating_add(entry.count);
    }
    counts
}

pub fn calculate_total_gpus(entries: &[GPUEntry], prefer_specific: bool) -> u64 {
    aggregate_gpu_counts(entries, prefer_specific)
        .values()
        .fold(0_u64, |sum, count| sum.saturating_add(*count))
}

pub fn format_gpu_types(counts: &BTreeMap<String, u64>) -> String {
    counts
        .iter()
        .map(|(name, count)| format!("{count}x {}", short_gpu_label(name)))
        .collect::<Vec<_>>()
        .join(", ")
}

fn mig_profile(typ: &str) -> Option<&str> {
    let bytes = typ.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if !bytes[i].is_ascii_digit() {
            i += 1;
            continue;
        }
        let start = i;
        while i < bytes.len() && bytes[i].is_ascii_digit() {
            i += 1;
        }
        if !bytes
            .get(i..i + 2)
            .is_some_and(|s| s.eq_ignore_ascii_case(b"g."))
        {
            continue;
        }
        i += 2;
        let digits = i;
        while i < bytes.len() && bytes[i].is_ascii_digit() {
            i += 1;
        }
        if i > digits
            && bytes
                .get(i..i + 2)
                .is_some_and(|s| s.eq_ignore_ascii_case(b"gb"))
        {
            return typ.get(start..i + 2);
        }
        i = digits;
    }
    None
}

pub fn is_mig_type(typ: &str) -> bool {
    mig_profile(typ).is_some()
}

pub fn short_gpu_label(typ: &str) -> String {
    mig_profile(typ).map_or_else(|| typ.into(), str::to_ascii_lowercase)
}

pub fn parse_tres_resources(raw: &str) -> TRESResources {
    let pairs = parse_tres_pairs(raw);
    let memory_gb = pairs
        .iter()
        .find(|(key, _)| key.eq_ignore_ascii_case("mem"))
        .map_or(0.0, |(_, memory)| {
            let Some(unit) = memory.as_bytes().last() else {
                return 0.0;
            };
            let Some(digits) = memory.get(..memory.len() - 1) else {
                return 0.0;
            };
            let value = digits.parse::<u64>().unwrap_or(0) as f64;
            match unit.to_ascii_uppercase() {
                b'G' => value,
                b'M' => value / 1024.0,
                b'T' => value * 1024.0,
                _ => 0.0,
            }
        });
    TRESResources {
        cpus: parse_cpu_count_from_tres(raw),
        memory_gb,
        gpus: parse_gpu_entries(raw),
    }
}

pub fn parse_cpu_count_from_tres(raw: &str) -> u64 {
    raw.split(',')
        .filter_map(|part| part.split_once('='))
        .find(|(key, _)| key.trim().eq_ignore_ascii_case("cpu"))
        .and_then(|(_, count)| count.trim().parse().ok())
        .unwrap_or(0)
}

pub fn parse_size_bytes(raw: &str) -> u64 {
    let raw = raw.trim();
    let Some(unit) = raw.as_bytes().last() else {
        return 0;
    };
    let multiplier = match unit.to_ascii_uppercase() {
        b'K' => 1024_f64,
        b'M' => 1048576_f64,
        b'G' => 1073741824_f64,
        b'T' => 1099511627776_f64,
        _ => 1.0,
    };
    let digits = if multiplier == 1.0 {
        raw
    } else {
        &raw[..raw.len() - 1]
    };
    let value = digits.parse::<f64>().unwrap_or(0.0);
    if !value.is_finite() || value < 0.0 {
        return 0;
    }
    (value * multiplier) as u64
}

const MAX_NODE_EXPANSION: usize = 100_000;

pub fn expand_node_list(raw: &str) -> Vec<String> {
    try_expand_node_list(raw).unwrap_or_default()
}

pub fn try_expand_node_list(raw: &str) -> Result<Vec<String>, String> {
    let raw = raw.trim();
    if raw.is_empty() || raw.starts_with('(') {
        return Ok(Vec::new());
    }
    let mut nodes = BTreeSet::new();
    let mut remaining = MAX_NODE_EXPANSION;
    let mut depth = 0_u32;
    let mut start = 0;
    for (i, character) in raw.char_indices() {
        match character {
            '[' => depth = depth.saturating_add(1),
            ']' => depth = depth.saturating_sub(1),
            ',' if depth == 0 => {
                expand_node_token(&raw[start..i], &mut nodes, &mut remaining)?;
                start = i + 1;
            }
            _ => {}
        }
    }
    expand_node_token(&raw[start..], &mut nodes, &mut remaining)?;
    Ok(nodes.into_iter().collect())
}

fn expand_node_token(
    token: &str,
    nodes: &mut BTreeSet<String>,
    remaining: &mut usize,
) -> Result<(), String> {
    let Some((prefix, bracket)) = token.split_once('[') else {
        if !token.is_empty() {
            consume_node_budget(remaining, 1, token)?;
            nodes.insert(token.into());
        }
        return Ok(());
    };
    let Some((spec, _)) = bracket.split_once(']') else {
        return Ok(());
    };
    for part in spec.split(',') {
        if let Some((start, end)) = part.split_once('-') {
            let (Ok(first), Ok(last)) = (start.parse::<u64>(), end.parse::<u64>()) else {
                continue;
            };
            if last < first {
                continue;
            }
            if last.saturating_sub(first) >= MAX_NODE_EXPANSION as u64 {
                return Err(format!("node range exceeds expansion limit: {token}"));
            }
            consume_node_budget(remaining, (last - first + 1) as usize, token)?;
            for index in first..=last {
                nodes.insert(format!("{prefix}{index:0width$}", width = start.len()));
            }
        } else {
            consume_node_budget(remaining, 1, token)?;
            nodes.insert(format!("{prefix}{part}"));
        }
    }
    Ok(())
}

fn consume_node_budget(remaining: &mut usize, count: usize, token: &str) -> Result<(), String> {
    *remaining = remaining
        .checked_sub(count)
        .ok_or_else(|| format!("node list exceeds expansion limit: {token}"))?;
    Ok(())
}

pub fn job_std_io(
    out: &str,
    err: &str,
    id: &str,
    master: &str,
    task: &str,
    user: &str,
    name: &str,
) -> (String, String) {
    let out = expand_std_io_path(std_io_value(out), id, master, task, user, name);
    let err = expand_std_io_path(std_io_value(err), id, master, task, user, name);
    let err = if err.is_empty() { out.clone() } else { err };
    (out, err)
}

fn std_io_value(raw: &str) -> &str {
    match raw.trim() {
        "(null)" | "N/A" => "",
        value => value,
    }
}

fn numeric_only(raw: &str) -> &str {
    if !raw.is_empty() && raw.bytes().all(|b| b.is_ascii_digit()) {
        raw
    } else {
        ""
    }
}

pub fn expand_std_io_path(
    path: &str,
    id: &str,
    master: &str,
    task: &str,
    user: &str,
    name: &str,
) -> String {
    try_expand_std_io_path(path, id, master, task, user, name).unwrap_or_else(|_| path.into())
}

const MAX_STD_IO_PATH_BYTES: usize = 1024 * 1024;

pub fn try_expand_std_io_path(
    path: &str,
    id: &str,
    master: &str,
    task: &str,
    user: &str,
    name: &str,
) -> Result<String, String> {
    if path.len() > MAX_STD_IO_PATH_BYTES {
        return Err(format!("log path exceeds size limit: {path}"));
    }
    let bytes = path.as_bytes();
    let mut output = String::with_capacity(path.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] != b'%' {
            let next = path[i..].find('%').map_or(path.len(), |offset| i + offset);
            push_pattern(&mut output, &path[i..next], path)?;
            i = next;
            continue;
        }
        let mut spec = i + 1;
        while spec < bytes.len() && bytes[spec].is_ascii_digit() {
            spec += 1;
        }
        if spec == bytes.len() {
            push_pattern(&mut output, &path[i..], path)?;
            break;
        }
        if bytes[spec] == b'%' && spec == i + 1 {
            push_pattern(&mut output, "%", path)?;
            i += 2;
            continue;
        }
        let value = match bytes[spec] {
            b'j' => numeric_only(id),
            b'A' => numeric_only(master),
            b'a' => numeric_only(task),
            b'u' => user,
            b'x' => name,
            _ => "",
        };
        let width = if spec == i + 1 {
            0
        } else {
            path[i + 1..spec].parse::<usize>().unwrap_or(usize::MAX)
        };
        if value.is_empty() || width > 20 {
            let end = path[spec..]
                .chars()
                .next()
                .map_or(spec + 1, |c| spec + c.len_utf8());
            push_pattern(&mut output, &path[i..end], path)?;
            i = end;
            continue;
        }
        if value.len().max(width) > MAX_STD_IO_PATH_BYTES.saturating_sub(output.len()) {
            return Err(format!("log path expansion exceeds size limit: {path}"));
        }
        for _ in value.len()..width {
            output.push('0');
        }
        output.push_str(value);
        i = spec + 1;
    }
    Ok(output)
}

fn push_pattern(output: &mut String, piece: &str, path: &str) -> Result<(), String> {
    if piece.len() > MAX_STD_IO_PATH_BYTES.saturating_sub(output.len()) {
        return Err(format!("log path expansion exceeds size limit: {path}"));
    }
    output.push_str(piece);
    Ok(())
}
