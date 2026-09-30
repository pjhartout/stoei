mod wait;

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, SyncSender};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use crossterm::event::{self, Event as TerminalEvent};

use crate::ui::ActionResult;

use super::{Event, io, send_event};

pub(super) enum Directive {
    Read,
    Editor(PathBuf),
    Stop,
}

pub(super) struct Input {
    directives: Option<SyncSender<Directive>>,
    thread: Option<JoinHandle<()>>,
    stopped: Arc<AtomicBool>,
    wake: wait::Wake,
    stdin: Option<wait::Stdin>,
}

impl Input {
    pub(super) fn new(events: SyncSender<Event>, stopped: Arc<AtomicBool>) -> Result<Self, String> {
        let stdin = wait::Stdin::new().map_err(|err| err.to_string())?;
        // Initialize Crossterm before installing the additional resize wakeup.
        event::poll(Duration::from_millis(1)).map_err(|err| err.to_string())?;
        let (mut waiter, wake) =
            wait::Waiter::new(stopped.clone()).map_err(|err| err.to_string())?;
        let mut input = Self::start(events, stopped, wake, move |stopped| {
            while !stopped.load(Ordering::Relaxed) {
                // The tty parser needs a positive timeout; native wait handles all idle time.
                if event::poll(Duration::from_millis(1))? {
                    return event::read().map(Some);
                }
                waiter.wait()?;
            }
            Ok(None)
        })?;
        input.stdin = Some(stdin);
        Ok(input)
    }

    fn start(
        events: SyncSender<Event>,
        stopped: Arc<AtomicBool>,
        wake: wait::Wake,
        read: impl FnMut(&AtomicBool) -> std::io::Result<Option<TerminalEvent>> + Send + 'static,
    ) -> Result<Self, String> {
        let (sender, directives) = mpsc::sync_channel(1);
        let shutdown = stopped.clone();
        let thread = thread::Builder::new()
            .name("stoei-input".into())
            .stack_size(256 * 1024)
            .spawn(move || {
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    pump(read, &events, directives, &shutdown)
                }))
                .unwrap_or_else(|_| Err("terminal input worker panicked".into()));
                if let Err(err) = result {
                    let _ = events.try_send(Event::WorkerError(err));
                }
                shutdown.store(true, Ordering::Relaxed);
                let _ = events.try_send(Event::Quit);
            })
            .map_err(|err| err.to_string())?;
        Ok(Self {
            directives: Some(sender),
            thread: Some(thread),
            stopped,
            wake,
            stdin: None,
        })
    }

    pub(super) fn send(&self, directive: Directive) -> Result<(), String> {
        self.directives
            .as_ref()
            .ok_or("input reader stopped")?
            .try_send(directive)
            .map_err(|err| format!("input reader: {err}"))
    }

    pub(super) fn stopped(&self) -> bool {
        self.stopped.load(Ordering::Relaxed)
    }

    pub(super) fn stop(&mut self) {
        self.stopped.store(true, Ordering::Relaxed);
        self.directives.take();
        (self.wake)();
    }
}

impl Drop for Input {
    fn drop(&mut self) {
        self.stop();
        if let Some(thread) = self.thread.take() {
            let deadline = Instant::now() + Duration::from_secs(2);
            while !thread.is_finished() && Instant::now() < deadline {
                thread::park_timeout(Duration::from_millis(10));
            }
            if thread.is_finished() {
                let _ = thread.join();
            }
        }
    }
}

