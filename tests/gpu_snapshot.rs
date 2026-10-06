use std::{
    collections::BTreeMap,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::Duration,
};

use stoei::slurm::{Client, CommandError, CommandErrorCause, Runner};

type Call = (String, Vec<String>, Duration);

struct SnapshotRunner {
    allocation: String,
    next_allocation: Option<String>,
    nodes: String,
    responses: BTreeMap<String, Result<String, CommandError>>,
    calls: Mutex<Vec<Call>>,
}

impl SnapshotRunner {
    fn standard() -> Self {
        Self {
            allocation: include_str!("fixtures/gpu_snapshot_allocation.txt").into(),
            next_allocation: None,
            nodes: include_str!("fixtures/gpu_snapshot_nodes.txt").into(),
            responses: BTreeMap::from([
                (
                    "gpu01".into(),
                    Ok(include_str!("fixtures/gpu_snapshot_nvidia.csv").into()),
                ),
                (
                    "gpu02".into(),
                    Ok("0, 3, NVIDIA H100 PCIe, GPU-second, N/A, 81559, N/A, Disabled\n".into()),
                ),
            ]),
            calls: Mutex::new(Vec::new()),
        }
    }

    fn ssh_count(&self) -> usize {
        self.calls
            .lock()
            .unwrap()
            .iter()
            .filter(|call| call.0 == "ssh")
            .count()
    }
}

impl Runner for SnapshotRunner {
    fn run(&self, name: &str, args: &[String], timeout: Duration) -> Result<String, CommandError> {
        let mut calls = self.calls.lock().unwrap();
        let repeat = calls
            .iter()
            .any(|call| call.0 == "scontrol" && call.1.get(2).map(String::as_str) == Some("job"));
        calls.push((name.into(), args.to_vec(), timeout));
        match name {
            "scontrol" if args == ["--details", "show", "job", "123_7"] => Ok(if repeat {
                self.next_allocation.as_ref().unwrap_or(&self.allocation)
            } else {
                &self.allocation
            }
            .clone()),
            "scontrol"
                if args.first().map(String::as_str) == Some("show")
                    && args.get(1).map(String::as_str) == Some("node") =>
            {
                Ok(self.nodes.clone())
            }
            "ssh" => {
                let host = args
                    .iter()
                    .position(|arg| arg == "--")
                    .map(|index| &args[index + 1])
                    .unwrap();
                self.responses
                    .get(host)
                    .expect("fake GPU node response")
                    .clone()
            }
            _ => panic!("Unexpected command in GPU snapshot fake: {name} {args:?}"),
        }
    }
}

fn client(runner: Arc<SnapshotRunner>) -> Client {
    Client::new(runner, "alice".into(), PathBuf::new())
}

#[test]
fn snapshots_filter_allocated_devices_and_map_gres_order_by_minor_number() {
    let runner = Arc::new(SnapshotRunner::standard());
    let snapshot = client(runner.clone()).job_gpu_snapshot("123_7").unwrap();
    assert!(snapshot.warnings.is_empty());
    assert_eq!(snapshot.devices.len(), 2);
    let first = &snapshot.devices[0];
    assert_eq!(first.node, "gpu01");
    assert_eq!(first.index, 0);
    assert_eq!(first.uuid, "GPU-allocated");
    assert_eq!(first.memory_used_bytes, Some(14382 << 20));
    assert_eq!(first.memory_total_bytes, Some(81559 << 20));
    assert_eq!(first.utilization_percent, Some(74.0));
    assert_eq!(snapshot.devices[1].memory_used_bytes, None);
    assert_eq!(snapshot.devices[1].utilization_percent, None);
    assert!(
        snapshot
            .devices
            .iter()
            .all(|device| device.uuid != "GPU-other-job")
    );
    let calls = runner.calls.lock().unwrap();
    assert_eq!(calls.iter().filter(|call| call.0 == "scontrol").count(), 3);
    assert_eq!(calls[1].1, ["show", "node", "gpu01,gpu02"]);
    for (name, args, timeout) in calls.iter().filter(|call| call.0 == "ssh") {
        assert_eq!(name, "ssh");
        assert!(args.contains(&"-T".into()));
        for option in [
            "BatchMode=yes",
            "ConnectTimeout=5",
            "ConnectionAttempts=1",
            "ClearAllForwardings=yes",
            "RequestTTY=no",
            "StrictHostKeyChecking=yes",
            "ControlMaster=no",
            "ControlPath=none",
            "ControlPersist=no",
            "ForwardAgent=no",
            "ForwardX11=no",
            "PermitLocalCommand=no",
            "RemoteCommand=none",
        ] {
            assert!(args.contains(&option.into()));
        }
        assert_eq!(
            args.last().unwrap(),
            "nvidia-smi --query-gpu=index,minor_number,name,uuid,memory.used,memory.total,utilization.gpu,mig.mode.current --format=csv,noheader,nounits"
        );
        assert_eq!(*timeout, Duration::from_secs(7));
    }
}

