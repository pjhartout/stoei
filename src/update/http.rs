use std::fs::File;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::Path;
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use std::os::unix::process::CommandExt;

use super::MAX_ARCHIVE;

pub(super) const COMMAND: &str = "__stoei_http_fetch";
const MAX_URL_BYTES: usize = 8192;
const STDERR_LIMIT: u64 = 4096;
const MAX_TIMEOUT: Duration = Duration::from_secs(300);
const POLL_INTERVAL: Duration = Duration::from_millis(20);
const REAP_GRACE: Duration = Duration::from_secs(2);

trait Clock {
    fn elapsed(&self) -> Duration;
    fn wait(&mut self, duration: Duration);
}

struct RealClock(Instant);

impl Clock for RealClock {
    fn elapsed(&self) -> Duration {
        self.0.elapsed()
    }
    fn wait(&mut self, duration: Duration) {
        std::thread::park_timeout(duration);
    }
}

struct OwnedHelper(Option<Child>);

impl Drop for OwnedHelper {
    fn drop(&mut self) {
        if let Some(mut child) = self.0.take() {
            terminate_and_reap(&mut child);
        }
    }
}

fn terminate_and_reap(child: &mut Child) {
    unsafe {
        libc::kill(-(child.id() as i32), libc::SIGKILL);
    }
    let _ = child.kill();
    let mut clock = RealClock(Instant::now());
    loop {
        match child.try_wait() {
            Ok(Some(_)) | Err(_) => return,
            Ok(None) => {}
        }
        let elapsed = clock.elapsed();
        if elapsed >= REAP_GRACE {
            return;
        }
        clock.wait(POLL_INTERVAL.min(REAP_GRACE.saturating_sub(elapsed)));
    }
}

fn validate(url: &str, timeout: Duration, limit: u64) -> Result<(), String> {
    if timeout.is_zero() {
        return Err("HTTP request timed out".into());
    }
    if timeout > MAX_TIMEOUT || limit > MAX_ARCHIVE {
        return Err("HTTP request exceeds allowed limits".into());
    }
    if url.len() > MAX_URL_BYTES || !(url.starts_with("http://") || url.starts_with("https://")) {
        return Err("invalid HTTP request URL".into());
    }
    Ok(())
}

pub(super) fn fetch(
    executable: &Path,
    url: &str,
    timeout: Duration,
    limit: u64,
    cancelled: &AtomicBool,
) -> Result<Vec<u8>, String> {
    validate(url, timeout, limit)?;
    if cancelled.load(Ordering::Relaxed) {
        return Err("HTTP request cancelled".into());
    }
    let mut clock = RealClock(Instant::now());
    let mut command = Command::new(executable);
    command.args([
        COMMAND,
        url,
        &timeout.as_millis().max(1).to_string(),
        &limit.to_string(),
    ]);
    run(command, timeout, limit, cancelled, &mut clock)
}

fn configure(command: &mut Command, stdout: &File, stderr: &File) -> Result<(), String> {
    command
        .stdin(Stdio::null())
        .stdout(stdout.try_clone().map_err(|err| err.to_string())?)
        .stderr(stderr.try_clone().map_err(|err| err.to_string())?);
    command.process_group(0);
    #[cfg(target_os = "linux")]
    {
        let parent = std::process::id() as libc::pid_t;
        unsafe {
            command.pre_exec(move || {
                if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
                if libc::getppid() != parent {
                    libc::_exit(125);
                }
                Ok(())
            });
        }
    }
    Ok(())
}

fn run(
    mut command: Command,
    timeout: Duration,
    limit: u64,
    cancelled: &AtomicBool,
    clock: &mut impl Clock,
) -> Result<Vec<u8>, String> {
    if cancelled.load(Ordering::Relaxed) {
        return Err("HTTP request cancelled".into());
    }
    let mut stdout = tempfile::tempfile().map_err(|err| err.to_string())?;
    let mut stderr = tempfile::tempfile().map_err(|err| err.to_string())?;
    configure(&mut command, &stdout, &stderr)?;
    let mut helper = OwnedHelper(Some(command.spawn().map_err(|err| err.to_string())?));
    let status = wait(
        helper.0.as_mut().expect("spawned helper is owned"),
        &stdout,
        &stderr,
        timeout,
        limit,
        cancelled,
        clock,
    )?;
    helper.0.take();
    if !status.success() {
        let bytes = read_bounded(&mut stderr, STDERR_LIMIT)?;
        let message = String::from_utf8_lossy(&bytes);
        let message = message
            .trim()
            .strip_prefix("stoei: ")
            .unwrap_or(message.trim());
        return Err(if message.is_empty() {
            format!("HTTP helper failed: {status}")
        } else {
            message.to_owned()
        });
    }
    read_bounded(&mut stdout, limit)
}

fn wait(
    child: &mut Child,
    stdout: &File,
    stderr: &File,
    timeout: Duration,
    limit: u64,
    cancelled: &AtomicBool,
    clock: &mut impl Clock,
) -> Result<ExitStatus, String> {
    loop {
        if cancelled.load(Ordering::Relaxed) {
            return Err("HTTP request cancelled".into());
        }
        let elapsed = clock.elapsed();
        if elapsed >= timeout {
            return Err("HTTP request timed out".into());
        }
        if stdout.metadata().map_err(|err| err.to_string())?.len() > limit
            || stderr.metadata().map_err(|err| err.to_string())?.len() > STDERR_LIMIT
        {
            return Err("HTTP helper output exceeds byte limit".into());
        }
        if let Some(status) = child.try_wait().map_err(|err| err.to_string())? {
            return Ok(status);
        }
        clock.wait(POLL_INTERVAL.min(timeout.saturating_sub(elapsed)));
    }
}

