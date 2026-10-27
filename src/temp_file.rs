use std::fs::File;
use std::io;
use std::path::Path;

pub(crate) fn create() -> io::Result<File> {
    create_in(&std::env::temp_dir(), Path::new("/tmp"))
}

fn create_in(preferred: &Path, fallback: &Path) -> io::Result<File> {
    tempfile::tempfile_in(preferred)
        .map_err(|error| {
            io::Error::new(
                error.kind(),
                format!(
                    "cannot create temporary file in {}: {error}",
                    preferred.display()
                ),
            )
        })
        .or_else(|preferred_error| {
            if preferred == fallback {
                return Err(preferred_error);
            }
            tempfile::tempfile_in(fallback).map_err(|error| {
                io::Error::new(
                    error.kind(),
                    format!(
                        "{preferred_error}; cannot create temporary file in {}: {error}",
                        fallback.display()
                    ),
                )
            })
        })
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::io::{Read, Seek, SeekFrom, Write};

    use super::*;

    #[test]
    fn working_preferred_directory_does_not_need_a_fallback() {
        let directory = tempfile::tempdir().unwrap();
        let fallback = directory.path().join("unused-fallback");
        let mut file = create_in(directory.path(), &fallback).unwrap();
        file.write_all(b"captured output").unwrap();
        file.seek(SeekFrom::Start(0)).unwrap();
        let mut output = String::new();
        file.read_to_string(&mut output).unwrap();
        assert_eq!(output, "captured output");
        assert!(!fallback.exists());
    }

    #[test]
    fn missing_preferred_directory_uses_fallback() {
        let directory = tempfile::tempdir().unwrap();
        let preferred = directory.path().join("missing");
        create_in(&preferred, directory.path()).unwrap();
        assert!(!preferred.exists());
    }

    #[test]
    fn non_directory_preferred_path_uses_fallback() {
        let directory = tempfile::tempdir().unwrap();
        let preferred = directory.path().join("file");
        fs::write(&preferred, b"existing content").unwrap();
        create_in(&preferred, directory.path()).unwrap();
        assert_eq!(fs::read(&preferred).unwrap(), b"existing content");
    }

    #[test]
    fn failure_reports_both_paths_and_causes() {
        let directory = tempfile::tempdir().unwrap();
        let preferred = directory.path().join("missing");
        let fallback = directory.path().join("file");
        fs::write(&fallback, b"existing content").unwrap();
        let preferred_error = tempfile::tempfile_in(&preferred).unwrap_err();
        let fallback_error = tempfile::tempfile_in(&fallback).unwrap_err();
        let error = create_in(&preferred, &fallback).unwrap_err();
        assert_eq!(error.kind(), fallback_error.kind());
        let message = error.to_string();
        assert!(
            message.contains(&preferred.display().to_string()),
            "{message}"
        );
        assert!(message.contains(&preferred_error.to_string()), "{message}");
        assert!(
            message.contains(&fallback.display().to_string()),
            "{message}"
        );
        assert!(message.contains(&fallback_error.to_string()), "{message}");
        assert!(!preferred.exists());
    }

    #[test]
    fn identical_paths_report_only_one_attempt() {
        let directory = tempfile::tempdir().unwrap();
        let missing = directory.path().join("missing");
        let error = create_in(&missing, &missing).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::NotFound);
        assert_eq!(
            error.to_string().matches(missing.to_str().unwrap()).count(),
            1
        );
    }
}
