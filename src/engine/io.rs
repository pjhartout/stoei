use std::collections::VecDeque;
use std::fs::File;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use crate::ui::Tail;

use super::terminal;

const MAX_TAIL_BYTES: usize = 16 * 1024 * 1024;
const MAX_LINE_BYTES: usize = 16 * 1024;
const MAX_INPUT_BYTES: u64 = 8 * 1024 * 1024 * 1024;

pub fn read_tail(path: &Path, max_lines: usize, stopped: &AtomicBool) -> Result<Tail, String> {
    if !path.metadata().map_err(|err| err.to_string())?.is_file() {
        return Err("log viewer requires a regular file".into());
    }
    let file = File::open(path).map_err(|err| format!("{}: {err}", path.display()))?;
    let length = file.metadata().map_err(|err| err.to_string())?.len();
    if length > MAX_INPUT_BYTES {
        return Err("log exceeds 8 GiB; open it in your editor".into());
    }
    let reader = BufReader::new(file.take(length));
    let deadline = Instant::now() + Duration::from_secs(15);
    let (lines, first_line, total_lines) = tail_reader(reader, max_lines, || {
        if stopped.load(Ordering::Relaxed) {
            Err("log read cancelled".into())
        } else if Instant::now() >= deadline {
            Err("log read exceeded 15 seconds; open it in your editor".into())
        } else {
            Ok(())
        }
    })?;
    Ok(Tail {
        path: path.to_path_buf(),
        lines,
        first_line,
        total_lines,
    })
}

fn tail_reader(
    mut reader: impl BufRead,
    max_lines: usize,
    mut check: impl FnMut() -> Result<(), String>,
) -> Result<(Vec<String>, u64, u64), String> {
    if max_lines == 0 || max_lines > 100_000 {
        return Err("log tail line count must be between 1 and 100000".into());
    }
    let mut lines = VecDeque::new();
    let mut line = Vec::new();
    let mut truncated = false;
    let mut bytes = 0;
    let mut total = 0;
    loop {
        check()?;
        let buffer = reader.fill_buf().map_err(|err| err.to_string())?;
        if buffer.is_empty() {
            if !line.is_empty() || truncated {
                push_line(
                    &mut lines, &mut bytes, &mut total, &line, truncated, max_lines,
                );
            }
            break;
        }
        let consumed = buffer
            .iter()
            .position(|byte| *byte == b'\n')
            .map_or(buffer.len(), |index| index + 1);
        let newline = buffer[consumed - 1] == b'\n';
        let content = &buffer[..consumed - usize::from(newline)];
        let retained = (MAX_LINE_BYTES - line.len()).min(content.len());
        line.extend_from_slice(&content[..retained]);
        truncated |= retained < content.len();
        reader.consume(consumed);
        if newline {
            push_line(
                &mut lines, &mut bytes, &mut total, &line, truncated, max_lines,
            );
            line.clear();
            truncated = false;
        }
    }
    let first = total.saturating_sub(lines.len() as u64) + 1;
    Ok((lines.into_iter().collect(), first, total))
}

fn push_line(
    lines: &mut VecDeque<String>,
    bytes: &mut usize,
    total: &mut u64,
    raw: &[u8],
    truncated: bool,
    max_lines: usize,
) {
    let mut line = printable(&String::from_utf8_lossy(raw));
    if truncated {
        line.push_str(" … [line truncated]");
    }
    *total += 1;
    *bytes += line.len();
    lines.push_back(line);
    while lines.len() > max_lines || *bytes > MAX_TAIL_BYTES {
        if let Some(line) = lines.pop_front() {
            *bytes -= line.len();
        }
    }
    debug_assert!(lines.len() <= max_lines);
    debug_assert!(*bytes <= MAX_TAIL_BYTES);
}

fn printable(raw: &str) -> String {
    let mut out = String::new();
    let mut escape = false;
    let mut csi = false;
    let mut osc = false;
    let mut osc_escape = false;
    for character in raw.chars() {
        if osc {
            if character == '\u{7}' || (osc_escape && character == '\\') {
                osc = false;
            }
            osc_escape = character == '\u{1b}';
            continue;
        }
        if csi {
            if ('@'..='~').contains(&character) {
                csi = false;
            }
            continue;
        }
        if escape {
            csi = character == '[';
            osc = character == ']';
            escape = false;
            continue;
        }
        match character {
            '\u{1b}' => escape = true,
            '\t' => out.push_str("    "),
            character if character.is_control() => {}
            character => out.push(character),
        }
    }
    out
}

fn executable(name: &str) -> Option<PathBuf> {
    let direct = Path::new(name);
    if direct.components().count() > 1 {
        return executable_path(direct.to_path_buf());
    }
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path)
        .map(|directory| directory.join(name))
        .find_map(executable_path)
}

fn executable_path(path: PathBuf) -> Option<PathBuf> {
    use std::os::unix::fs::PermissionsExt;
    path.metadata()
        .is_ok_and(|metadata| metadata.is_file() && metadata.permissions().mode() & 0o111 != 0)
        .then_some(path)
}

