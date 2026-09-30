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
pub struct LogRing(Arc<Mutex<VecDeque<LogEntry>>>);

impl LogRing {
    pub fn append(&self, level: &str, message: impl Into<String>) {
        let mut message = message.into();
        if message.len() > MAX_MESSAGE {
            let mut end = MAX_MESSAGE;
            while !message.is_char_boundary(end) {
                end -= 1;
            }
            message.truncate(end);
            message.push('…');
        }
        let entry = LogEntry {
            timestamp: Local::now().format("%H:%M:%S").to_string(),
            level: level.to_owned(),
            message,
        };
        let mut entries = self
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if entries.len() == CAPACITY {
            entries.pop_front();
        }
        entries.push_back(entry);
        debug_assert!(entries.len() <= CAPACITY);
    }

    pub fn snapshot(&self) -> Vec<LogEntry> {
        self.0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .iter()
            .cloned()
            .collect()
    }
}
