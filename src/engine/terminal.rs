use std::io;
use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, Ordering};

#[derive(Clone)]
pub(super) struct State(platform::State);

impl State {
    pub(super) fn capture() -> io::Result<Self> {
        platform::State::capture().map(Self)
    }

    pub(super) fn restore(&self) -> io::Result<()> {
        self.0.restore()
    }
}

pub(super) struct EditorSession<'a> {
    state: State,
    flags: Option<platform::Flags>,
    stopped: &'a AtomicBool,
    restored: bool,
}

impl<'a> EditorSession<'a> {
    pub(super) fn new(stopped: &'a AtomicBool) -> io::Result<Self> {
        Ok(Self {
            state: State::capture()?,
            flags: Some(platform::Flags::blocking_stdin()?),
            stopped,
            restored: false,
        })
    }

    pub(super) fn foreground(&self, id: u32) -> io::Result<()> {
        platform::foreground(id)
    }

    pub(super) fn suspend(&self) -> io::Result<()> {
        let editor = State::capture()?;
        self.state.restore()?;
        loop {
            // Stop stoei itself so its shell can return to the prompt without changing other jobs.
            if unsafe { libc::raise(libc::SIGSTOP) } != 0 {
                return Err(io::Error::last_os_error());
            }
            if self.stopped.load(Ordering::Relaxed) {
                return Ok(());
            }
            let foreground = unsafe { libc::tcgetpgrp(libc::STDIN_FILENO) };
            if foreground < 0 {
                return Err(io::Error::last_os_error());
            }
            if foreground == unsafe { libc::getpgrp() } {
                return editor.restore();
            }
        }
    }

    pub(super) fn restore(&mut self) -> io::Result<()> {
        if self.restored {
            return Ok(());
        }
        self.restored = true;
        let state = self.state.restore();
        let flags = match self.flags.take() {
            Some(flags) if !self.stopped.load(Ordering::Relaxed) => flags.restore(),
            _ => Ok(()),
        };
        state.and(flags)
    }
}

impl Drop for EditorSession<'_> {
    fn drop(&mut self) {
        let _ = self.restore();
    }
}

pub(super) fn configure_editor(command: &mut Command) {
    platform::configure_editor(command);
}

#[cfg(test)]
pub(super) fn attach_test_terminal() -> io::Result<()> {
    if unsafe { libc::setsid() } < 0
        || unsafe { libc::ioctl(libc::STDIN_FILENO, libc::TIOCSCTTY as _, 0) } < 0
    {
        return Err(io::Error::last_os_error());
    }
    platform::foreground(unsafe { libc::getpgrp() } as u32)
}

#[cfg(test)]
pub(super) struct FixtureChild(pub(super) Child);

