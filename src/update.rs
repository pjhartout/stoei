use std::fs;
use std::io::{Read, Write};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use flate2::read::GzDecoder;
use serde::Deserialize;
use sha2::{Digest, Sha256};

use crate::paths;

mod http;

pub const HTTP_HELPER_COMMAND: &str = http::COMMAND;

const REPO: &str = "pjhartout/stoei";
const MAX_ARCHIVE: u64 = 256 * 1024 * 1024;
const CACHE_TTL: i64 = 24 * 60 * 60;
const MAX_CACHE_BYTES: u64 = 4096;

#[derive(Clone)]
pub struct ReleaseClient {
    pub api_base: String,
    pub download_base: String,
}

impl Default for ReleaseClient {
    fn default() -> Self {
        Self {
            api_base: "https://api.github.com".into(),
            download_base: "https://github.com".into(),
        }
    }
}

pub fn semver(version: &str) -> Option<[u64; 3]> {
    let mut parts = version.trim().trim_start_matches('v').split('.');
    let out = [
        parts.next()?.parse().ok()?,
        parts.next()?.parse().ok()?,
        parts.next()?.parse().ok()?,
    ];
    parts.next().is_none().then_some(out)
}

pub fn is_newer(current: &str, latest: &str) -> bool {
    match (semver(current), semver(latest)) {
        (Some(current), Some(latest)) => latest > current,
        _ => false,
    }
}

pub fn asset_name(tag: &str, os: &str, arch: &str) -> Result<String, String> {
    if semver(tag).is_none() {
        return Err("invalid release tag".into());
    }
    let os = match os {
        "macos" | "darwin" => "darwin",
        "linux" => "linux",
        _ => return Err(format!("unsupported OS: {os}")),
    };
    let arch = match arch {
        "x86_64" | "amd64" => "amd64",
        "aarch64" | "arm64" => "arm64",
        _ => return Err(format!("unsupported architecture: {arch}")),
    };
    Ok(format!(
        "stoei_{}_{os}_{arch}.tar.gz",
        tag.trim_start_matches('v')
    ))
}

pub fn run_http_helper(arguments: &[String], output: &mut impl Write) -> Result<(), String> {
    http::helper(arguments, output)
}

impl ReleaseClient {
    pub fn latest(&self) -> Result<String, String> {
        self.latest_with_cancel(&AtomicBool::new(false))
    }

    pub fn latest_with_cancel(&self, cancelled: &AtomicBool) -> Result<String, String> {
        let helper = std::env::current_exe().map_err(|err| err.to_string())?;
        self.latest_with_helper(&helper, cancelled)
    }

    /// Uses an explicit stoei executable so embedders can keep HTTP work in its helper process.
    pub fn latest_with_helper(
        &self,
        helper: &Path,
        cancelled: &AtomicBool,
    ) -> Result<String, String> {
        #[derive(Deserialize)]
        struct Release {
            tag_name: String,
        }
        let url = format!("{}/repos/{REPO}/releases/latest", self.api_base);
        let body = http::fetch(
            helper,
            &url,
            Duration::from_secs(10),
            1024 * 1024,
            cancelled,
        )?;
        let release: Release = serde_json::from_slice(&body).map_err(|err| err.to_string())?;
        if semver(&release.tag_name).is_none() {
            return Err("release lookup: invalid tag".into());
        }
        Ok(release.tag_name)
    }

    pub fn latest_cached(&self) -> Result<String, String> {
        self.latest_cached_with_cancel(&AtomicBool::new(false))
    }

    pub fn latest_cached_with_cancel(&self, cancelled: &AtomicBool) -> Result<String, String> {
        if cancelled.load(Ordering::Relaxed) {
            return Err("HTTP request cancelled".into());
        }
        let now = chrono::Utc::now().timestamp();
        let result = match paths::cache() {
            Ok(path) => cached_lookup(&path, now, || self.latest_with_cancel(cancelled)),
            Err(_) => self.latest_with_cancel(cancelled),
        };
        if cancelled.load(Ordering::Relaxed) {
            Err("HTTP request cancelled".into())
        } else {
            result
        }
    }

    pub fn apply(&self, tag: &str, destination: &Path) -> Result<(), String> {
        self.apply_with_cancel(tag, destination, &AtomicBool::new(false))
    }

    pub fn apply_with_cancel(
        &self,
        tag: &str,
        destination: &Path,
        cancelled: &AtomicBool,
    ) -> Result<(), String> {
        let helper = std::env::current_exe().map_err(|err| err.to_string())?;
        self.apply_with_helper(tag, destination, &helper, cancelled)
    }

