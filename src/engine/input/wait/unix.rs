use std::ffi::OsStr;
use std::io::{self, Read, Write};
use std::os::fd::{AsFd, AsRawFd, OwnedFd, RawFd};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;

use signal_hook::SigId;
use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM, SIGWINCH};

use super::Wake;

pub(in crate::engine::input) struct Stdin {
    original: OwnedFd,
}

impl Stdin {
    pub(in crate::engine::input) fn new() -> io::Result<Self> {
        let original = std::io::stdin().as_fd().try_clone_to_owned()?;
        let input = std::fs::File::options()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(tty_path()?)?;
        // A separate file description keeps stdout and the shell's stdin blocking.
        if unsafe { libc::dup2(input.as_raw_fd(), libc::STDIN_FILENO) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self { original })
    }
}

fn tty_path() -> io::Result<std::path::PathBuf> {
    let mut name = vec![0; libc::PATH_MAX as usize];
    // ttyname_r copies the owned path; no process-global ttyname buffer is shared.
    let error =
        unsafe { libc::ttyname_r(libc::STDIN_FILENO, name.as_mut_ptr().cast(), name.len()) };
    if error != 0 {
        return Err(io::Error::from_raw_os_error(error));
    }
    let end = name
        .iter()
        .position(|byte| *byte == 0)
        .ok_or_else(|| io::Error::other("terminal path exceeds buffer"))?;
    Ok(std::path::PathBuf::from(OsStr::from_bytes(&name[..end])))
}

impl Drop for Stdin {
    fn drop(&mut self) {
        // The saved descriptor remains owned until the restoration completes.
        unsafe {
            libc::dup2(self.original.as_raw_fd(), libc::STDIN_FILENO);
        }
    }
}

pub(in crate::engine::input) struct Waiter {
    receiver: UnixStream,
    signals: Vec<SigId>,
}

impl Waiter {
    pub(in crate::engine::input) fn new(stopped: Arc<AtomicBool>) -> io::Result<(Self, Wake)> {
        let (receiver, sender) = UnixStream::pair()?;
        receiver.set_nonblocking(true)?;
        sender.set_nonblocking(true)?;
        let mut waiter = Self {
            receiver,
            signals: Vec::new(),
        };
        for signal in [SIGINT, SIGTERM, SIGHUP] {
            waiter
                .signals
                .push(signal_hook::flag::register(signal, stopped.clone())?);
            waiter.signals.push(signal_hook::low_level::pipe::register(
                signal,
                sender.try_clone()?,
            )?);
        }
        waiter.signals.push(signal_hook::low_level::pipe::register(
            SIGWINCH,
            sender.try_clone()?,
        )?);
        Ok((
            waiter,
            Box::new(move || {
                let _ = (&sender).write(&[1]);
            }),
        ))
    }

    pub(in crate::engine::input) fn wait(&mut self) -> io::Result<()> {
        self.wait_for(std::io::stdin().as_raw_fd())
    }

    fn wait_for(&mut self, input: RawFd) -> io::Result<()> {
        let mut fds = [
            libc::pollfd {
                fd: input,
                events: libc::POLLIN,
                revents: 0,
            },
            libc::pollfd {
                fd: self.receiver.as_raw_fd(),
                events: libc::POLLIN,
                revents: 0,
            },
        ];
        // Both descriptors stay owned and valid throughout the blocking wait.
        if unsafe { libc::poll(fds.as_mut_ptr(), fds.len() as libc::nfds_t, -1) } < 0 {
            let err = io::Error::last_os_error();
            return if err.kind() == io::ErrorKind::Interrupted {
                Ok(())
            } else {
                Err(err)
            };
        }
        if fds
            .iter()
            .any(|fd| fd.revents & (libc::POLLHUP | libc::POLLERR | libc::POLLNVAL) != 0)
        {
            return Err(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "terminal input closed",
            ));
        }
        if fds[1].revents & libc::POLLIN != 0 {
            match self.receiver.read(&mut [0; 256]) {
                Ok(_) => {}
                Err(err)
                    if matches!(
                        err.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                    ) => {}
                Err(err) => return Err(err),
            }
        }
        Ok(())
    }
}

impl Drop for Waiter {
    fn drop(&mut self) {
        for signal in self.signals.drain(..) {
            signal_hook::low_level::unregister(signal);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::Ordering;

    #[test]
    fn stop_wakeup_is_retained_before_entering_native_wait() {
        let (terminal, _sender) = UnixStream::pair().unwrap();
        let stopped = Arc::new(AtomicBool::new(false));
        let (mut waiter, wake) = Waiter::new(stopped.clone()).unwrap();
        stopped.store(true, Ordering::Relaxed);
        wake();
        waiter.wait_for(terminal.as_raw_fd()).unwrap();
        assert!(stopped.load(Ordering::Relaxed));
    }

    #[test]
    fn terminal_hangup_ends_native_wait() {
        let (terminal, sender) = UnixStream::pair().unwrap();
        let (mut waiter, _wake) = Waiter::new(Arc::new(AtomicBool::new(false))).unwrap();
        drop(sender);
        let err = waiter.wait_for(terminal.as_raw_fd()).unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::BrokenPipe);
    }
}
