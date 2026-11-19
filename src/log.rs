use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use chrono::Local;

const CAPACITY: usize = 1000;
const MAX_MESSAGE: usize = 4096;

#[derive(Clone, Debug)]
pub struct LogEntry {
    pub timestamp: String,
    pub level: String,
    pub message: String,
}

#[derive(Clone, Default)]
pub struct LogRing(Arc<Mutex<LogEntries>>);

#[derive(Default)]
struct LogEntries {
    revision: u64,
    rows: VecDeque<LogEntry>,
}

impl LogRing {
    pub fn append(&self, level: &str, message: impl Into<String>) {
        self.append_at(
            Local::now().format("%H:%M:%S").to_string(),
            level,
            message.into(),
        );
    }

    fn append_at(&self, timestamp: String, level: &str, mut message: String) {
        if message.len() > MAX_MESSAGE {
            let mut end = MAX_MESSAGE;
            while !message.is_char_boundary(end) {
                end -= 1;
            }
            message.truncate(end);
            message.push('…');
        }
        let entry = LogEntry {
            timestamp,
            level: level.to_owned(),
            message,
        };
        let mut entries = self
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if entries.rows.len() == CAPACITY {
            entries.rows.pop_front();
        }
        entries.rows.push_back(entry);
        entries.revision = entries.revision.wrapping_add(1);
    }

    pub fn snapshot_since(&self, revision: u64) -> Option<(u64, Vec<LogEntry>)> {
        let entries = self
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        (entries.revision != revision)
            .then(|| (entries.revision, entries.rows.iter().cloned().collect()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshots_follow_new_entries_even_after_the_ring_fills() {
        let reader = LogRing::default();
        let writer = reader.clone();
        assert!(reader.snapshot_since(0).is_none());
        for i in 0..CAPACITY {
            writer.append_at("12:00:00".into(), "INFO", i.to_string());
        }
        let (revision, rows) = reader.snapshot_since(0).unwrap();
        assert_eq!(rows.len(), CAPACITY);
        assert_eq!(rows[0].message, "0");
        assert!(reader.snapshot_since(revision).is_none());
        writer.append_at("12:00:01".into(), "ERROR", "界".repeat(MAX_MESSAGE));
        let (next, rows) = reader.snapshot_since(revision).unwrap();
        assert_eq!(rows.len(), CAPACITY);
        assert_eq!(rows[0].message, "1");
        assert!(rows.last().unwrap().message.ends_with('…'));
        assert!(rows.last().unwrap().message.len() <= MAX_MESSAGE + '…'.len_utf8());
        assert!(reader.snapshot_since(next).is_none());
    }
}
