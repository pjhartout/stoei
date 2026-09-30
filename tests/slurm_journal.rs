use std::{
    fs,
    sync::{Arc, Mutex},
};

use chrono::{DateTime, Local, TimeZone};
use stoei::slurm::*;

struct FixedClock(Mutex<DateTime<Local>>);

impl Clock for FixedClock {
    fn now(&self) -> DateTime<Local> {
        *self.0.lock().unwrap()
    }
}

fn clock() -> Arc<FixedClock> {
    Arc::new(FixedClock(Mutex::new(
        Local.with_ymd_and_hms(2026, 9, 30, 12, 0, 0).unwrap(),
    )))
}

#[test]
fn go_jsonl_remains_readable_and_terminal_states_are_sticky() {
    let temporary = tempfile::tempdir().unwrap();
    let path = temporary.path().join("jobs.jsonl");
    fs::write(&path, "malformed\n{\"ID\":\"123\",\"User\":\"alice\",\"State\":\"COMPLETED\",\"NCPUS\":\"4\",\"AllocTRES\":\"cpu=4\",\"FirstSeen\":\"2026-09-01T00:00:00Z\",\"LastSeen\":\"2026-09-01T00:00:00Z\"}\n").unwrap();
    let journal = Journal::new(path.clone(), clock());
    journal
        .upsert(vec![ControllerJob {
            id: "123".into(),
            state: "RUNNING".into(),
            std_out: "/logs/123".into(),
            ..Default::default()
        }])
        .unwrap();
    let rows = journal.all();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].state, "COMPLETED");
    assert_eq!(rows[0].ncpus, "4");
    assert_eq!(rows[0].std_out, "/logs/123");
    let value: serde_json::Value =
        serde_json::from_str(fs::read_to_string(&path).unwrap().trim()).unwrap();
    assert_eq!(value["ID"], "123");
    assert_eq!(value["FirstSeen"], "2026-09-01T00:00:00Z");
    assert_eq!(value["AllocTRES"], "cpu=4");
    assert!(value.get("job").is_none());
}

#[test]
fn pathless_sources_do_not_wipe_logs_and_old_unobserved_rows_expire() {
    let temporary = tempfile::tempdir().unwrap();
    let path = temporary.path().join("jobs.jsonl");
    fs::write(
        &path,
        "{\"ID\":\"old\",\"State\":\"COMPLETED\",\"LastSeen\":\"2026-01-01T00:00:00Z\"}\n",
    )
    .unwrap();
    let journal = Journal::new(path, clock());
    journal
        .upsert(vec![ControllerJob {
            id: "123".into(),
            state: "RUNNING".into(),
            std_out: "/log".into(),
            std_err: "/err".into(),
            ..Default::default()
        }])
        .unwrap();
    journal
        .upsert(vec![ControllerJob {
            id: "123".into(),
            state: "FAILED".into(),
            ..Default::default()
        }])
        .unwrap();
    let rows = journal.all();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].std_out, "/log");
    assert_eq!(rows[0].std_err, "/err");
    assert_eq!(rows[0].state, "FAILED");
}

#[test]
fn independent_journal_instances_do_not_lose_each_others_writes() {
    let temporary = tempfile::tempdir().unwrap();
    let path = temporary.path().join("jobs.jsonl");
    let clock = clock();
    let barrier = Arc::new(std::sync::Barrier::new(4));
    let handles: Vec<_> = (0..4)
        .map(|id| {
            let journal = Journal::new(path.clone(), clock.clone());
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                journal
                    .upsert(vec![ControllerJob {
                        id: id.to_string(),
                        state: "COMPLETED".into(),
                        ..Default::default()
                    }])
                    .unwrap();
            })
        })
        .collect();
    for handle in handles {
        handle.join().unwrap();
    }
    let journal = Journal::new(path, clock);
    assert_eq!(journal.all().len(), 4);
    journal.remove(&["1".into(), "2".into()]).unwrap();
    assert_eq!(
        journal
            .all()
            .iter()
            .map(|job| job.id.as_str())
            .collect::<Vec<_>>(),
        ["0", "3"]
    );
}

#[test]
fn oversized_journal_fails_without_overwriting_records() {
    let temporary = tempfile::tempdir().unwrap();
    let path = temporary.path().join("jobs.jsonl");
    let file = fs::File::create(&path).unwrap();
    let length = 128 * 1024 * 1024 + 1;
    file.set_len(length).unwrap();
    let journal = Journal::new(path.clone(), clock());
    assert!(journal.try_all().unwrap_err().contains("jobs.jsonl"));
    let error = journal
        .upsert(vec![ControllerJob {
            id: "1".into(),
            ..Default::default()
        }])
        .unwrap_err();
    assert!(error.contains("file size limit"));
    assert!(journal.remove(&["1".into()]).is_err());
    assert_eq!(fs::metadata(path).unwrap().len(), length);
}

#[test]
fn oversized_new_record_is_rejected_before_publication() {
    let temporary = tempfile::tempdir().unwrap();
    let path = temporary.path().join("jobs.jsonl");
    let journal = Journal::new(path.clone(), clock());
    journal
        .upsert(vec![ControllerJob {
            id: "123".into(),
            state: "COMPLETED".into(),
            ..Default::default()
        }])
        .unwrap();
    let original = fs::read(&path).unwrap();
    let error = journal
        .upsert(vec![ControllerJob {
            id: "456".into(),
            name: "x".repeat(4 * 1024 * 1024),
            ..Default::default()
        }])
        .unwrap_err();
    assert!(error.contains("size limit"));
    assert_eq!(fs::read(path).unwrap(), original);
}