#[test]
fn a_failed_node_keeps_successful_device_readings() {
    let mut runner = SnapshotRunner::standard();
    runner.responses.insert(
        "gpu02".into(),
        Err(CommandError::new("ssh", CommandErrorCause::TimedOut, "")),
    );
    let snapshot = client(Arc::new(runner)).job_gpu_snapshot("123_7").unwrap();
    assert_eq!(snapshot.devices.len(), 1);
    assert_eq!(snapshot.warnings.len(), 1);
    assert!(snapshot.warnings[0].contains("gpu02: ssh: command timed out"));
}

#[test]
fn unsafe_or_ambiguous_job_ids_never_run_commands() {
    for id in ["--bad", "123;echo x", "123_[1-2]", "123_7_8", ""] {
        let runner = Arc::new(SnapshotRunner::standard());
        assert!(client(runner.clone()).job_gpu_snapshot(id).is_err());
        assert!(runner.calls.lock().unwrap().is_empty());
    }
}

#[test]
fn foreign_pending_and_finished_jobs_are_rejected_before_ssh() {
    for (from, to) in [
        ("alice(1000)", "bob(2000)"),
        ("JobState=RUNNING", "JobState=PENDING"),
        ("JobState=RUNNING", "JobState=COMPLETED"),
    ] {
        let mut runner = SnapshotRunner::standard();
        runner.allocation = runner.allocation.replace(from, to);
        let runner = Arc::new(runner);
        assert!(client(runner.clone()).job_gpu_snapshot("123_7").is_err());
        assert_eq!(runner.ssh_count(), 0);
        assert_eq!(runner.calls.lock().unwrap().len(), 1);
    }
}

#[test]
fn changed_allocation_or_state_discards_probe_results() {
    for (from, to) in [
        ("IDX:1", "IDX:0"),
        ("JobState=RUNNING", "JobState=COMPLETED"),
        (
            "StartTime=2026-10-06T12:00:00",
            "StartTime=2026-10-06T13:00:00",
        ),
    ] {
        let mut runner = SnapshotRunner::standard();
        runner.next_allocation = Some(runner.allocation.replace(from, to));
        let runner = Arc::new(runner);
        assert!(client(runner.clone()).job_gpu_snapshot("123_7").is_err());
        assert_eq!(runner.ssh_count(), 2);
    }
}

#[test]
fn mig_modes_and_profiles_never_report_physical_parent_metrics() {
    let mut runner = SnapshotRunner::standard();
    runner.responses.insert(
        "gpu01".into(),
        Ok(include_str!("fixtures/gpu_snapshot_nvidia.csv").replace("Disabled", "Enabled")),
    );
    let snapshot = client(Arc::new(runner)).job_gpu_snapshot("123_7").unwrap();
    assert_eq!(snapshot.devices.len(), 1);
    assert_eq!(snapshot.devices[0].node, "gpu02");
    assert!(snapshot.warnings[0].contains("MIG"));
    let mut runner = SnapshotRunner::standard();
    runner.allocation = runner
        .allocation
        .replace("gpu:h100:1", "gpu:h100_1g.10gb:1");
    let runner = Arc::new(runner);
    let snapshot = client(runner.clone()).job_gpu_snapshot("123_7").unwrap();
    assert!(snapshot.devices.is_empty());
    assert_eq!(snapshot.warnings.len(), 2);
    assert_eq!(runner.ssh_count(), 0);
}

