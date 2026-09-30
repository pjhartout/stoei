use std::env;
use std::ffi::OsString;
use std::path::PathBuf;

fn nonempty(name: &str) -> Option<OsString> {
    env::var_os(name).filter(|value| !value.is_empty())
}

fn home() -> Result<PathBuf, String> {
    nonempty("HOME")
        .map(PathBuf::from)
        .ok_or_else(|| "cannot resolve home directory".to_owned())
}

pub fn config() -> Result<PathBuf, String> {
    if let Some(path) = nonempty("STOEI_CONFIG_DIR") {
        return Ok(PathBuf::from(path).join("config.yaml"));
    }
    let base = match nonempty("XDG_CONFIG_HOME") {
        Some(path) => PathBuf::from(path),
        None => home()?.join(".config"),
    };
    Ok(base.join("stoei/config.yaml"))
}

pub fn journal() -> Result<PathBuf, String> {
    let base = match nonempty("XDG_DATA_HOME") {
        Some(path) => PathBuf::from(path),
        None => home()?.join(".local/share"),
    };
    Ok(base.join("stoei/jobs.jsonl"))
}

pub fn cache() -> Result<PathBuf, String> {
    let base = if cfg!(target_os = "macos") {
        home()?.join("Library/Caches")
    } else {
        match nonempty("XDG_CACHE_HOME") {
            Some(path) => PathBuf::from(path),
            None => home()?.join(".cache"),
        }
    };
    Ok(base.join("stoei/latest-release"))
}
