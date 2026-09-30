use chrono::{DateTime, Local, NaiveDateTime, Utc};

pub trait Clock: Send + Sync {
    fn now(&self) -> DateTime<Local>;
}

#[derive(Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> DateTime<Local> {
        Local::now()
    }
}

pub fn parse_elapsed_to_seconds(raw: &str) -> f64 {
    let raw = raw.trim();
    let (days, raw) = match raw.split_once('-') {
        Some((days, rest)) => match days.parse::<u64>() {
            Ok(days) => (days as f64, if rest.is_empty() { "0" } else { rest }),
            Err(_) => return 0.0,
        },
        None => (0.0, raw),
    };
    let values: Vec<_> = raw.split(':').take(4).collect();
    if values.len() > 3 {
        return 0.0;
    }
    let mut seconds = days * 86400.0;
    for (i, value) in values.iter().enumerate() {
        let number = if i + 1 == values.len() {
            value.parse::<f64>().ok()
        } else {
            value.parse::<u64>().ok().map(|n| n as f64)
        };
        let Some(number) = number else { return 0.0 };
        if !number.is_finite() || number < 0.0 {
            return 0.0;
        }
        seconds += number * 60_f64.powi((values.len() - i - 1) as i32);
    }
    if seconds.is_finite() { seconds } else { 0.0 }
}

pub fn parse_slurm_timestamp(raw: &str) -> Option<DateTime<Utc>> {
    NaiveDateTime::parse_from_str(raw.trim(), "%Y-%m-%dT%H:%M:%S")
        .ok()
        .map(|t| t.and_utc())
}

pub fn wait_time_seconds(submit: &str, start: &str) -> Option<f64> {
    let duration = parse_slurm_timestamp(start)? - parse_slurm_timestamp(submit)?;
    let seconds = duration.num_seconds();
    (seconds >= 0).then_some(seconds as f64)
}

pub fn is_terminal_state(state: &str) -> bool {
    matches!(
        state.split_whitespace().next().unwrap_or(""),
        "COMPLETED"
            | "FAILED"
            | "CANCELLED"
            | "TIMEOUT"
            | "OUT_OF_MEMORY"
            | "NODE_FAIL"
            | "BOOT_FAIL"
            | "DEADLINE"
            | "PREEMPTED"
            | "REVOKED"
            | "SPECIAL_EXIT"
    )
}