    pub fn apply_with_helper(
        &self,
        tag: &str,
        destination: &Path,
        helper: &Path,
        cancelled: &AtomicBool,
    ) -> Result<(), String> {
        let name = asset_name(tag, std::env::consts::OS, std::env::consts::ARCH)?;
        let base = format!("{}/{REPO}/releases/download/{tag}/", self.download_base);
        let archive = http::fetch(
            helper,
            &(base.clone() + &name),
            Duration::from_secs(300),
            MAX_ARCHIVE,
            cancelled,
        )?;
        let checksums = http::fetch(
            helper,
            &(base + "checksums.txt"),
            Duration::from_secs(10),
            1024 * 1024,
            cancelled,
        )?;
        let want = checksum_for(&String::from_utf8_lossy(&checksums), &name)?;
        let got = format!("{:x}", Sha256::digest(&archive));
        if got != want {
            return Err(format!(
                "checksum mismatch for {name}: got {got} want {want}"
            ));
        }
        let binary = extract_binary(&archive)?;
        if cancelled.load(Ordering::Relaxed) {
            return Err("HTTP request cancelled".into());
        }
        replace_binary(destination, &binary)
    }
}

pub fn cached_lookup(
    path: &Path,
    now: i64,
    lookup: impl FnOnce() -> Result<String, String>,
) -> Result<String, String> {
    let mut raw = String::new();
    let read = fs::File::open(path)
        .and_then(|file| file.take(MAX_CACHE_BYTES + 1).read_to_string(&mut raw));
    if read.is_err() || raw.len() as u64 > MAX_CACHE_BYTES {
        raw.clear();
    }
    let mut fields = raw.split_whitespace();
    let cached = fields
        .next()
        .filter(|tag| semver(tag).is_some())
        .unwrap_or("");
    let timestamp = fields.next().and_then(|field| field.parse::<i64>().ok());
    let fresh = timestamp
        .is_some_and(|timestamp| timestamp <= now && now.saturating_sub(timestamp) < CACHE_TTL);
    if fresh && !cached.is_empty() {
        return Ok(cached.to_owned());
    }
    match lookup() {
        Ok(tag) => {
            if let Some(parent) = path.parent() {
                let _ = fs::create_dir_all(parent);
            }
            let _ = fs::write(path, format!("{tag} {now}\n"));
            Ok(tag)
        }
        Err(_) if !cached.is_empty() => Ok(cached.to_owned()),
        Err(err) => Err(err),
    }
}

pub fn checksum_for(checksums: &str, name: &str) -> Result<String, String> {
    for line in checksums.lines() {
        let fields: Vec<_> = line.split_whitespace().take(3).collect();
        if fields.len() == 2 && fields[1] == name {
            let digest = fields[0];
            if digest.len() == 64 && digest.bytes().all(|byte| byte.is_ascii_hexdigit()) {
                return Ok(digest.to_ascii_lowercase());
            }
            return Err(format!("invalid checksum for {name}"));
        }
    }
    Err(format!("no checksum for {name}"))
}

pub fn extract_binary(archive: &[u8]) -> Result<Vec<u8>, String> {
    let mut archive = tar::Archive::new(GzDecoder::new(archive));
    for entry in archive.entries().map_err(|err| err.to_string())?.take(1024) {
        let mut entry = entry.map_err(|err| err.to_string())?;
        if !entry.header().entry_type().is_file() {
            continue;
        }
        let path = entry.path().map_err(|err| err.to_string())?;
        if path.file_name().is_some_and(|name| name == "stoei") {
            if entry.size() > MAX_ARCHIVE {
                return Err("binary exceeds size limit".into());
            }
            let mut binary = Vec::new();
            entry
                .by_ref()
                .take(MAX_ARCHIVE + 1)
                .read_to_end(&mut binary)
                .map_err(|err| err.to_string())?;
            if binary.is_empty() || binary.len() as u64 > MAX_ARCHIVE {
                return Err("invalid binary size".into());
            }
            return Ok(binary);
        }
    }
    Err("stoei binary not found in archive".into())
}

pub fn replace_binary(destination: &Path, binary: &[u8]) -> Result<(), String> {
    let parent = destination.parent().ok_or("binary path has no parent")?;
    let mut temporary = tempfile::NamedTempFile::new_in(parent).map_err(|err| err.to_string())?;
    temporary.write_all(binary).map_err(|err| err.to_string())?;
    {
        use std::os::unix::fs::PermissionsExt;
        temporary
            .as_file()
            .set_permissions(fs::Permissions::from_mode(0o755))
            .map_err(|err| err.to_string())?;
    }
    temporary
        .as_file()
        .sync_all()
        .map_err(|err| err.to_string())?;
    temporary
        .persist(destination)
        .map_err(|err| err.to_string())?;
    Ok(())
}

