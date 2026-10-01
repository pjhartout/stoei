use std::collections::BTreeSet;

use super::checked_job_id;

const MAX_SELECTION_BYTES: usize = 64 * 1024;
const MAX_PENDING_TASKS: usize = 100_000;

pub(super) struct PendingSelection {
    pub query_id: String,
    ranges: Option<Vec<(u32, u32)>>,
}

impl PendingSelection {
    pub fn parse(id: &str) -> Result<Self, String> {
        if id.len() > MAX_SELECTION_BYTES {
            return Err("job selection exceeds size limit".into());
        }
        let query_id = checked_job_id(id)?
            .split('_')
            .map(|part| part.parse::<u32>().map(|number| number.to_string()))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|_| "invalid numeric job ID".to_owned())?
            .join("_");
        let ranges = id
            .split_once("_[")
            .map(|(_, spec)| parse_ranges(spec))
            .transpose()?;
        Ok(Self { query_id, ranges })
    }

    pub fn target(&self, raw: &str) -> Result<String, String> {
        let root = self.query_id.split('_').next().unwrap_or(&self.query_id);
        let mut tasks = BTreeSet::new();
        let mut direct = false;
        for (index, row) in raw
            .lines()
            .map(str::trim)
            .filter(|id| !id.is_empty())
            .enumerate()
        {
            if index >= MAX_PENDING_TASKS {
                return Err("pending job selection exceeds task limit".into());
            }
            let (id, number) = pending_ids(row)?;
            let Some((base, task)) = id.split_once('_') else {
                if id != self.query_id || number != id || self.ranges.is_some() {
                    return Err(format!("unexpected pending job ID: {id}"));
                }
                direct = true;
                continue;
            };
            if base != root && self.ranges.is_none() && number == self.query_id {
                direct = true;
                continue;
            }
            if base != root || (self.query_id.contains('_') && id != self.query_id) {
                return Err(format!("unexpected pending array task: {id}"));
            }
            let task = task
                .parse::<u32>()
                .map_err(|_| format!("invalid array task: {id}"))?;
            if self.ranges.as_ref().is_none_or(|ranges| {
                let index = ranges.partition_point(|(_, last)| *last < task);
                ranges.get(index).is_some_and(|(first, _)| *first <= task)
            }) {
                tasks.insert(task);
            }
        }
        if direct && tasks.is_empty() {
            return Ok(self.query_id.clone());
        }
        if direct {
            return Err("pending job selection mixes a numeric job and array tasks".into());
        }
        if tasks.is_empty() {
            return Err("No selected jobs or array tasks are still pending; their partition cannot be changed.".into());
        }
        array_target(root, tasks)
    }
}

fn pending_ids(row: &str) -> Result<(&str, &str), String> {
    let (id, number) = row.split_once('|').ok_or("invalid pending job record")?;
    if checked_job_id(id)? != id {
        return Err(format!("expected an individual pending job ID: {id}"));
    }
    if !number.bytes().all(|byte| byte.is_ascii_digit()) || number.parse::<u32>().is_err() {
        return Err(format!("invalid numeric pending job ID: {number}"));
    }
    Ok((id, number))
}

fn parse_ranges(spec: &str) -> Result<Vec<(u32, u32)>, String> {
    let invalid = || "invalid or incomplete array task selection".to_owned();
    let spec = spec.strip_suffix(']').ok_or_else(invalid)?;
    let spec = if let Some((spec, throttle)) = spec.split_once('%') {
        if !throttle.bytes().all(|byte| byte.is_ascii_digit()) {
            return Err(invalid());
        }
        throttle.parse::<u32>().map_err(|_| invalid())?;
        spec
    } else {
        spec
    };
    let mut ranges = spec
        .split(',')
        .map(|part| {
            let (first, last) = part.split_once('-').unwrap_or((part, part));
            if !first.bytes().all(|byte| byte.is_ascii_digit())
                || !last.bytes().all(|byte| byte.is_ascii_digit())
            {
                return Err(invalid());
            }
            let first = first.parse::<u32>().map_err(|_| invalid())?;
            let last = last.parse::<u32>().map_err(|_| invalid())?;
            if first > last {
                return Err(invalid());
            }
            Ok((first, last))
        })
        .collect::<Result<Vec<_>, _>>()?;
    ranges.sort_unstable();
    let mut merged: Vec<(u32, u32)> = Vec::with_capacity(ranges.len());
    for (first, last) in ranges {
        if let Some((_, end)) = merged.last_mut()
            && first <= end.saturating_add(1)
        {
            *end = (*end).max(last);
        } else {
            merged.push((first, last));
        }
    }
    Ok(merged)
}

fn array_target(root: &str, tasks: BTreeSet<u32>) -> Result<String, String> {
    debug_assert!(!tasks.is_empty());
    debug_assert!(tasks.len() <= MAX_PENDING_TASKS);
    let mut tasks = tasks.into_iter();
    let mut first = tasks.next().expect("nonempty pending task selection");
    let mut last = first;
    let mut spec = String::new();
    for task in tasks {
        if task.checked_sub(last) == Some(1) {
            last = task;
        } else {
            append_range(&mut spec, first, last)?;
            first = task;
            last = task;
        }
    }
    append_range(&mut spec, first, last)?;
    Ok(format!("{root}_[{spec}]"))
}

fn append_range(spec: &mut String, first: u32, last: u32) -> Result<(), String> {
    debug_assert!(first <= last);
    debug_assert!(spec.len() <= MAX_SELECTION_BYTES);
    if !spec.is_empty() {
        spec.push(',');
    }
    spec.push_str(&if first == last {
        first.to_string()
    } else {
        format!("{first}-{last}")
    });
    if spec.len() > MAX_SELECTION_BYTES {
        return Err("pending job selection exceeds size limit".into());
    }
    Ok(())
}
