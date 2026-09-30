use std::{
    collections::BTreeMap,
    env,
    fs::{self, File, FileTimes, OpenOptions},
    io::{self, BufRead, BufReader, BufWriter, Read, Write},
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{Duration, Instant, SystemTime},
};

use chrono::{DateTime, SecondsFormat};
use serde::{Deserialize, Serialize};

use super::{Clock, ControllerJob, is_terminal_state};

pub const JOURNAL_RETENTION_DAYS: i64 = 90;
const MAX_JOURNAL_BYTES: u64 = 128 * 1024 * 1024;
const MAX_RECORD_BYTES: usize = 4 * 1024 * 1024;

pub fn journal_path() -> PathBuf {
    let base = env::var_os("XDG_DATA_HOME")
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .or_else(|| {
            env::var_os("HOME")
                .filter(|v| !v.is_empty())
                .map(|home| PathBuf::from(home).join(".local/share"))
        });
    base.map_or_else(PathBuf::new, |base| base.join("stoei/jobs.jsonl"))
}

pub fn acct_stamp_path(journal: &Path) -> PathBuf {
    journal
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("sacct-reconcile.stamp")
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default)]
struct JournalRecord {
    #[serde(flatten)]
    job: ControllerJob,
    #[serde(rename = "FirstSeen")]
    first_seen: String,
    #[serde(rename = "LastSeen")]
    last_seen: String,
}

pub struct Journal {
    path: PathBuf,
    clock: Arc<dyn Clock>,
    mutex: Mutex<()>,
}

impl Journal {
    pub fn new(path: PathBuf, clock: Arc<dyn Clock>) -> Self {
        Self {
            path,
            clock,
            mutex: Mutex::new(()),
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn all(&self) -> Vec<ControllerJob> {
        self.try_all().unwrap_or_default()
    }

    pub fn try_all(&self) -> Result<Vec<ControllerJob>, String> {
        let _guard = self.mutex.lock().unwrap_or_else(|e| e.into_inner());
        self.load()
            .map(|rows| rows.into_values().map(|record| record.job).collect())
            .map_err(|e| format!("job journal {}: {e}", self.path.display()))
    }

    pub fn upsert(&self, jobs: Vec<ControllerJob>) -> Result<(), String> {
        let _guard = self.mutex.lock().unwrap_or_else(|e| e.into_inner());
        let directory = self.path.parent().unwrap_or_else(|| Path::new("."));
        fs::create_dir_all(directory).map_err(|e| e.to_string())?;
        let _lock = FileLock::acquire(&self.path).map_err(|e| e.to_string())?;
        let mut records = self
            .load()
            .map_err(|e| format!("job journal {}: {e}", self.path.display()))?;
        let now = self.clock.now().to_utc();
        let timestamp = now.to_rfc3339_opts(SecondsFormat::Secs, true);
        for job in jobs {
            if job.id.is_empty() {
                continue;
            }
            upsert_record(&mut records, job, &timestamp);
        }
        let cutoff = now - chrono::Duration::days(JOURNAL_RETENTION_DAYS);
        records.retain(|_, record| {
            DateTime::parse_from_rfc3339(&record.last_seen).map_or(true, |seen| seen >= cutoff)
        });
        self.write(&records)
            .map_err(|e| format!("job journal {}: {e}", self.path.display()))
    }

    pub fn remove(&self, ids: &[String]) -> Result<(), String> {
        if ids.is_empty() {
            return Ok(());
        }
        let _guard = self.mutex.lock().unwrap_or_else(|e| e.into_inner());
        let _lock = FileLock::acquire(&self.path).map_err(|e| e.to_string())?;
        let mut records = self
            .load()
            .map_err(|e| format!("job journal {}: {e}", self.path.display()))?;
        for id in ids {
            records.remove(id);
        }
        self.write(&records)
            .map_err(|e| format!("job journal {}: {e}", self.path.display()))
    }

    pub fn touch_acct_stamp(&self) {
        let path = acct_stamp_path(&self.path);
        if let Some(directory) = path.parent() {
            let _ = fs::create_dir_all(directory);
        }
        if let Ok(file) = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(path)
        {
            let now: SystemTime = self.clock.now().into();
            let _ = file.set_times(FileTimes::new().set_modified(now));
        }
    }

    pub(crate) fn try_acct_lock(&self) -> Result<Option<FileLock>, String> {
        let stamp = acct_stamp_path(&self.path);
        if let Some(directory) = stamp.parent() {
            fs::create_dir_all(directory).map_err(|e| e.to_string())?;
        }
        FileLock::try_acquire(&stamp).map_err(|e| e.to_string())
    }

    fn load(&self) -> io::Result<BTreeMap<String, JournalRecord>> {
        let mut records = BTreeMap::new();
        let file = match File::open(&self.path) {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(records),
            Err(error) => return Err(error),
        };
        check_file_size(&file)?;
        let mut reader = BufReader::new((&file).take(MAX_JOURNAL_BYTES + 1));
        let mut line = Vec::new();
        while read_record_line(&mut reader, &mut line)? {
            if let Ok(record) = serde_json::from_slice::<JournalRecord>(&line)
                && !record.job.id.is_empty()
            {
                records.insert(record.job.id.clone(), record);
            }
        }
        check_file_size(&file)?;
        Ok(records)
    }

    fn write(&self, records: &BTreeMap<String, JournalRecord>) -> io::Result<()> {
        let directory = self.path.parent().unwrap_or_else(|| Path::new("."));
        let mut temporary = tempfile::Builder::new()
            .prefix("jobs-")
            .suffix(".tmp")
            .tempfile_in(directory)?;
        {
            let mut writer =
                LimitedWriter::new(BufWriter::new(temporary.as_file_mut()), MAX_JOURNAL_BYTES);
            for record in records.values() {
                let mut record_writer = LimitedWriter::new(&mut writer, MAX_RECORD_BYTES as u64);
                serde_json::to_writer(&mut record_writer, record)?;
                record_writer.write_all(b"\n")?;
            }
            writer.flush()?;
        }
        temporary.persist(&self.path).map_err(|e| e.error)?;
        Ok(())
    }
}

struct LimitedWriter<W> {
    inner: W,
    length: u64,
    limit: u64,
}

impl<W: Write> LimitedWriter<W> {
    fn new(inner: W, limit: u64) -> Self {
        Self {
            inner,
            length: 0,
            limit,
        }
    }
}

impl<W: Write> Write for LimitedWriter<W> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() as u64 > self.limit.saturating_sub(self.length) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "journal output exceeds size limit",
            ));
        }
        let written = self.inner.write(bytes)?;
        self.length += written as u64;
        Ok(written)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.inner.flush()
    }
}

