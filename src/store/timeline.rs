use chrono::{NaiveDate, NaiveDateTime};

use super::MergedJob;

pub fn parse_restarts(value: &str) -> u64 {
    let value = value.trim();
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        0
    } else {
        value.parse().unwrap_or(0)
    }
}

pub fn format_compact_time(value: &str, today: NaiveDate) -> String {
    let Ok(time) = NaiveDateTime::parse_from_str(value.trim(), "%Y-%m-%dT%H:%M:%S") else {
        return String::new();
    };
    time.format(if time.date() == today {
        "%H:%M"
    } else {
        "%m-%d %H:%M"
    })
    .to_string()
}

pub fn format_compact_timeline(
    submit: &str,
    start: &str,
    end: &str,
    state: &str,
    restarts: u64,
    today: NaiveDate,
) -> String {
    let submit = format_compact_time(submit, today);
    if submit.is_empty() {
        return "—".into();
    }
    let start = format_compact_time(start, today);
    let end = format_compact_time(end, today);
    let state = state.to_ascii_uppercase();
    let mut result = if matches!(state.as_str(), "PENDING" | "PD") {
        format!("{submit} ⏳")
    } else if matches!(state.as_str(), "RUNNING" | "R") {
        if start.is_empty() {
            format!("{submit} ⏳")
        } else {
            format!("{submit} → {start}")
        }
    } else if !end.is_empty() {
        if start.is_empty() {
            format!("{submit} → {end}")
        } else {
            format!("{submit} → {start} → {end}")
        }
    } else if !start.is_empty() {
        format!("{submit} → {start}")
    } else {
        submit
    };
    if restarts > 0 {
        result.push_str(&format!("  ↻ {restarts}"));
    }
    result
}

impl MergedJob {
    pub fn timeline(&self, today: NaiveDate) -> String {
        format_compact_timeline(
            &self.submit_time,
            &self.start_time,
            &self.end_time,
            &self.state,
            self.restarts,
            today,
        )
    }
}
