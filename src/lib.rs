#[cfg(not(any(target_os = "linux", target_os = "macos")))]
compile_error!("stoei supports Linux and macOS only");

pub mod config;
pub mod engine;
pub mod log;
pub mod paths;
pub mod slurm;
pub mod store;
pub mod ui;
pub mod update;

pub const VERSION: &str = match option_env!("STOEI_VERSION") {
    Some(version) => version,
    None => "dev",
};
