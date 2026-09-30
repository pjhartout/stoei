use std::{collections::BTreeMap, time::Duration};

use chrono::{DateTime, Utc};

use super::*;

pub const ALL_USERS_FORMAT: &str = "JobID:30,Name:50,UserName:15,Partition:15,StateCompact:10,TimeUsed:12,NumNodes:6,NodeList:80,Reason:40,tres:80";
pub const JOURNAL_SQUEUE_FORMAT: &str = "JobId:30,ArrayJobId:20,ArrayTaskId:20,UserName:15,Name:50,State:20,Partition:15,SubmitTime:25,StartTime:25,EndTime:25,TimeUsed:15,exit_code:10,RestartCnt:10,NumCPUs:10,NodeList:80,tres-alloc:200,StdErr:256,StdOut:256";
pub const ACCT_FORMAT: &str = "JobID,User,State,Partition,Submit,Start,End,Elapsed,ExitCode,NodeList,AllocCPUS,AllocTRES,StdErr,StdOut,JobName";
pub const PRIORITY_FORMAT: &str = "%i|%u|%o|%r|%n|%Y|%A|%F|%J|%P|%Q|%T|%B|%S|%N";

pub fn field<'a>(fields: &'a BTreeMap<String, String>, key: &str) -> &'a str {
    fields.get(key).map_or("", String::as_str)
}

pub fn base_state(state: &str) -> &str {
    state.split_whitespace().next().unwrap_or("")
}

pub fn parse_scontrol_fields(raw: &str) -> BTreeMap<String, String> {
    raw.split_whitespace()
        .filter_map(|token| {
            let (key, value) = token.split_once('=')?;
            let key = key.rsplit(':').next()?;
            if key.is_empty()
                || !key
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'/')
            {
                return None;
            }
            Some((key.into(), value.into()))
        })
        .collect()
}

pub fn parse_scontrol_job_records(raw: &str) -> Vec<BTreeMap<String, String>> {
    let mut records = Vec::new();
    let mut current = String::new();
    for line in raw.lines() {
        if line.trim_start().starts_with("JobId=") && !current.is_empty() {
            records.push(parse_scontrol_fields(&current));
            current.clear();
        }
        if !current.is_empty() || line.trim_start().starts_with("JobId=") {
            current.push_str(line);
            current.push('\n');
        }
    }
    if !current.is_empty() {
        records.push(parse_scontrol_fields(&current));
    }
    records
}

pub fn parse_node_fields(raw: &str) -> BTreeMap<String, String> {
    let mut fields = BTreeMap::new();
    for line in raw.lines() {
        let line = line.trim();
        let mut heads = Vec::new();
        let mut start = 0;
        for token in line.split_whitespace() {
            let position = line[start..].find(token).map_or(start, |p| start + p);
            if let Some((key, _)) = token.split_once('=')
                && !key.is_empty()
                && key
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'/' || b == b':')
            {
                heads.push((position, position + key.len() + 1, key));
            }
            start = position + token.len();
        }
        for (i, (_, value_start, key)) in heads.iter().enumerate() {
            let end = heads.get(i + 1).map_or(line.len(), |h| h.0);
            fields.insert((*key).into(), line[*value_start..end].trim().into());
        }
    }
    fields
}

pub fn parse_nodes(raw: &str) -> Vec<Node> {
    let mut nodes = Vec::new();
    let mut current = String::new();
    for line in raw.lines() {
        if line.trim_start().starts_with("NodeName=") && !current.is_empty() {
            nodes.push(node_from_fields(parse_node_fields(&current)));
            current.clear();
        }
        if !current.is_empty() || line.trim_start().starts_with("NodeName=") {
            current.push_str(line);
            current.push('\n');
        }
    }
    if !current.is_empty() {
        nodes.push(node_from_fields(parse_node_fields(&current)));
    }
    nodes
}

pub fn node_from_fields(fields: BTreeMap<String, String>) -> Node {
    Node {
        name: field(&fields, "NodeName").into(),
        state: field(&fields, "State").into(),
        cpu_tot: field(&fields, "CPUTot").into(),
        cpu_alloc: field(&fields, "CPUAlloc").into(),
        real_mem: field(&fields, "RealMemory").into(),
        alloc_mem: field(&fields, "AllocMem").into(),
        cfg_tres: field(&fields, "CfgTRES").into(),
        alloc_tres: field(&fields, "AllocTRES").into(),
        gres: field(&fields, "Gres").into(),
        reason: field(&fields, "Reason").into(),
        fields,
    }
}

pub fn parse_running_jobs(raw: &str) -> Vec<RunningJob> {
    raw.trim()
        .lines()
        .skip(1)
        .filter_map(|line| {
            let parts: Vec<_> = line.split('|').map(str::trim).collect();
            if parts.len() < 8 {
                return None;
            }
            let tail = &parts[parts.len() - 6..];
            Some(RunningJob {
                id: parts[0].into(),
                name: parts[1..parts.len() - 6].join("|"),
                state: tail[0].into(),
                time: tail[1].into(),
                nodes: tail[2].into(),
                node_list: tail[3].into(),
                submit_time: tail[4].into(),
                start_time: tail[5].into(),
            })
        })
        .collect()
}

