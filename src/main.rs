use std::fs::{self, OpenOptions};
use std::path::Path;
use std::sync::{Arc, atomic::AtomicBool};

use stoei::{VERSION, config, engine, paths, update};

fn usage() -> &'static str {
    "stoei — a terminal UI for monitoring Slurm jobs\n\nUsage:\n  stoei            launch the TUI\n  stoei update     replace this binary with the latest release\n  stoei reset      clear the persistent job journal\n  stoei version    print the version"
}

fn reset(path: &Path) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }
    let lock_path = path.with_file_name(format!(
        "{}.lock",
        path.file_name()
            .ok_or("invalid journal path")?
            .to_string_lossy()
    ));
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(lock_path)
        .map_err(|err| err.to_string())?;
    lock.lock().map_err(|err| err.to_string())?;
    for path in [
        path.to_path_buf(),
        path.with_file_name("sacct-reconcile.stamp"),
    ] {
        match fs::remove_file(path) {
            Ok(()) => {}
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
            Err(err) => return Err(err.to_string()),
        }
    }
    Ok(())
}

fn start() -> Result<(), String> {
    let config_path = paths::config()?;
    let (config, error) = match config::load_file(&config_path) {
        Ok(config) => (config, None),
        Err(error) => (config::Config::default(), Some(error)),
    };
    engine::run(config, config_path, paths::journal()?, error)
}

struct UpdateSignals(Vec<signal_hook::SigId>);

impl Drop for UpdateSignals {
    fn drop(&mut self) {
        for signal in self.0.drain(..) {
            signal_hook::low_level::unregister(signal);
        }
    }
}

fn update_command() -> Result<(), String> {
    let cancelled = Arc::new(AtomicBool::new(false));
    let _signals = {
        use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM};
        let mut signals = UpdateSignals(Vec::with_capacity(3));
        for signal in [SIGINT, SIGTERM, SIGHUP] {
            signals.0.push(
                signal_hook::flag::register(signal, Arc::clone(&cancelled))
                    .map_err(|err| err.to_string())?,
            );
        }
        signals
    };
    update::run_with_cancel(VERSION, &mut std::io::stdout(), &cancelled)
}

fn main() -> std::process::ExitCode {
    let result = match std::env::args().nth(1).as_deref() {
        Some(update::HTTP_HELPER_COMMAND) => update::run_http_helper(
            &std::env::args().skip(2).collect::<Vec<_>>(),
            &mut std::io::stdout(),
        ),
        Some("--version" | "-v" | "version") => {
            println!("stoei {VERSION}");
            Ok(())
        }
        Some("--help" | "-h" | "help") => {
            println!("{}", usage());
            Ok(())
        }
        Some("reset") => paths::journal()
            .and_then(|path| reset(&path))
            .map(|()| println!("stoei: cleared the job journal")),
        Some("update") => update_command(),
        Some(command) => {
            eprintln!("stoei: unknown command {command:?}\n\n{}", usage());
            return std::process::ExitCode::from(2);
        }
        None => start(),
    };
    match result {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(err) => {
            eprintln!("stoei: {err}");
            std::process::ExitCode::FAILURE
        }
    }
}