fn check_file_size(file: &File) -> io::Result<()> {
    if file.metadata()?.len() > MAX_JOURNAL_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "journal exceeds file size limit",
        ));
    }
    Ok(())
}

fn upsert_record(
    records: &mut BTreeMap<String, JournalRecord>,
    mut job: ControllerJob,
    timestamp: &str,
) {
    if let Some(existing) = records.get_mut(&job.id) {
        if is_terminal_state(&existing.job.state) {
            existing.last_seen = timestamp.into();
            if existing.job.std_out.is_empty() {
                existing.job.std_out = job.std_out;
            }
            if existing.job.std_err.is_empty() {
                existing.job.std_err = job.std_err;
            }
            return;
        }
        if job.std_out.is_empty() {
            job.std_out = existing.job.std_out.clone();
        }
        if job.std_err.is_empty() {
            job.std_err = existing.job.std_err.clone();
        }
        existing.job = job;
        existing.last_seen = timestamp.into();
        return;
    }
    records.insert(
        job.id.clone(),
        JournalRecord {
            job,
            first_seen: timestamp.into(),
            last_seen: timestamp.into(),
        },
    );
}

fn read_record_line(reader: &mut impl BufRead, line: &mut Vec<u8>) -> io::Result<bool> {
    line.clear();
    loop {
        let buffer = reader.fill_buf()?;
        if buffer.is_empty() {
            return Ok(!line.is_empty());
        }
        let newline = buffer.iter().position(|b| *b == b'\n');
        let length = newline.map_or(buffer.len(), |end| end + 1);
        if line.len().saturating_add(length) > MAX_RECORD_BYTES {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "journal record exceeds line size limit",
            ));
        }
        line.extend_from_slice(&buffer[..length]);
        reader.consume(length);
        if newline.is_some() {
            return Ok(true);
        }
    }
}

pub(crate) struct FileLock {
    _file: File,
}

impl FileLock {
    fn try_acquire(path: &Path) -> io::Result<Option<Self>> {
        let file = open_lock_file(path)?;
        if !try_lock_file(&file)? {
            return Ok(None);
        }
        Ok(Some(Self { _file: file }))
    }

    fn acquire(path: &Path) -> io::Result<Self> {
        let file = open_lock_file(path)?;
        lock_file(&file)?;
        Ok(Self { _file: file })
    }
}

fn open_lock_file(path: &Path) -> io::Result<File> {
    let mut lock_path = path.as_os_str().to_os_string();
    lock_path.push(".lock");
    OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(lock_path)
}

fn try_lock_file(file: &File) -> io::Result<bool> {
    match file.try_lock() {
        Ok(()) => Ok(true),
        Err(fs::TryLockError::WouldBlock) => Ok(false),
        Err(fs::TryLockError::Error(error)) => Err(error),
    }
}

fn lock_file(file: &File) -> io::Result<()> {
    let start = Instant::now();
    loop {
        if try_lock_file(file)? {
            return Ok(());
        }
        if start.elapsed() >= Duration::from_secs(2) {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "job journal is locked by another process",
            ));
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}
