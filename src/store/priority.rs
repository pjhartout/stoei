use std::collections::BTreeMap;
use std::time::Duration;

use super::{FairShareEntry, PriorityEntry, PriorityFactors};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum UsageBand {
    #[default]
    Unknown,
    Unused,
    Under,
    Over,
    Heavy,
}

impl UsageBand {
    pub fn label(self) -> &'static str {
        match self {
            Self::Unknown => "",
            Self::Unused => "Unused",
            Self::Under => "Under-served",
            Self::Over => "Over-served",
            Self::Heavy => "Heavily over-served",
        }
    }

    pub fn role(self) -> &'static str {
        match self {
            Self::Unknown => "",
            Self::Unused => "muted",
            Self::Under => "success",
            Self::Over => "warning",
            Self::Heavy => "error",
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct RankedShare {
    pub entry: FairShareEntry,
    pub rank: usize,
    pub total: usize,
    pub ratio: f64,
    pub ratio_ok: bool,
    pub band: UsageBand,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct QueuePosition {
    pub cluster: usize,
    pub cluster_total: usize,
    pub partition: usize,
    pub partition_total: usize,
}

#[derive(Clone, Debug, Default)]
pub struct RankedPriority {
    pub entry: PriorityEntry,
    pub pos: QueuePosition,
}

#[derive(Clone, Debug, Default)]
pub struct PartitionStanding {
    pub partition: String,
    pub best: QueuePosition,
    pub jobs: usize,
}

fn finite_number(value: &str) -> Option<f64> {
    value
        .trim()
        .parse::<f64>()
        .ok()
        .filter(|value| value.is_finite())
}

pub fn usage_ratio(entry: &FairShareEntry) -> Option<f64> {
    let share = finite_number(&entry.norm_shares)?;
    let usage = finite_number(&entry.effectv_usage)?;
    if share <= 0.0 || usage < 0.0 {
        return None;
    }
    let ratio = usage / share;
    ratio.is_finite().then_some(ratio)
}

pub fn classify_usage(ratio: f64, valid: bool) -> UsageBand {
    if !valid || !ratio.is_finite() || ratio < 0.0 {
        return UsageBand::Unknown;
    }
    if ratio == 0.0 {
        UsageBand::Unused
    } else if ratio <= 1.0 {
        UsageBand::Under
    } else if ratio <= 2.0 {
        UsageBand::Over
    } else {
        UsageBand::Heavy
    }
}

pub fn fair_share_value(entry: &FairShareEntry) -> f64 {
    finite_number(&entry.fair_share).unwrap_or(0.0)
}

pub fn rank_active_users(entries: &[FairShareEntry]) -> Vec<RankedShare> {
    let mut best: BTreeMap<&str, &FairShareEntry> = BTreeMap::new();
    for entry in entries.iter().filter(|entry| !entry.is_account()) {
        if !usage_ratio(entry).is_some_and(|ratio| ratio > 0.0) {
            continue;
        }
        if best
            .get(entry.user.as_str())
            .is_none_or(|previous| fair_share_value(entry) > fair_share_value(previous))
        {
            best.insert(&entry.user, entry);
        }
    }
    let mut users: Vec<_> = best.into_values().cloned().collect();
    users.sort_by(|a, b| {
        fair_share_value(b)
            .total_cmp(&fair_share_value(a))
            .then_with(|| a.user.cmp(&b.user))
    });
    rank_shares(users, fair_share_value)
}

pub fn rank_accounts(entries: &[FairShareEntry]) -> Vec<RankedShare> {
    let mut accounts: Vec<_> = entries
        .iter()
        .filter(|entry| {
            entry.is_account()
                && entry.account != "root"
                && usage_ratio(entry).is_some_and(|ratio| ratio > 0.0)
        })
        .cloned()
        .collect();
    let key = |entry: &FairShareEntry| usage_ratio(entry).unwrap_or(0.0);
    accounts.sort_by(|a, b| {
        key(a)
            .total_cmp(&key(b))
            .then_with(|| a.account.cmp(&b.account))
    });
    rank_shares(accounts, key)
}

fn rank_shares(
    entries: Vec<FairShareEntry>,
    key: impl Fn(&FairShareEntry) -> f64,
) -> Vec<RankedShare> {
    let total = entries.len();
    let mut rank = 0;
    let mut previous = None;
    entries
        .into_iter()
        .map(|entry| {
            let value = key(&entry);
            if previous != Some(value) {
                rank += 1;
            }
            previous = Some(value);
            let ratio = usage_ratio(&entry);
            let band = classify_usage(ratio.unwrap_or(0.0), ratio.is_some());
            RankedShare {
                entry,
                rank,
                total,
                ratio: ratio.unwrap_or(0.0),
                ratio_ok: ratio.is_some(),
                band,
            }
        })
        .collect()
}

pub fn user_associations(entries: &[FairShareEntry], username: &str) -> Vec<FairShareEntry> {
    entries
        .iter()
        .filter(|entry| entry.user == username)
        .cloned()
        .collect()
}

pub fn account_count(entries: &[FairShareEntry]) -> usize {
    entries
        .iter()
        .filter(|entry| entry.is_account() && entry.account != "root")
        .count()
}

pub fn find_ranked_user<'a>(ranked: &'a [RankedShare], username: &str) -> Option<&'a RankedShare> {
    ranked.iter().find(|row| row.entry.user == username)
}