pub fn editor(path: &Path, stopped: &AtomicBool) -> Result<(), String> {
    let configured = std::env::var("EDITOR")
        .ok()
        .and_then(|editor| shlex::split(&editor));
    let mut arguments = configured
        .filter(|arguments| !arguments.is_empty() && executable(&arguments[0]).is_some())
        .or_else(|| {
            ["vim", "nano", "vi"]
                .into_iter()
                .find(|name| executable(name).is_some())
                .map(|name| vec![name.to_owned()])
        })
        .ok_or("no editor available; set EDITOR")?;
    let program = executable(&arguments.remove(0)).ok_or("editor is no longer available")?;
    if stopped.load(Ordering::Relaxed) {
        return Err("editor cancelled".into());
    }
    let mut session = terminal::EditorSession::new(stopped).map_err(|err| err.to_string())?;
    let mut command = Command::new(program);
    command.args(arguments).arg(path);
    terminal::configure_editor(&mut command);
    let child = command.spawn().map_err(|err| err.to_string())?;
    let mut child = EditorChild::new(child)?;
    let foreground = session.foreground(child.child.id());
    let result = match foreground {
        Ok(()) => {
            child.group.resume();
            wait_editor(&mut child, stopped, Some(&session))
        }
        Err(error) => match child.poll() {
            Ok(Some(status)) => editor_status(status),
            _ => Err(format!("cannot give the editor the terminal: {error}")),
        },
    };
    drop(child);
    let restored = session
        .restore()
        .map_err(|err| format!("terminal restore: {err}"));
    match (result, restored) {
        (Err(error), Err(restored)) => Err(format!("{error}; {restored}")),
        (Err(error), _) | (_, Err(error)) => Err(error),
        _ => Ok(()),
    }
}

struct EditorChild {
    child: Child,
    group: terminal::EditorGroup,
    reaped: bool,
    cleanup_attempted: bool,
}

impl EditorChild {
    fn new(mut child: Child) -> Result<Self, String> {
        let group = match terminal::EditorGroup::new(&child) {
            Ok(group) => group,
            Err(error) => {
                let _ = child.kill();
                reap_command(&mut child);
                return Err(format!("cannot isolate the editor: {error}"));
            }
        };
        Ok(Self {
            child,
            group,
            reaped: false,
            cleanup_attempted: false,
        })
    }

    fn poll(&mut self) -> std::io::Result<Option<std::process::ExitStatus>> {
        let result = self.child.try_wait()?;
        self.reaped |= result.is_some();
        Ok(result)
    }
}

impl Drop for EditorChild {
    fn drop(&mut self) {
        self.group.signal(true);
        if !self.reaped && !self.cleanup_attempted {
            let _ = self.child.kill();
            reap_command(&mut self.child);
        }
    }
}

fn editor_status(status: std::process::ExitStatus) -> Result<(), String> {
    if status.success() {
        Ok(())
    } else {
        Err(format!("editor exited with {status}"))
    }
}

fn wait_editor(
    child: &mut EditorChild,
    stopped: &AtomicBool,
    session: Option<&terminal::EditorSession<'_>>,
) -> Result<(), String> {
    loop {
        if stopped.load(Ordering::Relaxed) {
            cancel_editor(child);
            return Err("editor cancelled".into());
        }
        if terminal::editor_stopped(&child.child).map_err(|err| err.to_string())?
            && let Some(session) = session
        {
            session.suspend().map_err(|err| err.to_string())?;
            if !stopped.load(Ordering::Relaxed) {
                child.group.resume();
            }
            continue;
        }
        match child.poll() {
            Ok(Some(status)) => return editor_status(status),
            Ok(None) => std::thread::park_timeout(Duration::from_millis(20)),
            Err(err) => return Err(err.to_string()),
        }
    }
}

fn cancel_editor(child: &mut EditorChild) {
    child.group.signal(false);
    child.group.resume();
    let deadline = Instant::now() + Duration::from_millis(250);
    while Instant::now() < deadline {
        let _ = child.poll();
        if !child.group.alive() {
            break;
        }
        std::thread::park_timeout(Duration::from_millis(10));
    }
    child.group.signal(true);
    if !child.reaped {
        child.cleanup_attempted = true;
        reap_command(&mut child.child);
        let _ = child.poll();
    }
}

pub fn copy(text: &str, stopped: &AtomicBool) -> Result<(), String> {
    if text.len() > 64 * 1024 {
        return Err("clipboard text exceeds limit".into());
    }
    for (name, arguments) in [
        ("xclip", &["-selection", "clipboard"][..]),
        ("xsel", &["--clipboard", "--input"][..]),
        ("wl-copy", &[][..]),
        ("pbcopy", &[][..]),
    ] {
        if stopped.load(Ordering::Relaxed) {
            return Err("clipboard cancelled".into());
        }
        let Some(program) = executable(name) else {
            continue;
        };
        let mut input = tempfile::tempfile().map_err(|err| err.to_string())?;
        input
            .write_all(text.as_bytes())
            .map_err(|err| err.to_string())?;
        use std::io::{Seek, SeekFrom};
        input
            .seek(SeekFrom::Start(0))
            .map_err(|err| err.to_string())?;
        let mut command = Command::new(program);
        command
            .args(arguments)
            .stdin(Stdio::from(input))
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
        let Ok(mut child) = command.spawn() else {
            continue;
        };
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            if stopped.load(Ordering::Relaxed) {
                stop_command(&mut child);
                return Err("clipboard cancelled".into());
            }
            match child.try_wait() {
                Ok(Some(status)) if status.success() => return Ok(()),
                Ok(Some(_)) => break,
                Err(_) => {
                    stop_command(&mut child);
                    break;
                }
                Ok(None) if Instant::now() < deadline => {
                    std::thread::park_timeout(Duration::from_millis(10))
                }
                Ok(None) => {
                    stop_command(&mut child);
                    break;
                }
            }
        }
    }
    Err(text.to_owned())
}