fn pump(
    mut read: impl FnMut(&AtomicBool) -> std::io::Result<Option<TerminalEvent>>,
    events: &SyncSender<Event>,
    directives: Receiver<Directive>,
    stopped: &AtomicBool,
) -> Result<(), String> {
    while !stopped.load(Ordering::Relaxed) {
        let Some(input) = read(stopped).map_err(|err| format!("terminal input: {err}"))? else {
            return Ok(());
        };
        if !send_event(events, Event::Input(input), stopped) {
            return Ok(());
        }
        loop {
            match directives.recv() {
                Ok(Directive::Read) => break,
                Ok(Directive::Stop) | Err(_) => return Ok(()),
                Ok(Directive::Editor(path)) => {
                    let result = io::editor(&path, stopped);
                    if !send_event(
                        events,
                        Event::Action(ActionResult::EditorDone(result)),
                        stopped,
                    ) {
                        return Ok(());
                    }
                }
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn input_failure_stops_the_app_and_reports_the_error() {
        let (events, receiver) = mpsc::sync_channel(2);
        let input = Input::start(
            events,
            Arc::new(AtomicBool::new(false)),
            Box::new(|| {}),
            |_| Err(std::io::Error::other("input disconnected")),
        )
        .unwrap();
        assert!(matches!(
            receiver.recv().unwrap(),
            Event::WorkerError(message) if message.contains("input disconnected")
        ));
        assert!(matches!(receiver.recv().unwrap(), Event::Quit));
        assert!(input.stopped());
        drop(input);
    }

    #[test]
    fn unexpected_input_end_stops_the_app_with_a_full_event_queue() {
        let (events, receiver) = mpsc::sync_channel(1);
        events
            .try_send(Event::Input(TerminalEvent::FocusGained))
            .unwrap();
        let mut input = Input::start(
            events,
            Arc::new(AtomicBool::new(false)),
            Box::new(|| {}),
            |_| Ok(None),
        )
        .unwrap();
        input.thread.take().unwrap().join().unwrap();
        assert!(input.stopped());
        assert!(matches!(receiver.try_recv().unwrap(), Event::Input(_)));
    }

    #[test]
    fn blocked_input_is_woken_and_joined_on_drop() {
        let (events, _receiver) = mpsc::sync_channel(1);
        let (ready, started) = mpsc::sync_channel(1);
        let (wake, wait) = mpsc::sync_channel(1);
        let stopped = Arc::new(AtomicBool::new(false));
        let finished = Arc::new(AtomicBool::new(false));
        let ended = finished.clone();
        let input = Input::start(
            events,
            stopped.clone(),
            Box::new(move || {
                let _ = wake.try_send(());
            }),
            move |stopped| {
                ready.send(()).unwrap();
                wait.recv().unwrap();
                assert!(stopped.load(Ordering::Relaxed));
                ended.store(true, Ordering::Relaxed);
                Ok(None)
            },
        )
        .unwrap();
        started.recv().unwrap();
        drop(input);
        assert!(stopped.load(Ordering::Relaxed));
        assert!(finished.load(Ordering::Relaxed));
    }

    #[test]
    fn dropping_input_releases_directive_wait_without_another_key() {
        let (events, receiver) = mpsc::sync_channel(1);
        let stopped = Arc::new(AtomicBool::new(false));
        let input = Input::start(events, stopped, Box::new(|| {}), |_| {
            Ok(Some(TerminalEvent::FocusGained))
        })
        .unwrap();
        assert!(matches!(
            receiver.recv().unwrap(),
            Event::Input(TerminalEvent::FocusGained)
        ));
        drop(input);
        assert!(matches!(receiver.recv(), Ok(Event::Quit) | Err(_)));
    }

    #[test]
    fn input_reads_only_after_acknowledgement() {
        let (events, receiver) = mpsc::sync_channel(1);
        let reads = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let count = reads.clone();
        let input = Input::start(
            events,
            Arc::new(AtomicBool::new(false)),
            Box::new(|| {}),
            move |_| {
                count.fetch_add(1, Ordering::Relaxed);
                Ok(Some(TerminalEvent::FocusGained))
            },
        )
        .unwrap();
        assert!(matches!(receiver.recv().unwrap(), Event::Input(_)));
        assert_eq!(reads.load(Ordering::Relaxed), 1);
        input.send(Directive::Read).unwrap();
        assert!(matches!(receiver.recv().unwrap(), Event::Input(_)));
        assert_eq!(reads.load(Ordering::Relaxed), 2);
        drop(input);
        assert_eq!(reads.load(Ordering::Relaxed), 2);
    }

    #[test]
    fn partial_terminal_input_stops_and_restores_stdin() {
        use std::io::{BufRead, BufReader, Write};
        use std::os::fd::{FromRawFd, OwnedFd};
        use std::os::unix::process::CommandExt;
        use std::process::{Command, Stdio};

        let mut master = -1;
        let mut slave = -1;
        let mut size = libc::winsize {
            ws_row: 24,
            ws_col: 80,
            ws_xpixel: 0,
            ws_ypixel: 0,
        };
        assert_eq!(
            unsafe {
                libc::openpty(
                    &mut master,
                    &mut slave,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    std::ptr::addr_of_mut!(size),
                )
            },
            0
        );
        let mut master = std::fs::File::from(unsafe { OwnedFd::from_raw_fd(master) });
        let slave = std::fs::File::from(unsafe { OwnedFd::from_raw_fd(slave) });
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--ignored",
                "--exact",
                "engine::input::tests::terminal_process",
            ])
            .env("STOEI_INPUT_PTY_FIXTURE", "1")
            .stdin(slave.try_clone().unwrap())
            .stdout(slave)
            .stderr(Stdio::piped());
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() < 0
                    || libc::ioctl(libc::STDIN_FILENO, libc::TIOCSCTTY as _, 0) < 0
                {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let mut child = command.spawn().unwrap();
        let mut ready = String::new();
        BufReader::new(child.stderr.take().unwrap())
            .read_line(&mut ready)
            .unwrap();
        assert_eq!(ready, "input ready\n");
        master.write_all(b"\x1b[").unwrap();
        assert_eq!(unsafe { libc::kill(child.id() as i32, libc::SIGTERM) }, 0);
        assert!(child.wait().unwrap().success());
    }

    #[test]
    #[ignore]
    fn terminal_process() {
        if std::env::var_os("STOEI_INPUT_PTY_FIXTURE").is_none() {
            return;
        }
        use std::io::Write;
        let flags = |fd| unsafe { libc::fcntl(fd, libc::F_GETFL) };
        let original = flags(libc::STDIN_FILENO);
        let output = flags(libc::STDOUT_FILENO);
        crossterm::terminal::enable_raw_mode().unwrap();
        let (events, receiver) = mpsc::sync_channel(1);
        let input = Input::new(events, Arc::new(AtomicBool::new(false))).unwrap();
        assert_ne!(flags(libc::STDIN_FILENO) & libc::O_NONBLOCK, 0);
        assert_eq!(flags(libc::STDOUT_FILENO), output);
        std::io::stderr().write_all(b"input ready\n").unwrap();
        while !input.stopped() {
            match receiver.recv().unwrap() {
                Event::Input(_) => {
                    let _ = input.send(Directive::Read);
                }
                Event::Quit => break,
                _ => panic!("unexpected terminal fixture event"),
            }
        }
        drop(input);
        assert_eq!(flags(libc::STDIN_FILENO), original);
        assert_eq!(flags(libc::STDOUT_FILENO), output);
        crossterm::terminal::disable_raw_mode().unwrap();
    }
}