#[test]
fn incomplete_duplicate_or_mismatched_inventories_fail_closed_per_node() {
    for response in [
        "0, 1, NVIDIA H100 PCIe, GPU-one, 1, 80000, 50, Disabled\n",
        "0, 1, NVIDIA H100 PCIe, GPU-one, 1, 80000, 50, Disabled\n1, 1, NVIDIA H100 PCIe, GPU-two, 1, 80000, 50, Disabled\n",
        "0, 0, NVIDIA A100 PCIe, GPU-one, 1, 80000, 50, Disabled\n1, 1, NVIDIA A100 PCIe, GPU-two, 1, 80000, 50, Disabled\n",
        "corrupt inventory",
    ] {
        let mut runner = SnapshotRunner::standard();
        runner.responses.insert("gpu01".into(), Ok(response.into()));
        let snapshot = client(Arc::new(runner)).job_gpu_snapshot("123_7").unwrap();
        assert_eq!(snapshot.devices.len(), 1);
        assert_eq!(snapshot.devices[0].node, "gpu02");
        assert_eq!(snapshot.warnings.len(), 1);
    }
}

#[test]
fn allocation_limits_and_host_validation_stop_before_ssh() {
    for (from, to) in [
        ("gpu[01-02]", "gpu[01-17]"),
        ("gpu[01-02]", "-oProxyCommand=bad"),
        ("gpu[01-02]", "gpu01,gpu02,"),
        ("Nodes=gpu01", "Nodes=unallocated"),
        ("IDX:1", "IDX:1-256"),
        ("IDX:1", "IDX:1,1"),
        ("gpu:h100:1(IDX:1)", "gpu:h100:1"),
        ("gres/gpu=2", "gres/gpu=3"),
    ] {
        let mut runner = SnapshotRunner::standard();
        runner.allocation = runner.allocation.replace(from, to);
        let runner = Arc::new(runner);
        assert!(client(runner.clone()).job_gpu_snapshot("123_7").is_err());
        assert_eq!(runner.ssh_count(), 0);
    }
}

#[test]
fn missing_per_node_allocations_do_not_silently_hide_gpus() {
    let mut runner = SnapshotRunner::standard();
    runner.allocation = runner
        .allocation
        .lines()
        .filter(|line| !line.trim_start().starts_with("Nodes=gpu02"))
        .collect::<Vec<_>>()
        .join("\n");
    let runner = Arc::new(runner);
    assert!(client(runner.clone()).job_gpu_snapshot("123_7").is_err());
    assert_eq!(runner.ssh_count(), 0);
}

#[test]
fn model_names_allow_slurm_space_and_hyphen_normalization() {
    let mut runner = SnapshotRunner::standard();
    runner.allocation = runner.allocation.replace("gpu:h100:1", "gpu:h100_pcie:1");
    runner.responses.insert(
        "gpu02".into(),
        Ok("0, 3, NVIDIA H100-PCIe, GPU-second, 10, 81559, 2, Disabled\n".into()),
    );
    let snapshot = client(Arc::new(runner)).job_gpu_snapshot("123_7").unwrap();
    assert_eq!(snapshot.devices.len(), 2);
    assert!(snapshot.warnings.is_empty());
}

#[test]
fn jobs_without_gpu_or_with_shared_gpu_allocations_do_not_probe_nodes() {
    for (from, to) in [
        ("gpu:h100:1(IDX:1)", "mps:50(IDX:1)"),
        ("gpu:h100:1(IDX:1)", ""),
        ("gpu:h100:1(IDX:1)", "shard:1(IDX:1)"),
    ] {
        let mut runner = SnapshotRunner::standard();
        runner.allocation = runner
            .allocation
            .replace(from, to)
            .replace("gpu:h100:1(IDX:0)", "");
        let runner = Arc::new(runner);
        assert!(client(runner.clone()).job_gpu_snapshot("123_7").is_err());
        assert_eq!(runner.ssh_count(), 0);
    }
}