pub fn run(current: &str, output: &mut impl Write) -> Result<(), String> {
    run_with_cancel(current, output, &AtomicBool::new(false))
}

pub fn run_with_cancel(
    current: &str,
    output: &mut impl Write,
    cancelled: &AtomicBool,
) -> Result<(), String> {
    let client = ReleaseClient::default();
    let latest = client.latest_with_cancel(cancelled)?;
    writeln!(output, "current {current} → latest {latest}").map_err(|err| err.to_string())?;
    if semver(current).is_some() && !is_newer(current, &latest) {
        writeln!(output, "already up to date").map_err(|err| err.to_string())?;
        return Ok(());
    }
    let executable = std::env::current_exe()
        .and_then(fs::canonicalize)
        .map_err(|err| err.to_string())?;
    client.apply_with_cancel(&latest, &executable, cancelled)?;
    writeln!(output, "updated {} ✓ checksum", executable.display()).map_err(|err| err.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_and_assets_remain_compatible() {
        assert!(is_newer("0.9.0", "v0.10.0"));
        assert!(!is_newer("dev", "v1.0.0"));
        assert!(!is_newer("1.0.0", "v1.0.0"));
        assert_eq!(
            asset_name("v1.2.3", "linux", "x86_64").unwrap(),
            "stoei_1.2.3_linux_amd64.tar.gz"
        );
        assert_eq!(
            asset_name("v1.2.3", "macos", "aarch64").unwrap(),
            "stoei_1.2.3_darwin_arm64.tar.gz"
        );
        assert!(asset_name("../latest", "linux", "x86_64").is_err());
        assert!(asset_name("v1.2.3", "windows", "x86_64").is_err());
    }

    #[test]
    fn cancelled_release_checks_skip_helpers_and_cache_fallback() {
        let client = ReleaseClient {
            api_base: "http://127.0.0.1:1".into(),
            download_base: "http://127.0.0.1:1".into(),
        };
        let cancelled = AtomicBool::new(true);
        assert_eq!(
            client.latest_with_cancel(&cancelled),
            Err("HTTP request cancelled".into())
        );
        assert_eq!(
            client.latest_cached_with_cancel(&cancelled),
            Err("HTTP request cancelled".into())
        );
    }

    #[test]
    fn fresh_and_stale_caches_control_network_calls() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("latest-release");
        fs::write(&path, "v1.2.3 1000\n").unwrap();
        assert_eq!(
            cached_lookup(&path, 1001, || panic!("fresh cache must skip network")).unwrap(),
            "v1.2.3"
        );
        assert_eq!(
            cached_lookup(&path, 1000 + CACHE_TTL, || Err("offline".into())).unwrap(),
            "v1.2.3"
        );
        assert_eq!(
            cached_lookup(&path, 1000 + CACHE_TTL, || Ok("v1.2.4".into())).unwrap(),
            "v1.2.4"
        );
        fs::write(&path, format!("v1.2.3 {}\n", i64::MIN)).unwrap();
        assert_eq!(
            cached_lookup(&path, 1001, || Ok("v1.2.4".into())).unwrap(),
            "v1.2.4"
        );
        fs::write(&path, "x".repeat(MAX_CACHE_BYTES as usize + 1)).unwrap();
        assert_eq!(
            cached_lookup(&path, 1001, || Ok("v1.2.4".into())).unwrap(),
            "v1.2.4"
        );
    }

    #[test]
    fn checksum_and_archive_validation_precede_replacement() {
        let checksum = "a".repeat(64);
        assert_eq!(
            checksum_for(&format!("{checksum}  exact.tar.gz\n"), "exact.tar.gz").unwrap(),
            checksum
        );
        assert!(checksum_for("bad exact.tar.gz", "exact.tar.gz").is_err());
        assert!(extract_binary(b"not gzip").is_err());
        let mut archive = tar::Builder::new(Vec::new());
        let mut header = tar::Header::new_gnu();
        header.set_size(3);
        header.set_mode(0o755);
        header.set_cksum();
        archive
            .append_data(&mut header, "stoei", &b"exe"[..])
            .unwrap();
        let tar = archive.into_inner().unwrap();
        let mut gzip = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
        gzip.write_all(&tar).unwrap();
        assert_eq!(extract_binary(&gzip.finish().unwrap()).unwrap(), b"exe");
    }
}
