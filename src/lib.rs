#[cfg(not(target_os = "linux"))]
compile_error!("stoei supports Linux only");

pub mod config;
pub mod engine;
pub mod log;
pub mod paths;
pub mod slurm;
pub mod store;
mod temp_file;
pub mod ui;
pub mod update;

pub const VERSION: &str = match option_env!("STOEI_VERSION") {
    Some(version) => version,
    None => "dev",
};