fn fixed_fields<'a>(line: &'a str, ends: &[usize]) -> Vec<&'a str> {
    let mut fields = Vec::with_capacity(ends.len() + 1);
    let mut start = 0;
    for end in ends
        .iter()
        .copied()
        .chain(std::iter::once(line.len().max(*ends.last().unwrap_or(&0))))
    {
        let end = end.min(line.len());
        // Slurm column widths are byte offsets; lossy empty fields avoid slicing UTF-8 mid-codepoint.
        fields.push(line.get(start..end).unwrap_or("").trim());
        start = end;
    }
    fields
}

pub fn parse_all_users_jobs(raw: &str) -> Vec<AllUsersJob> {
    raw.lines()
        .filter(|line| line.len() >= 30)
        .filter_map(|line| {
            let f = fixed_fields(line, &[30, 80, 95, 110, 120, 132, 138, 218, 258]);
            if f[0].is_empty() {
                return None;
            }
            Some(AllUsersJob {
                id: f[0].into(),
                name: f[1].into(),
                user: f[2].into(),
                partition: f[3].into(),
                state: f[4].into(),
                time: f[5].into(),
                num_nodes: f[6].into(),
                node_list: f[7].into(),
                reason: f[8].into(),
                tres: f[9].into(),
            })
        })
        .collect()
}

pub fn journal_job_id(id: &str, master: &str, task: &str) -> String {
    if !master.is_empty() && task.parse::<u64>().is_ok() {
        format!("{master}_{task}")
    } else {
        id.into()
    }
}

pub fn parse_journal_jobs(raw: &str) -> Vec<ControllerJob> {
    raw.lines()
        .filter_map(|line| {
            let f = fixed_fields(
                line,
                &[
                    30, 50, 70, 85, 135, 155, 170, 195, 220, 245, 260, 270, 280, 290, 370, 570, 826,
                ],
            );
            if f[0].is_empty() {
                return None;
            }
            let (std_out, std_err) = job_std_io(f[17], f[16], f[0], f[1], f[2], f[3], f[4]);
            Some(ControllerJob {
                id: journal_job_id(f[0], f[1], f[2]),
                user: f[3].into(),
                name: f[4].into(),
                state: base_state(f[5]).into(),
                partition: f[6].into(),
                submit: f[7].into(),
                start: f[8].into(),
                end: f[9].into(),
                elapsed: f[10].into(),
                exit_code: f[11].into(),
                restart: f[12].into(),
                ncpus: f[13].into(),
                node_list: f[14].into(),
                alloc_tres: f[15].into(),
                std_out,
                std_err,
            })
        })
        .collect()
}

fn normalize_acct_id(id: &str) -> String {
    let Some((master, spec)) = id.split_once("_[") else {
        return id.into();
    };
    let Some(spec) = spec.strip_suffix(']') else {
        return id.into();
    };
    let task = match spec.split_once('%') {
        Some((task, throttle)) if throttle.parse::<u64>().is_ok() => task,
        Some(_) => return id.into(),
        None => spec,
    };
    if master.parse::<u64>().is_ok() && task.parse::<u64>().is_ok() {
        format!("{master}_{task}")
    } else {
        id.into()
    }
}

pub fn parse_acct_jobs(raw: &str) -> Vec<ControllerJob> {
    raw.lines()
        .filter_map(|line| {
            let f: Vec<_> = line.splitn(15, '|').collect();
            if f.len() != 15 || f[0].is_empty() {
                return None;
            }
            let id = normalize_acct_id(f[0].trim());
            let (master, task) = id.split_once('_').unwrap_or(("", ""));
            let (std_out, std_err) = job_std_io(f[13], f[12], &id, master, task, f[1], f[14]);
            Some(ControllerJob {
                id,
                user: f[1].into(),
                state: base_state(f[2]).into(),
                partition: f[3].into(),
                submit: f[4].into(),
                start: f[5].into(),
                end: f[6].into(),
                elapsed: f[7].into(),
                exit_code: f[8].into(),
                node_list: f[9].into(),
                ncpus: f[10].into(),
                alloc_tres: f[11].into(),
                std_err,
                std_out,
                name: f[14].into(),
                restart: String::new(),
            })
        })
        .collect()
}

pub fn controller_job_from_fields(f: &BTreeMap<String, String>) -> ControllerJob {
    let user = field(f, "UserId").split('(').next().unwrap_or("");
    let (std_out, std_err) = job_std_io(
        field(f, "StdOut"),
        field(f, "StdErr"),
        field(f, "JobId"),
        field(f, "ArrayJobId"),
        field(f, "ArrayTaskId"),
        user,
        field(f, "JobName"),
    );
    ControllerJob {
        id: journal_job_id(
            field(f, "JobId"),
            field(f, "ArrayJobId"),
            field(f, "ArrayTaskId"),
        ),
        user: user.into(),
        name: field(f, "JobName").into(),
        state: base_state(field(f, "JobState")).into(),
        partition: field(f, "Partition").into(),
        submit: field(f, "SubmitTime").into(),
        start: field(f, "StartTime").into(),
        end: field(f, "EndTime").into(),
        elapsed: field(f, "RunTime").into(),
        exit_code: field(f, "ExitCode").into(),
        restart: field(f, "Restarts").into(),
        node_list: field(f, "NodeList").into(),
        ncpus: field(f, "NumCPUs").into(),
        alloc_tres: field(f, "TRES").into(),
        std_out,
        std_err,
    }
}

