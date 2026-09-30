use std::{
    fmt,
    fs::File,
    io::{Read, Seek, SeekFrom},
    process::{Child, Command, ExitStatus, Stdio},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, Instant},
};

use std::os::unix::process::CommandExt;

pub trait Runner: Send + Sync {
    fn run(&self, name: &str, args: &[String], timeout: Duration) -> Result<String, CommandError>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CommandErrorCause {
    TimedOut,
    Cancelled,
    Exit(Option<i32>),
    Io(String),
    OutputLimit,
    HardFailure,
}

impl fmt::Display for CommandErrorCause {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TimedOut => f.write_str("command timed out"),
            Self::Cancelled => f.write_str("command cancelled"),
            Self::Exit(Some(code)) => write!(f, "exit status {code}"),
            Self::Exit(None) => f.write_str("process terminated by a signal"),
            Self::Io(error) => f.write_str(error),
            Self::OutputLimit => f.write_str("command output exceeds capture limit"),
            Self::HardFailure => Ok(()),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CommandError {
    pub name: String,
    pub stderr: String,
    pub cause: CommandErrorCause,
}

impl CommandError {
    pub fn new(name: &str, cause: CommandErrorCause, stderr: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            cause,
            stderr: stderr.into(),
        }
    }
}

impl fmt::Display for CommandError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: ", self.name)?;
        if self.cause != CommandErrorCause::HardFailure {
            write!(f, "{}", self.cause)?;
            if !self.stderr.is_empty() {
                f.write_str(": ")?;
            }
        }
        f.write_str(&self.stderr)
    }
}

impl std::error::Error for CommandError {}

pub struct ExecRunner {
    pub stop: Arc<AtomicBool>,
}

impl Default for ExecRunner {
    fn default() -> Self {
        Self::new(Arc::new(AtomicBool::new(false)))
    }
}

const STDOUT_LIMIT: u64 = 16 * 1024 * 1024;
const STDERR_LIMIT: u64 = 1024 * 1024;
const POLL_INTERVAL: Duration = Duration::from_millis(20);
const REAP_GRACE: Duration = Duration::from_secs(2);

impl ExecRunner {
    pub fn new(stop: Arc<AtomicBool>) -> Self {
        Self { stop }
    }

    fn execute(
        &self,
        name: &str,
        args: &[String],
        timeout: Duration,
    ) -> Result<String, CommandError> {
        if self.stop.load(Ordering::Relaxed) {
            return Err(CommandError::new(name, CommandErrorCause::Cancelled, ""));
        }
        if timeout.is_zero() {
            return Err(CommandError::new(name, CommandErrorCause::TimedOut, ""));
        }
        let io_error = |error: std::io::Error| {
            CommandError::new(name, CommandErrorCause::Io(error.to_string()), "")
        };
        let mut stdout = tempfile::tempfile().map_err(io_error)?;
        let mut stderr = tempfile::tempfile().map_err(io_error)?;
        let mut command = Command::new(name);
        command
            .args(args)
            .stdin(Stdio::null())
            .stdout(stdout.try_clone().map_err(io_error)?)
            .stderr(stderr.try_clone().map_err(io_error)?);
        command.process_group(0);
        let mut child = command.spawn().map_err(io_error)?;
        let outcome = self.wait(&mut child, &stdout, &stderr, timeout);
        if outcome.is_err() {
            terminate_and_reap(&mut child);
        }
        let error_text = read_bounded(&mut stderr, STDERR_LIMIT)
            .unwrap_or_default()
            .trim_end()
            .to_owned();
        let status = outcome.map_err(|cause| CommandError::new(name, cause, &error_text))?;
        if !status.success() {
            return Err(CommandError::new(
                name,
                CommandErrorCause::Exit(status.code()),
                error_text,
            ));
        }
        if error_text
            .to_ascii_lowercase()
            .contains("connection refused")
        {
            return Err(CommandError::new(
                name,
                CommandErrorCause::HardFailure,
                error_text,
            ));
        }
        read_bounded(&mut stdout, STDOUT_LIMIT)
            .map_err(|cause| CommandError::new(name, cause, error_text))
    }

    fn wait(
        &self,
        child: &mut Child,
        stdout: &File,
        stderr: &File,
        timeout: Duration,
    ) -> Result<ExitStatus, CommandErrorCause> {
        let start = Instant::now();
        loop {
            if self.stop.load(Ordering::Relaxed) {
                return Err(CommandErrorCause::Cancelled);
            }
            if start.elapsed() >= timeout {
                return Err(CommandErrorCause::TimedOut);
            }
            if stdout.metadata().map_err(io_cause)?.len() > STDOUT_LIMIT
                || stderr.metadata().map_err(io_cause)?.len() > STDERR_LIMIT
            {
                return Err(CommandErrorCause::OutputLimit);
            }
            if let Some(status) = child.try_wait().map_err(io_cause)? {
                return Ok(status);
            }
            thread::sleep(POLL_INTERVAL.min(timeout.saturating_sub(start.elapsed())));
        }
    }
}

impl Runner for ExecRunner {
    fn run(&self, name: &str, args: &[String], timeout: Duration) -> Result<String, CommandError> {
        self.execute(name, args, timeout)
    }
}

fn io_cause(error: std::io::Error) -> CommandErrorCause {
    CommandErrorCause::Io(error.to_string())
}

fn terminate_and_reap(child: &mut Child) {
    {
        // Every command leads its own process group, so descendants cannot survive cancellation.
        unsafe {
            libc::kill(-(child.id() as i32), libc::SIGKILL);
        }
    }
    let _ = child.kill();
    let start = Instant::now();
    while start.elapsed() < REAP_GRACE {
        match child.try_wait() {
            Ok(Some(_)) | Err(_) => return,
            Ok(None) => thread::sleep(POLL_INTERVAL),
        }
    }
}

fn read_bounded(file: &mut File, limit: u64) -> Result<String, CommandErrorCause> {
    file.seek(SeekFrom::Start(0)).map_err(io_cause)?;
    let mut bytes = Vec::new();
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(io_cause)?;
    if bytes.len() as u64 > limit {
        return Err(CommandErrorCause::OutputLimit);
    }
    Ok(String::from_utf8_lossy(&bytes).into_owned())
}