fn stop_command(child: &mut Child) {
    unsafe {
        libc::kill(-(child.id() as i32), libc::SIGKILL);
    }
    let _ = child.kill();
    reap_command(child);
}

fn reap_command(child: &mut Child) {
    let deadline = Instant::now() + Duration::from_secs(2);
    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) | Err(_) => break,
            Ok(None) => std::thread::park_timeout(Duration::from_millis(10)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn tail_preserves_absolute_lines_and_final_unterminated_line() {
        let (lines, first, total) =
            tail_reader(Cursor::new(b"one\ntwo\nthree\nfour"), 2, || Ok(())).unwrap();
        assert_eq!(lines, ["three", "four"]);
        assert_eq!((first, total), (3, 4));
        let (lines, _, total) = tail_reader(Cursor::new(b"\n\n"), 2, || Ok(())).unwrap();
        assert_eq!(lines, ["", ""]);
        assert_eq!(total, 2);
    }

    #[test]
    fn pathological_lines_are_bounded_and_terminal_controls_removed() {
        let long = "x".repeat(MAX_LINE_BYTES * 2);
        let (lines, _, _) = tail_reader(Cursor::new(long), 1, || Ok(())).unwrap();
        assert!(lines[0].len() < MAX_LINE_BYTES + 64);
        assert!(lines[0].ends_with("[line truncated]"));
        assert_eq!(printable("\u{1b}[31mred\u{1b}[0m\ttext\r"), "red    text");
        assert_eq!(
            printable("\u{1b}]8;;https://example.com\u{1b}\\label\u{1b}]8;;\u{1b}\\ text"),
            "label text"
        );
    }

    #[test]
    fn cancelled_reads_stop_before_consuming_more_input() {
        let mut checks = 0;
        let result = tail_reader(Cursor::new(b"one\ntwo\nthree"), 3, || {
            checks += 1;
            if checks == 2 {
                Err("cancelled".into())
            } else {
                Ok(())
            }
        });
        assert_eq!(result.unwrap_err(), "cancelled");
        assert_eq!(checks, 2);
    }

    #[test]
    fn stopping_editor_wait_terminates_the_owned_child() {
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args(["--exact", "engine::io::tests::editor_process", "--ignored"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        terminal::configure_editor(&mut command);
        let mut child = EditorChild::new(command.spawn().unwrap()).unwrap();
        let stopped = AtomicBool::new(true);
        assert_eq!(
            wait_editor(&mut child, &stopped, None).unwrap_err(),
            "editor cancelled"
        );
        let status = child.poll().unwrap().expect("editor must be reaped");
        assert!(!status.success());
        assert!(child.reaped);
        drop(child);
    }

    #[test]
    fn stopping_editor_wrapper_closes_its_descendants_output() {
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                "engine::io::tests::editor_wrapper",
                "--ignored",
                "--nocapture",
            ])
            .env("STOEI_EDITOR_WRAPPER", "1")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        terminal::configure_editor(&mut command);
        let mut child = EditorChild::new(command.spawn().unwrap()).unwrap();
        let mut output = BufReader::new(child.child.stdout.take().unwrap());
        let mut line = String::new();
        for _ in 0..8 {
            line.clear();
            assert_ne!(output.read_line(&mut line).unwrap(), 0);
            if line.contains("editor descendant ready") {
                break;
            }
        }
        assert!(line.contains("editor descendant ready"));
        assert_eq!(
            wait_editor(&mut child, &AtomicBool::new(true), None).unwrap_err(),
            "editor cancelled"
        );
        drop(child);
        let mut remaining = Vec::new();
        output.read_to_end(&mut remaining).unwrap();
    }

    #[test]
    #[ignore]
    fn editor_wrapper() {
        if std::env::var_os("STOEI_EDITOR_WRAPPER").is_none() {
            return;
        }
        let mut child = Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "engine::io::tests::editor_process",
                "--ignored",
                "--nocapture",
            ])
            .env("STOEI_EDITOR_DESCENDANT", "1")
            .spawn()
            .unwrap();
        let _ = child.wait();
    }

    #[test]
    #[ignore]
    fn editor_process() {
        if std::env::var_os("STOEI_EDITOR_DESCENDANT").is_some() {
            println!("editor descendant ready");
            std::io::stdout().flush().unwrap();
        }
        loop {
            std::thread::park();
        }
    }
}