pub fn find_ranked_account<'a>(
    ranked: &'a [RankedShare],
    account: &str,
) -> Option<&'a RankedShare> {
    ranked.iter().find(|row| row.entry.account == account)
}

pub fn recovery_time(ratio: f64, half_life: Duration) -> Option<Duration> {
    if !ratio.is_finite() || ratio <= 1.0 || half_life.is_zero() {
        return None;
    }
    Duration::try_from_secs_f64(ratio.log2() * half_life.as_secs_f64()).ok()
}

pub fn rank_pending(entries: &[PriorityEntry]) -> Vec<RankedPriority> {
    let mut sorted = entries.to_vec();
    sorted.sort_by(|a, b| {
        b.priority
            .cmp(&a.priority)
            .then_with(|| job_id_cmp(&a.job_id, &b.job_id))
    });
    let mut cluster_positions = BTreeMap::new();
    let mut partition_totals: BTreeMap<&str, usize> = BTreeMap::new();
    for entry in &sorted {
        let next = cluster_positions.len() + 1;
        cluster_positions
            .entry(entry.job_id.as_str())
            .or_insert(next);
        *partition_totals.entry(&entry.partition).or_default() += 1;
    }
    let mut partition_seen: BTreeMap<&str, usize> = BTreeMap::new();
    sorted
        .iter()
        .map(|entry| {
            let position = partition_seen.entry(&entry.partition).or_default();
            *position += 1;
            RankedPriority {
                entry: entry.clone(),
                pos: QueuePosition {
                    cluster: cluster_positions[entry.job_id.as_str()],
                    cluster_total: cluster_positions.len(),
                    partition: *position,
                    partition_total: partition_totals[entry.partition.as_str()],
                },
            }
        })
        .collect()
}

pub fn user_pending(ranked: &[RankedPriority], username: &str) -> Vec<RankedPriority> {
    ranked
        .iter()
        .filter(|row| row.entry.user == username)
        .cloned()
        .collect()
}

pub fn by_partition(ranked: &[RankedPriority]) -> Vec<RankedPriority> {
    let mut rows = ranked.to_vec();
    rows.sort_by(|a, b| {
        a.entry
            .partition
            .cmp(&b.entry.partition)
            .then_with(|| a.pos.partition.cmp(&b.pos.partition))
    });
    rows
}

pub fn partition_standings(rows: &[RankedPriority]) -> Vec<PartitionStanding> {
    let mut groups: BTreeMap<String, PartitionStanding> = BTreeMap::new();
    for row in rows {
        let standing = groups
            .entry(row.entry.partition.clone())
            .or_insert_with(|| PartitionStanding {
                partition: row.entry.partition.clone(),
                best: row.pos,
                jobs: 0,
            });
        standing.jobs += 1;
        if row.pos.partition < standing.best.partition {
            standing.best = row.pos;
        }
    }
    let mut result: Vec<_> = groups.into_values().collect();
    result.sort_by_key(|standing| standing.best.cluster);
    result
}

pub fn sum_factors(rows: &[RankedPriority]) -> (PriorityFactors, i64) {
    let mut factors = PriorityFactors::default();
    let mut total: i64 = 0;
    for row in rows {
        factors.add(&row.entry.factors);
        total = total.saturating_add(row.entry.priority);
    }
    (factors, total)
}

fn job_id_cmp(a: &str, b: &str) -> std::cmp::Ordering {
    let leading = |id: &str| -> u64 {
        let end = id.bytes().take_while(u8::is_ascii_digit).count();
        id[..end].parse().unwrap_or(0)
    };
    leading(a).cmp(&leading(b)).then_with(|| a.cmp(b))
}