#[cfg(test)]
impl Drop for FixtureChild {
    fn drop(&mut self) {
        if matches!(self.0.try_wait(), Ok(Some(_))) {
            return;
        }
        unsafe {
            libc::kill(-(self.0.id() as i32), libc::SIGKILL);
        }
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

pub(super) fn editor_stopped(child: &Child) -> io::Result<bool> {
    let mut event = std::mem::MaybeUninit::<libc::siginfo_t>::zeroed();
    // Consume only stop events; Child::try_wait retains ownership of exit-status reaping.
    let result = unsafe {
        libc::waitid(
            libc::P_PID,
            child.id() as libc::id_t,
            event.as_mut_ptr(),
            libc::WSTOPPED | libc::WNOHANG,
        )
    };
    if result < 0 {
        let error = io::Error::last_os_error();
        return if error.raw_os_error() == Some(libc::ECHILD)
            || error.kind() == io::ErrorKind::Interrupted
        {
            Ok(false)
        } else {
            Err(error)
        };
    }
    Ok(unsafe { event.assume_init() }.si_code == libc::CLD_STOPPED)
}

pub(super) struct EditorGroup(platform::EditorGroup);

impl EditorGroup {
    pub(super) fn new(child: &Child) -> io::Result<Self> {
        platform::EditorGroup::new(child).map(Self)
    }

    pub(super) fn signal(&self, force: bool) {
        self.0.signal(force);
    }

    pub(super) fn resume(&self) {
        self.0.resume();
    }

    pub(super) fn alive(&self) -> bool {
        self.0.alive()
    }
}

mod platform {
    use std::io;
    use std::os::unix::process::CommandExt;
    use std::process::{Child, Command};

    #[derive(Clone)]
    pub(super) struct State {
        attrs: libc::termios,
        foreground: libc::pid_t,
    }

    impl State {
        pub(super) fn capture() -> io::Result<Self> {
            let mut attrs = std::mem::MaybeUninit::uninit();
            // tcgetattr initializes every field before the value is assumed initialized.
            if unsafe { libc::tcgetattr(libc::STDIN_FILENO, attrs.as_mut_ptr()) } < 0 {
                return Err(io::Error::last_os_error());
            }
            let foreground = unsafe { libc::tcgetpgrp(libc::STDIN_FILENO) };
            if foreground < 0 {
                return Err(io::Error::last_os_error());
            }
            Ok(Self {
                attrs: unsafe { attrs.assume_init() },
                foreground,
            })
        }

        pub(super) fn restore(&self) -> io::Result<()> {
            terminal_io(|| {
                let foreground = set_foreground_unmasked(self.foreground);
                let attrs =
                    if unsafe { libc::tcsetattr(libc::STDIN_FILENO, libc::TCSANOW, &self.attrs) }
                        < 0
                    {
                        Err(io::Error::last_os_error())
                    } else {
                        Ok(())
                    };
                foreground.and(attrs)
            })
        }
    }

    pub(super) struct Flags(libc::c_int);

    impl Flags {
        pub(super) fn blocking_stdin() -> io::Result<Self> {
            let flags = unsafe { libc::fcntl(libc::STDIN_FILENO, libc::F_GETFL) };
            if flags < 0 {
                return Err(io::Error::last_os_error());
            }
            set_flags(flags & !libc::O_NONBLOCK)?;
            Ok(Self(flags))
        }

        pub(super) fn restore(self) -> io::Result<()> {
            set_flags(self.0)
        }
    }

    fn set_flags(flags: libc::c_int) -> io::Result<()> {
        if unsafe { libc::fcntl(libc::STDIN_FILENO, libc::F_SETFL, flags) } < 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(())
        }
    }

    pub(super) fn foreground(id: u32) -> io::Result<()> {
        let id = libc::pid_t::try_from(id).map_err(|_| io::Error::other("invalid editor pid"))?;
        set_foreground(id)
    }

    fn set_foreground(group: libc::pid_t) -> io::Result<()> {
        terminal_io(|| set_foreground_unmasked(group))
    }

    fn set_foreground_unmasked(group: libc::pid_t) -> io::Result<()> {
        if unsafe { libc::tcsetpgrp(libc::STDIN_FILENO, group) } < 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(())
        }
    }

    fn terminal_io(action: impl FnOnce() -> io::Result<()>) -> io::Result<()> {
        let mut blocked = std::mem::MaybeUninit::<libc::sigset_t>::uninit();
        let mut previous = std::mem::MaybeUninit::<libc::sigset_t>::uninit();
        // A handoff makes this thread's process background before termios restoration finishes.
        unsafe {
            libc::sigemptyset(blocked.as_mut_ptr());
            libc::sigaddset(blocked.as_mut_ptr(), libc::SIGTTOU);
        }
        let error = unsafe {
            libc::pthread_sigmask(libc::SIG_BLOCK, blocked.as_ptr(), previous.as_mut_ptr())
        };
        if error != 0 {
            return Err(io::Error::from_raw_os_error(error));
        }
        let result = action();
        let error = unsafe {
            libc::pthread_sigmask(libc::SIG_SETMASK, previous.as_ptr(), std::ptr::null_mut())
        };
        result.and(if error == 0 {
            Ok(())
        } else {
            Err(io::Error::from_raw_os_error(error))
        })
    }

    pub(super) fn configure_editor(command: &mut Command) {
        command.process_group(0);
    }

    pub(super) struct EditorGroup(libc::pid_t);

