use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::Path;

use serde::{Deserialize, Serialize};

pub const THEMES: [&str; 14] = [
    "oc-1",
    "tokyonight",
    "dracula",
    "monokai",
    "solarized",
    "nord",
    "catppuccin",
    "ayu",
    "onedarkpro",
    "shadesofpurple",
    "nightowl",
    "vesper",
    "gruvbox",
    "charm",
];

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Config {
    pub theme: String,
    pub refresh_interval: f64,
    pub job_history_days: u32,
    pub log_viewer_lines: usize,
    pub keybind_mode: String,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            theme: "nord".into(),
            refresh_interval: 120.0,
            job_history_days: 7,
            log_viewer_lines: 10_000,
            keybind_mode: "vim".into(),
        }
    }
}

#[derive(Default, Deserialize)]
#[serde(default)]
struct RawConfig {
    theme: String,
    refresh_interval: f64,
    job_history_days: i64,
    log_viewer_lines: i64,
    keybind_mode: String,
}

impl Config {
    pub fn clamped(mut self) -> Self {
        let defaults = Self::default();
        if !THEMES.contains(&self.theme.as_str()) {
            self.theme = defaults.theme;
        }
        if !self.refresh_interval.is_finite() || !(120.0..=300.0).contains(&self.refresh_interval) {
            self.refresh_interval = defaults.refresh_interval;
        }
        if !(1..=90).contains(&self.job_history_days) {
            self.job_history_days = defaults.job_history_days;
        }
        if !(500..=100_000).contains(&self.log_viewer_lines) {
            self.log_viewer_lines = defaults.log_viewer_lines;
        }
        if self.keybind_mode != "vim" && self.keybind_mode != "emacs" {
            self.keybind_mode = defaults.keybind_mode;
        }
        self
    }
}

pub fn load(data: &str) -> Result<Config, String> {
    if data.trim().is_empty() {
        return Ok(Config::default());
    }
    if data.len() > 64 * 1024 {
        return Err("config exceeds 64 KiB".into());
    }
    let raw: RawConfig = serde_saphyr::from_str(data).map_err(|err| err.to_string())?;
    Ok(Config {
        theme: raw.theme,
        refresh_interval: raw.refresh_interval,
        job_history_days: u32::try_from(raw.job_history_days).unwrap_or(0),
        log_viewer_lines: usize::try_from(raw.log_viewer_lines).unwrap_or(0),
        keybind_mode: raw.keybind_mode,
    }
    .clamped())
}

pub fn load_file(path: &Path) -> Result<Config, String> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(Config::default()),
        Err(err) => return Err(err.to_string()),
    };
    let mut data = String::new();
    file.take(64 * 1024 + 1)
        .read_to_string(&mut data)
        .map_err(|err| err.to_string())?;
    load(&data)
}

pub fn save(path: &Path, config: &Config) -> Result<(), String> {
    let config = config.clone().clamped();
    let data = format!(
        "theme: {}\nrefresh_interval: {}\njob_history_days: {}\nlog_viewer_lines: {}\nkeybind_mode: {}\n",
        config.theme,
        config.refresh_interval,
        config.job_history_days,
        config.log_viewer_lines,
        config.keybind_mode,
    );
    let parent = path.parent().ok_or("config path has no parent")?;
    fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    let mut temporary = tempfile::NamedTempFile::new_in(parent).map_err(|err| err.to_string())?;
    temporary
        .write_all(data.as_bytes())
        .map_err(|err| err.to_string())?;
    temporary
        .as_file()
        .sync_all()
        .map_err(|err| err.to_string())?;
    temporary.persist(path).map_err(|err| err.to_string())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn existing_yaml_round_trips() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("stoei/config.yaml");
        let config = load("theme: gruvbox\nrefresh_interval: 150.5\njob_history_days: 20\nlog_viewer_lines: 500\nkeybind_mode: emacs").unwrap();
        save(&path, &config).unwrap();
        assert_eq!(load_file(&path).unwrap(), config);
        assert_eq!(config.refresh_interval, 150.5);
    }

    #[test]
    fn invalid_fields_fall_back_independently() {
        let config = load(
            "theme: missing\nrefresh_interval: .nan\njob_history_days: -1\nlog_viewer_lines: 4\nkeybind_mode: wrong",
        );
        assert!(config.is_err() || config.unwrap() == Config::default());
        assert_eq!(
            load("theme: dracula\njob_history_days: 91").unwrap().theme,
            "dracula"
        );
        assert_eq!(
            load("theme: dracula\njob_history_days: 91")
                .unwrap()
                .job_history_days,
            7
        );
        assert!(load("theme: [").is_err());
        assert_eq!(load("").unwrap(), Config::default());
    }

    #[test]
    fn missing_file_is_normal_and_failed_save_preserves_content() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(
            load_file(&dir.path().join("missing")).unwrap(),
            Config::default()
        );
        let path = dir.path().join("existing");
        fs::create_dir(&path).unwrap();
        fs::write(path.join("retained"), "ok").unwrap();
        assert!(save(&path, &Config::default()).is_err());
        assert_eq!(fs::read_to_string(path.join("retained")).unwrap(), "ok");
    }
}