fn read_bounded(file: &mut File, limit: u64) -> Result<Vec<u8>, String> {
    file.seek(SeekFrom::Start(0))
        .map_err(|err| err.to_string())?;
    let mut bytes = Vec::new();
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|err| err.to_string())?;
    if bytes.len() as u64 > limit {
        return Err("HTTP helper output exceeds byte limit".into());
    }
    Ok(bytes)
}

pub(super) fn helper(arguments: &[String], output: &mut impl Write) -> Result<(), String> {
    let [url, timeout, limit] = arguments else {
        return Err("invalid HTTP helper arguments".into());
    };
    let timeout = Duration::from_millis(timeout.parse().map_err(|_| "invalid HTTP timeout")?);
    let limit = limit.parse().map_err(|_| "invalid HTTP byte limit")?;
    validate(url, timeout, limit)?;
    let agent: ureq::Agent = ureq::Agent::config_builder()
        .timeout_global(Some(timeout))
        .build()
        .into();
    let mut response = agent
        .get(url)
        .header("User-Agent", "stoei")
        .call()
        .map_err(|err| err.to_string())?;
    if response.status() != 200 {
        return Err(format!("download {url}: {}", response.status()));
    }
    let count = std::io::copy(&mut response.body_mut().as_reader().take(limit + 1), output)
        .map_err(|err| err.to_string())?;
    if count > limit {
        return Err(format!("HTTP response exceeds {limit} bytes"));
    }
    output.flush().map_err(|err| err.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestClock<'a> {
        elapsed: Duration,
        advance: Duration,
        cancel_on_wait: Option<&'a AtomicBool>,
        waits: usize,
    }

    impl Clock for TestClock<'_> {
        fn elapsed(&self) -> Duration {
            self.elapsed
        }
        fn wait(&mut self, duration: Duration) {
            assert!(!duration.is_zero());
            self.elapsed += self.advance;
            self.waits += 1;
            if let Some(cancelled) = self.cancel_on_wait {
                cancelled.store(true, Ordering::Relaxed);
            }
        }
    }

    fn supervise(
        clock: &mut TestClock<'_>,
        cancelled: &AtomicBool,
        oversized: bool,
    ) -> Result<ExitStatus, String> {
        let mut stdout = tempfile::tempfile().unwrap();
        let stderr = tempfile::tempfile().unwrap();
        let mut command = Command::new(std::env::current_exe().unwrap());
        command.args([
            "--ignored",
            "--exact",
            "update::http::tests::blocked_helper_fixture",
            "--nocapture",
        ]);
        configure(&mut command, &stdout, &stderr).unwrap();
        let mut helper = OwnedHelper(Some(command.spawn().unwrap()));
        let child = helper.0.as_mut().unwrap();
        let pid = child.id() as libc::pid_t;
        assert_eq!(unsafe { libc::getpgid(pid) }, pid);
        if oversized {
            stdout.write_all(&[b'x'; 1025]).unwrap();
        }
        let result = wait(
            child,
            &stdout,
            &stderr,
            Duration::from_secs(1),
            1024,
            cancelled,
            clock,
        );
        drop(helper);
        {
            assert_eq!(
                unsafe { libc::waitpid(pid, std::ptr::null_mut(), libc::WNOHANG) },
                -1
            );
            assert_eq!(
                std::io::Error::last_os_error().raw_os_error(),
                Some(libc::ECHILD)
            );
        }
        result
    }

    #[test]
    fn deadline_kills_and_reaps_the_helper() {
        let mut clock = TestClock {
            elapsed: Duration::ZERO,
            advance: Duration::from_secs(1),
            cancel_on_wait: None,
            waits: 0,
        };
        let error = supervise(&mut clock, &AtomicBool::new(false), false).unwrap_err();
        assert_eq!(error, "HTTP request timed out");
        assert_eq!(clock.waits, 1);
    }

    #[test]
    fn cancellation_kills_and_reaps_an_active_helper() {
        let cancelled = AtomicBool::new(false);
        let mut clock = TestClock {
            elapsed: Duration::ZERO,
            advance: Duration::ZERO,
            cancel_on_wait: Some(&cancelled),
            waits: 0,
        };
        let error = supervise(&mut clock, &cancelled, false).unwrap_err();
        assert_eq!(error, "HTTP request cancelled");
        assert_eq!(clock.waits, 1);
    }

    #[test]
    fn oversized_output_kills_and_reaps_the_helper() {
        let mut clock = TestClock {
            elapsed: Duration::ZERO,
            advance: Duration::ZERO,
            cancel_on_wait: None,
            waits: 0,
        };
        let error = supervise(&mut clock, &AtomicBool::new(false), true).unwrap_err();
        assert_eq!(error, "HTTP helper output exceeds byte limit");
        assert_eq!(clock.waits, 0);
    }

    #[test]
    fn cancelled_requests_and_invalid_limits_never_spawn() {
        assert_eq!(
            fetch(
                Path::new("never-executed"),
                "http://127.0.0.1/",
                Duration::from_secs(1),
                1024,
                &AtomicBool::new(true)
            ),
            Err("HTTP request cancelled".into())
        );
        assert!(validate("http://127.0.0.1/", Duration::ZERO, 1).is_err());
        assert!(validate("http://127.0.0.1/", MAX_TIMEOUT + Duration::from_secs(1), 1).is_err());
        assert!(validate("http://127.0.0.1/", MAX_TIMEOUT, MAX_ARCHIVE + 1).is_err());
    }

    #[test]
    #[ignore = "subprocess fixture only"]
    fn blocked_helper_fixture() {
        loop {
            std::thread::park();
        }
    }
}