    impl EditorGroup {
        pub(super) fn new(child: &Child) -> io::Result<Self> {
            let id = libc::pid_t::try_from(child.id())
                .map_err(|_| io::Error::other("invalid editor pid"))?;
            Ok(Self(id))
        }

        pub(super) fn signal(&self, force: bool) {
            unsafe {
                libc::kill(-self.0, if force { libc::SIGKILL } else { libc::SIGTERM });
            }
        }

        pub(super) fn resume(&self) {
            unsafe {
                libc::kill(-self.0, libc::SIGCONT);
            }
        }

        pub(super) fn alive(&self) -> bool {
            unsafe { libc::kill(-self.0, 0) == 0 }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::File;
    use std::io::{BufRead, BufReader, Read, Write};
    use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::process::CommandExt;
    use std::process::Stdio;

    #[test]
    fn editor_session_restores_modes_foreground_and_flags() {
        let (_master, slave) = pty();
        eprintln!("editor fixture: terminal opened");
        let inspect = slave.try_clone().unwrap();
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--ignored",
                "--exact",
                "engine::terminal::tests::session_process",
                "--nocapture",
            ])
            .env("STOEI_EDITOR_SESSION_FIXTURE", "1")
            .stdin(slave.try_clone().unwrap())
            .stdout(Stdio::null())
            .stderr(Stdio::piped());
        unsafe {
            command.pre_exec(attach_test_terminal);
        }
        let mut child = FixtureChild(command.spawn().unwrap());
        eprintln!("editor fixture: child started");
        let mut stderr = BufReader::new(child.0.stderr.take().unwrap());
        let mut ready = String::new();
        stderr.read_line(&mut ready).unwrap();
        assert_eq!(ready, "editor suspending\n");
        eprintln!("editor fixture: ready to suspend");
        let mut status = 0;
        assert_eq!(
            unsafe { libc::waitpid(child.0.id() as i32, &mut status, libc::WUNTRACED) },
            child.0.id() as i32
        );
        assert!(libc::WIFSTOPPED(status));
        eprintln!("editor fixture: suspended");
        let mut current = std::mem::MaybeUninit::<libc::termios>::uninit();
        assert_eq!(
            unsafe { libc::tcgetattr(inspect.as_raw_fd(), current.as_mut_ptr()) },
            0
        );
        let current = unsafe { current.assume_init() };
        assert_ne!(current.c_lflag & libc::ICANON, 0);
        assert_ne!(current.c_lflag & libc::ECHO, 0);
        assert_eq!(unsafe { libc::kill(child.0.id() as i32, libc::SIGCONT) }, 0);
        eprintln!("editor fixture: resumed");
        let status = child.0.wait().unwrap();
        let mut errors = String::new();
        stderr.read_to_string(&mut errors).unwrap();
        assert!(status.success(), "{status}: {errors}");
    }

    fn pty() -> (File, File) {
        let mut master = -1;
        let mut slave = -1;
        assert_eq!(
            unsafe {
                libc::openpty(
                    &mut master,
                    &mut slave,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                )
            },
            0
        );
        (
            File::from(unsafe { OwnedFd::from_raw_fd(master) }),
            File::from(unsafe { OwnedFd::from_raw_fd(slave) }),
        )
    }

    fn attrs() -> libc::termios {
        let mut attrs = std::mem::MaybeUninit::uninit();
        assert_eq!(
            unsafe { libc::tcgetattr(libc::STDIN_FILENO, attrs.as_mut_ptr()) },
            0
        );
        unsafe { attrs.assume_init() }
    }