#[test]
fn invalid_device_measurements_remain_unknown() {
    let mut runner = SnapshotRunner::standard();
    runner.responses.insert(
        "gpu02".into(),
        Ok("0, 3, NVIDIA H100 PCIe, GPU-second, -1, 18446744073709551615, NaN, Disabled\n".into()),
    );
    let snapshot = client(Arc::new(runner)).job_gpu_snapshot("123_7").unwrap();
    let device = &snapshot.devices[1];
    assert_eq!(device.memory_used_bytes, None);
    assert_eq!(device.memory_total_bytes, None);
    assert_eq!(device.utilization_percent, None);
}

#[test]
fn grouped_nodes_and_comma_separated_device_indices_are_expanded() {
    let mut runner = SnapshotRunner::standard();
    runner.allocation = "JobId=70001 ArrayJobId=123 ArrayTaskId=7 UserId=alice(1000) JobState=RUNNING NodeList=gpu[01-02] AllocTRES=gres/gpu=4\nNodes=gpu[01-02] CPU_IDs=0-3 Mem=16000 GRES=gpu:h100:2(IDX:0,1)\n".into();
    runner.nodes = runner.nodes.replace("gpu:h100:1", "gpu:h100:2");
    runner.responses.insert(
        "gpu02".into(),
        Ok(include_str!("fixtures/gpu_snapshot_nvidia.csv").into()),
    );
    let snapshot = client(Arc::new(runner)).job_gpu_snapshot("123_7").unwrap();
    assert_eq!(snapshot.devices.len(), 4);
    assert!(snapshot.warnings.is_empty());
}

#[test]
fn maximum_node_count_keeps_per_worker_timeouts_inside_the_operation_budget() {
    let mut runner = SnapshotRunner::standard();
    runner.allocation = "JobId=70001 ArrayJobId=123 ArrayTaskId=7 UserId=alice(1000) JobState=RUNNING NodeList=gpu[01-16] AllocTRES=gres/gpu=16\nNodes=gpu[01-16] CPU_IDs=0-3 Mem=16000 GRES=gpu:h100:1(IDX:0)\n".into();
    runner.nodes.clear();
    for index in 1..=16 {
        let node = format!("gpu{index:02}");
        runner
            .nodes
            .push_str(&format!("NodeName={node} Gres=gpu:h100:1\n"));
        runner.responses.insert(
            node,
            Ok("0, 0, NVIDIA H100 PCIe, GPU-one, 1, 80000, 50, Disabled\n".into()),
        );
    }
    let runner = Arc::new(runner);
    let snapshot = client(runner.clone()).job_gpu_snapshot("123_7").unwrap();
    assert_eq!(snapshot.devices.len(), 16);
    assert_eq!(runner.ssh_count(), 16);
    assert!(snapshot.warnings.is_empty());
    for call in runner
        .calls
        .lock()
        .unwrap()
        .iter()
        .filter(|call| call.0 == "ssh")
    {
        assert_eq!(call.2 * 4, Duration::from_secs(15));
    }
}

#[test]
fn oversized_command_output_is_rejected_without_parsing_or_followup_commands() {
    let mut runner = SnapshotRunner::standard();
    runner.allocation = "x".repeat(256 * 1024 + 1);
    let runner = Arc::new(runner);
    assert!(
        client(runner.clone())
            .job_gpu_snapshot("123_7")
            .unwrap_err()
            .contains("size limit")
    );
    assert_eq!(runner.calls.lock().unwrap().len(), 1);
    let mut runner = SnapshotRunner::standard();
    runner
        .responses
        .insert("gpu01".into(), Ok("x".repeat(256 * 1024 + 1)));
    let snapshot = client(Arc::new(runner)).job_gpu_snapshot("123_7").unwrap();
    assert_eq!(snapshot.devices.len(), 1);
    assert!(snapshot.warnings[0].contains("size limit"));
}