pub fn history_jobs_for(
    jobs: Vec<ControllerJob>,
    user: &str,
    cutoff: Option<DateTime<Utc>>,
) -> (Vec<HistoryJob>, HistoryStats) {
    let mut stats = HistoryStats::default();
    let mut rows = Vec::new();
    for job in jobs {
        if !user.is_empty() && job.user != user {
            continue;
        }
        let latest = [&job.end, &job.start, &job.submit]
            .into_iter()
            .find_map(|v| parse_slurm_timestamp(v));
        if latest
            .zip(cutoff)
            .is_some_and(|(time, cutoff)| time < cutoff)
        {
            continue;
        }
        let requeues = job.restart.parse::<u64>().unwrap_or(0);
        stats.total_requeues = stats.total_requeues.saturating_add(requeues);
        stats.max_requeues = stats.max_requeues.max(requeues);
        rows.push(HistoryJob::from(job));
    }
    rows.sort_by(|a, b| b.submit.cmp(&a.submit));
    stats.total_jobs = rows.len();
    (rows, stats)
}

pub fn parse_fair_share(raw: &str) -> Vec<FairShareEntry> {
    raw.lines()
        .filter_map(|line| {
            let f: Vec<_> = line.split('|').map(str::trim).collect();
            if f.len() < 8 {
                return None;
            }
            Some(FairShareEntry {
                account: f[0].into(),
                user: f[1].into(),
                raw_shares: f[2].into(),
                norm_shares: f[3].into(),
                raw_usage: f[4].into(),
                norm_usage: f[5].into(),
                effectv_usage: f[6].into(),
                fair_share: f[7].into(),
            })
        })
        .collect()
}

fn integer(raw: &str) -> i64 {
    raw.trim().parse::<i64>().unwrap_or_else(|_| {
        let value = raw.trim().parse::<f64>().unwrap_or(0.0);
        if value.is_finite() {
            value.round() as i64
        } else {
            0
        }
    })
}

fn sum_tres_weights(raw: &str) -> i64 {
    raw.split(',')
        .filter_map(|part| part.split_once('='))
        .fold(0_i64, |sum, (_, value)| sum.saturating_add(integer(value)))
}

pub fn parse_priority(raw: &str) -> Vec<PriorityEntry> {
    let mut entries: Vec<_> = raw
        .lines()
        .filter_map(|line| {
            let f: Vec<_> = line.split('|').map(str::trim).collect();
            if f.len() < 15 {
                return None;
            }
            Some(PriorityEntry {
                job_id: f[0].into(),
                user: f[1].into(),
                account: f[2].into(),
                partition: f[3].into(),
                qos: f[4].into(),
                priority: integer(f[5]),
                factors: PriorityFactors {
                    age: integer(f[6]),
                    fair_share: integer(f[7]),
                    job_size: integer(f[8]),
                    partition: integer(f[9]),
                    qos: integer(f[10]),
                    tres: sum_tres_weights(f[11]),
                    assoc: integer(f[12]),
                    site: integer(f[13]),
                    nice: integer(f[14]),
                },
            })
        })
        .collect();
    entries.sort_by_key(|entry| std::cmp::Reverse(entry.priority));
    entries
}

pub fn parse_priority_config(raw: &str) -> PriorityConfig {
    let fields: BTreeMap<String, String> = raw
        .lines()
        .filter_map(|line| line.split_once('='))
        .map(|(key, value)| {
            (
                key.trim().into(),
                if value.trim() == "(null)" {
                    String::new()
                } else {
                    value.trim().into()
                },
            )
        })
        .collect();
    PriorityConfig {
        priority_type: field(&fields, "PriorityType").into(),
        weights: PriorityWeights {
            age: integer(field(&fields, "PriorityWeightAge")),
            assoc: integer(field(&fields, "PriorityWeightAssoc")),
            fair_share: integer(field(&fields, "PriorityWeightFairShare")),
            job_size: integer(field(&fields, "PriorityWeightJobSize")),
            partition: integer(field(&fields, "PriorityWeightPartition")),
            qos: integer(field(&fields, "PriorityWeightQOS")),
            tres: field(&fields, "PriorityWeightTRES").into(),
        },
        max_age: Duration::try_from_secs_f64(parse_elapsed_to_seconds(field(
            &fields,
            "PriorityMaxAge",
        )))
        .unwrap_or_default(),
        decay_half_life: Duration::try_from_secs_f64(parse_elapsed_to_seconds(field(
            &fields,
            "PriorityDecayHalfLife",
        )))
        .unwrap_or_default(),
        favor_small: field(&fields, "PriorityFavorSmall").eq_ignore_ascii_case("yes"),
    }
}