    #[test]
    #[ignore]
    fn session_process() {
        if std::env::var_os("STOEI_EDITOR_SESSION_FIXTURE").is_none() {
            return;
        }
        let initial = attrs();
        let group = unsafe { libc::tcgetpgrp(libc::STDIN_FILENO) };
        for stopping in [false, true] {
            let input = File::options()
                .read(true)
                .write(true)
                .custom_flags(libc::O_NONBLOCK)
                .open("/dev/tty")
                .unwrap();
            assert_eq!(
                unsafe { libc::dup2(input.as_raw_fd(), libc::STDIN_FILENO) },
                0
            );
            let stopped = AtomicBool::new(false);
            let mut session = EditorSession::new(&stopped).unwrap();
            let (mut child, editor) = raw_editor(&session);
            let current = attrs();
            assert_eq!(current.c_lflag & libc::ICANON, 0);
            assert_eq!(current.c_lflag & libc::ECHO, 0);
            if !stopping {
                pause_editor(&child.0, &session);
                editor.resume();
                assert_eq!(attrs().c_lflag & libc::ICANON, 0);
            }
            editor.signal(true);
            child.0.wait().unwrap();
            stopped.store(stopping, Ordering::Relaxed);
            session.restore().unwrap();
            let current = attrs();
            assert_eq!(current.c_iflag, initial.c_iflag);
            assert_eq!(current.c_oflag, initial.c_oflag);
            assert_eq!(current.c_cflag, initial.c_cflag);
            assert_eq!(current.c_lflag, initial.c_lflag);
            assert_eq!(current.c_cc, initial.c_cc);
            assert_eq!(unsafe { libc::tcgetpgrp(libc::STDIN_FILENO) }, group);
            let flags = unsafe { libc::fcntl(libc::STDIN_FILENO, libc::F_GETFL) };
            assert_eq!(flags & libc::O_NONBLOCK != 0, !stopping);
        }
    }

    fn pause_editor(child: &Child, session: &EditorSession<'_>) {
        assert_eq!(
            unsafe { libc::kill(-(child.id() as i32), libc::SIGSTOP) },
            0
        );
        let mut event = std::mem::MaybeUninit::<libc::siginfo_t>::zeroed();
        assert_eq!(
            unsafe {
                libc::waitid(
                    libc::P_PID,
                    child.id() as libc::id_t,
                    event.as_mut_ptr(),
                    libc::WSTOPPED | libc::WNOWAIT,
                )
            },
            0
        );
        assert!(editor_stopped(child).unwrap());
        assert!(!editor_stopped(child).unwrap());
        std::io::stderr().write_all(b"editor suspending\n").unwrap();
        session.suspend().unwrap();
    }

    fn raw_editor(session: &EditorSession<'_>) -> (FixtureChild, EditorGroup) {
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--ignored",
                "--exact",
                "engine::terminal::tests::raw_editor_process",
                "--nocapture",
            ])
            .env("STOEI_RAW_EDITOR_FIXTURE", "1")
            .stdout(Stdio::piped());
        configure_editor(&mut command);
        let mut child = FixtureChild(command.spawn().unwrap());
        let group = EditorGroup::new(&child.0).unwrap();
        let mut status = 0;
        assert_eq!(
            unsafe { libc::waitpid(child.0.id() as i32, &mut status, libc::WUNTRACED) },
            child.0.id() as i32
        );
        assert!(libc::WIFSTOPPED(status));
        session.foreground(child.0.id()).unwrap();
        group.resume();
        let mut output = BufReader::new(child.0.stdout.take().unwrap());
        let mut line = String::new();
        for _ in 0..8 {
            line.clear();
            assert_ne!(output.read_line(&mut line).unwrap(), 0);
            if line.contains("editor modes changed") {
                break;
            }
        }
        assert!(line.contains("editor modes changed"));
        (child, group)
    }

    #[test]
    #[ignore]
    fn raw_editor_process() {
        if std::env::var_os("STOEI_RAW_EDITOR_FIXTURE").is_none() {
            return;
        }
        assert_eq!(unsafe { libc::raise(libc::SIGSTOP) }, 0);
        let flags = unsafe { libc::fcntl(libc::STDIN_FILENO, libc::F_GETFL) };
        assert_eq!(flags & libc::O_NONBLOCK, 0);
        let mut raw = attrs();
        unsafe {
            libc::cfmakeraw(&mut raw);
        }
        assert_eq!(
            unsafe { libc::tcsetattr(libc::STDIN_FILENO, libc::TCSANOW, &raw) },
            0
        );
        assert_eq!(unsafe { libc::tcgetpgrp(libc::STDIN_FILENO) }, unsafe {
            libc::getpgrp()
        });
        println!("editor modes changed");
        std::io::stdout().flush().unwrap();
        loop {
            std::thread::park();
        }
    }
}
