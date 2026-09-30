use std::{
    sync::{Arc, atomic::AtomicBool},
    time::Duration,
};

use stoei::slurm::*;

#[test]
fn shutdown_and_deadline_causes_are_explicit() {
    let runner = ExecRunner::new(Arc::new(AtomicBool::new(true)));
    let error = runner
        .run("never-executed", &[], Duration::from_secs(1))
        .unwrap_err();
    assert_eq!(error.cause, CommandErrorCause::Cancelled);
    let error = ExecRunner::default()
        .run("never-executed", &[], Duration::ZERO)
        .unwrap_err();
    assert_eq!(error.cause, CommandErrorCause::TimedOut);
    assert!(!error.to_string().contains("signal"));
}

#[test]
fn hard_failure_stderr_is_detected_even_on_zero_exit() {
    let executable = std::env::current_exe().unwrap();
    let args = [
        "--ignored",
        "--exact",
        "subprocess_stderr_fixture",
        "--nocapture",
    ]
    .map(String::from);
    let error = ExecRunner::default()
        .run(executable.to_str().unwrap(), &args, Duration::from_secs(5))
        .unwrap_err();
    assert_eq!(error.cause, CommandErrorCause::HardFailure);
    assert!(error.stderr.contains("CONNECTION REFUSED"));
}

#[test]
fn command_output_and_nonzero_exits_are_distinct() {
    let executable = std::env::current_exe().unwrap();
    let args = [
        "--ignored",
        "--exact",
        "subprocess_output_fixture",
        "--nocapture",
    ]
    .map(String::from);
    let output = ExecRunner::default()
        .run(executable.to_str().unwrap(), &args, Duration::from_secs(5))
        .unwrap();
    assert!(output.contains("output fixture"));
    let args = [
        "--ignored",
        "--exact",
        "subprocess_failure_fixture",
        "--nocapture",
    ]
    .map(String::from);
    let error = ExecRunner::default()
        .run(executable.to_str().unwrap(), &args, Duration::from_secs(5))
        .unwrap_err();
    assert!(matches!(error.cause, CommandErrorCause::Exit(Some(_))));
}

#[test]
fn killed_command_preserves_the_deadline_cause() {
    let executable = std::env::current_exe().unwrap();
    let args = [
        "--ignored",
        "--exact",
        "subprocess_blocked_fixture",
        "--nocapture",
    ]
    .map(String::from);
    let error = ExecRunner::default()
        .run(
            executable.to_str().unwrap(),
            &args,
            Duration::from_millis(1),
        )
        .unwrap_err();
    assert_eq!(error.cause, CommandErrorCause::TimedOut);
    assert!(!error.to_string().contains("signal"));
}

#[test]
#[ignore]
fn subprocess_blocked_fixture() {
    std::thread::park();
}

#[test]
#[ignore]
fn subprocess_stderr_fixture() {
    eprintln!("slurmdbd: CONNECTION REFUSED");
}

#[test]
#[ignore]
fn subprocess_output_fixture() {
    println!("output fixture");
}

#[test]
#[ignore]
fn subprocess_failure_fixture() {
    std::process::exit(7);
}
