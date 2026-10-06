use std::{
    collections::{BTreeMap, BTreeSet},
    thread,
    time::Duration,
};

use super::{
    Runner, calculate_total_gpus, checked_job_id, field, is_mig_type, parse_gpu_entries,
    parse_gpu_from_gres, parse_nodes, parse_scontrol_fields, parse_scontrol_job_records,
};

const MAX_NODES: usize = 16;
const MAX_DEVICES: usize = 256;
const MAX_OUTPUT: usize = 256 * 1024;
const CONTROLLER_TIMEOUT: Duration = Duration::from_secs(5);
const PROBE_BUDGET: Duration = Duration::from_secs(15);
const MAX_PROBE_TIMEOUT: Duration = Duration::from_secs(7);
const MAX_WORKERS: usize = 4;
const GPU_QUERY: &str = "nvidia-smi --query-gpu=index,minor_number,name,uuid,memory.used,memory.total,utilization.gpu,mig.mode.current --format=csv,noheader,nounits";

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GpuSnapshot {
    pub devices: Vec<GpuDevice>,
    pub warnings: Vec<String>,
}

/// A device-wide snapshot for a physical GPU allocated to the selected job.
#[derive(Clone, Debug, PartialEq)]
pub struct GpuDevice {
    pub node: String,
    pub index: u32,
    pub name: String,
    pub uuid: String,
    pub memory_used_bytes: Option<u64>,
    pub memory_total_bytes: Option<u64>,
    pub utilization_percent: Option<f64>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct Allocation {
    job_id: String,
    start: String,
    nodes: BTreeMap<String, BTreeMap<u32, String>>,
}

struct InventoryDevice {
    minor: u32,
    mig: bool,
    device: GpuDevice,
}

pub(super) fn job_gpu_snapshot(
    runner: &dyn Runner,
    username: &str,
    id: &str,
) -> Result<GpuSnapshot, String> {
    if id.len() > 64 || checked_job_id(id)? != id {
        return Err("Select one job or array task for a GPU snapshot".into());
    }
    let allocation = fetch_allocation(runner, username, id)?;
    let names = allocation.nodes.keys().cloned().collect::<Vec<_>>();
    let raw = run(runner, "scontrol", &["show", "node", &names.join(",")])?;
    let counts = node_inventory(&raw, &names)?;
    let chunk_size = names.len().div_ceil(MAX_WORKERS);
    let timeout = (PROBE_BUDGET / chunk_size as u32).min(MAX_PROBE_TIMEOUT);
    let mut snapshot = probe_nodes(runner, &allocation, &counts, &names, chunk_size, timeout)?;
    if fetch_allocation(runner, username, id)? != allocation {
        return Err("Job allocation changed during the GPU snapshot; refresh to retry".into());
    }
    snapshot
        .devices
        .sort_by(|left, right| (&left.node, left.index).cmp(&(&right.node, right.index)));
    Ok(snapshot)
}

fn run(runner: &dyn Runner, name: &str, args: &[&str]) -> Result<String, String> {
    let args = args
        .iter()
        .map(|value| (*value).to_owned())
        .collect::<Vec<_>>();
    let raw = runner
        .run(name, &args, CONTROLLER_TIMEOUT)
        .map_err(|error| error.to_string())?;
    bounded_output(&raw)?;
    Ok(raw)
}

fn bounded_output(raw: &str) -> Result<(), String> {
    if raw.len() > MAX_OUTPUT {
        Err("GPU snapshot command output exceeds the size limit".into())
    } else {
        Ok(())
    }
}

fn fetch_allocation(runner: &dyn Runner, username: &str, id: &str) -> Result<Allocation, String> {
    let raw = run(runner, "scontrol", &["--details", "show", "job", id])?;
    let records = parse_scontrol_job_records(&raw);
    if records.len() != 1 {
        return Err("GPU snapshots require one running job or array task".into());
    }
    let fields = &records[0];
    let job_id = field(fields, "JobId");
    let array_id = format!(
        "{}_{}",
        field(fields, "ArrayJobId"),
        field(fields, "ArrayTaskId")
    );
    if job_id != id && array_id != id {
        return Err("Controller returned a different job for the GPU snapshot".into());
    }
    if field(fields, "JobState") != "RUNNING" {
        return Err("GPU snapshots are available only for running jobs".into());
    }
    if field(fields, "UserId").split('(').next() != Some(username) {
        return Err("GPU snapshots are available only for your own jobs".into());
    }
    let hosts = hostnames(field(fields, "NodeList"))?;
    let nodes = allocated_devices(&raw, &hosts)?;
    if nodes.is_empty() {
        return Err("This job has no individually identifiable GPU allocation".into());
    }
    let expected = ["AllocTRES", "TRES"]
        .iter()
        .map(|key| allocated_gpu_count(field(fields, key)))
        .find(|count| *count > 0);
    let identified = nodes.values().map(BTreeMap::len).sum::<usize>();
    if expected.is_some_and(|count| count != identified as u64) {
        return Err("Detailed GPU allocation does not match the job's allocated GPU count".into());
    }
    Ok(Allocation {
        job_id: job_id.into(),
        start: field(fields, "StartTime").into(),
        nodes,
    })
}

fn allocated_gpu_count(raw: &str) -> u64 {
    let entries = parse_gpu_entries(raw);
    entries
        .iter()
        .find(|entry| entry.gpu_type.eq_ignore_ascii_case("gpu"))
        .map_or_else(|| calculate_total_gpus(&entries, true), |entry| entry.count)
}

fn allocated_devices(
    raw: &str,
    hosts: &[String],
) -> Result<BTreeMap<String, BTreeMap<u32, String>>, String> {
    let mut nodes = BTreeMap::new();
    let mut seen = BTreeSet::new();
    for line in raw
        .lines()
        .filter(|line| line.trim_start().starts_with("Nodes="))
    {
        let fields = parse_scontrol_fields(line);
        let devices = gres_devices(field(&fields, "GRES"))?;
        for host in hostnames(field(&fields, "Nodes"))? {
            if !hosts.contains(&host) || !seen.insert(host.clone()) {
                return Err("Ambiguous per-node GPU allocation in controller output".into());
            }
            if !devices.is_empty() {
                nodes.insert(host, devices.clone());
            }
        }
    }
    if seen.len() != hosts.len() {
        return Err("Controller did not identify GPU allocations for every job node".into());
    }
    Ok(nodes)
}

fn gres_devices(raw: &str) -> Result<BTreeMap<u32, String>, String> {
    let mut devices = BTreeMap::new();
    for entry in gres_entries(raw)? {
        let (description, detail) = entry.split_once('(').unwrap_or((entry, ""));
        let parts = description.split(':').collect::<Vec<_>>();
        if matches!(parts.first(), Some(&"mps") | Some(&"shard")) {
            return Err("Shared GPU allocations cannot be mapped to individual devices".into());
        }
        if parts.first() != Some(&"gpu") {
            continue;
        }
        let typ = match parts.as_slice() {
            ["gpu", _] => "gpu",
            ["gpu", typ, _] => typ,
            _ => return Err("Unrecognized GPU allocation description".into()),
        };
        let count = parts
            .last()
            .unwrap()
            .parse::<usize>()
            .map_err(|_| "Invalid GPU allocation count")?;
        if count == 0 {
            continue;
        }
        let indices = detail
            .strip_prefix("IDX:")
            .and_then(|value| value.strip_suffix(')'))
            .ok_or("GPU allocation has no physical device indices")?;
        let indices = indices_list(indices)?;
        if indices.len() != count || devices.len() + count > MAX_DEVICES {
            return Err("GPU allocation count or device limit does not match its indices".into());
        }
        for index in indices {
            if devices.insert(index, typ.to_owned()).is_some() {
                return Err("GPU allocation contains duplicate device indices".into());
            }
        }
    }
    Ok(devices)
}

fn gres_entries(raw: &str) -> Result<Vec<&str>, String> {
    let mut entries = Vec::new();
    let mut start = 0;
    let mut depth = 0;
    for (index, ch) in raw.char_indices() {
        match ch {
            '(' if depth == 0 => depth = 1,
            ')' if depth == 1 => depth = 0,
            ',' if depth == 0 => {
                entries.push(&raw[start..index]);
                start = index + 1;
            }
            '(' | ')' => return Err("Malformed GPU allocation description".into()),
            _ => {}
        }
    }
    if depth != 0 {
        return Err("Malformed GPU allocation description".into());
    }
    entries.push(&raw[start..]);
    if entries.len() > MAX_DEVICES {
        return Err("GPU allocation exceeds the device limit".into());
    }
    Ok(entries)
}

fn indices_list(raw: &str) -> Result<BTreeSet<u32>, String> {
    let mut indices = BTreeSet::new();
    for part in raw.split(',') {
        let (first, last) = part.split_once('-').unwrap_or((part, part));
        let first = first
            .parse::<u32>()
            .map_err(|_| "Invalid GPU device index")?;
        let last = last
            .parse::<u32>()
            .map_err(|_| "Invalid GPU device index")?;
        if first > last || last >= MAX_DEVICES as u32 {
            return Err("GPU device index range exceeds the supported limit".into());
        }
        for index in first..=last {
            if !indices.insert(index) {
                return Err("GPU device index range contains duplicates".into());
            }
        }
    }
    Ok(indices)
}

fn hostnames(raw: &str) -> Result<Vec<String>, String> {
    if raw.ends_with(',') {
        return Err("Malformed allocated node list".into());
    }
    let mut hosts = Vec::new();
    let mut rest = raw;
    while !rest.is_empty() {
        let end = if let Some(open) = rest.find('[') {
            let comma = rest.find(',');
            if comma.is_some_and(|comma| comma < open) {
                comma.unwrap()
            } else {
                let close = rest.find(']').ok_or("Malformed allocated node list")?;
                rest[close + 1..]
                    .find(',')
                    .map_or(rest.len(), |end| close + 1 + end)
            }
        } else {
            rest.find(',').unwrap_or(rest.len())
        };
        let token = &rest[..end];
        if let Some((prefix, ranges)) = token.split_once('[') {
            let ranges = ranges
                .strip_suffix(']')
                .ok_or("Unsupported allocated node list")?;
            for part in ranges.split(',') {
                let (first, last) = part.split_once('-').unwrap_or((part, part));
                let first_number = first.parse::<u32>().map_err(|_| "Invalid node index")?;
                let last_number = last.parse::<u32>().map_err(|_| "Invalid node index")?;
                if first_number > last_number || last_number - first_number >= MAX_NODES as u32 {
                    return Err("GPU snapshots support at most 16 allocated nodes".into());
                }
                for index in first_number..=last_number {
                    push_host(
                        &mut hosts,
                        format!("{prefix}{index:0width$}", width = first.len()),
                    )?;
                }
            }
        } else {
            push_host(&mut hosts, token.into())?;
        }
        rest = rest.get(end + 1..).unwrap_or("");
    }
    if hosts.is_empty() {
        return Err("Job has no allocated nodes".into());
    }
    Ok(hosts)
}

fn push_host(hosts: &mut Vec<String>, host: String) -> Result<(), String> {
    if host.len() > 253
        || !host
            .as_bytes()
            .first()
            .is_some_and(u8::is_ascii_alphanumeric)
        || !host
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
        || host.contains("..")
        || host.ends_with('.')
        || hosts.contains(&host)
    {
        return Err("Unsafe or ambiguous allocated node hostname".into());
    }
    if hosts.len() == MAX_NODES {
        return Err("GPU snapshots support at most 16 allocated nodes".into());
    }
    hosts.push(host);
    Ok(())
}

fn node_inventory(raw: &str, names: &[String]) -> Result<BTreeMap<String, usize>, String> {
    let mut counts = BTreeMap::new();
    for node in parse_nodes(raw) {
        if !names.contains(&node.name) || counts.contains_key(&node.name) {
            return Err("Controller returned an ambiguous GPU node inventory".into());
        }
        let entries = parse_gpu_from_gres(&node.gres);
        let count = entries
            .iter()
            .try_fold(0usize, |total, entry| {
                if is_mig_type(&entry.gpu_type) {
                    None
                } else {
                    total.checked_add(entry.count.try_into().ok()?)
                }
            })
            .unwrap_or(0);
        counts.insert(node.name, if count <= MAX_DEVICES { count } else { 0 });
    }
    if counts.len() != names.len() {
        return Err("Controller did not identify every allocated GPU node".into());
    }
    Ok(counts)
}

fn probe_nodes(
    runner: &dyn Runner,
    allocation: &Allocation,
    counts: &BTreeMap<String, usize>,
    names: &[String],
    chunk_size: usize,
    timeout: Duration,
) -> Result<GpuSnapshot, String> {
    debug_assert!(!names.is_empty());
    debug_assert!(names.len().div_ceil(chunk_size) <= MAX_WORKERS);
    thread::scope(|scope| {
        let handles = names
            .chunks(chunk_size)
            .map(|chunk| {
                scope.spawn(move || {
                    chunk
                        .iter()
                        .map(|name| {
                            let result = probe_node(
                                runner,
                                name,
                                &allocation.nodes[name],
                                counts[name],
                                timeout,
                            );
                            (name, result)
                        })
                        .collect::<Vec<_>>()
                })
            })
            .collect::<Vec<_>>();
        let mut snapshot = GpuSnapshot::default();
        for handle in handles {
            for (name, result) in handle.join().map_err(|_| "GPU snapshot worker stopped")? {
                match result {
                    Ok(devices) => snapshot.devices.extend(devices),
                    Err(error) => snapshot.warnings.push(format!("{name}: {error}")),
                }
            }
        }
        Ok(snapshot)
    })
}

fn probe_node(
    runner: &dyn Runner,
    node: &str,
    allocated: &BTreeMap<u32, String>,
    configured_count: usize,
    timeout: Duration,
) -> Result<Vec<GpuDevice>, String> {
    if configured_count == 0 || allocated.values().any(|typ| is_mig_type(typ)) {
        return Err(
            "MIG or unsupported GPU configuration; physical parent readings are unavailable".into(),
        );
    }
    let raw = runner
        .run("ssh", &ssh_args(node), timeout)
        .map_err(|error| error.to_string())?;
    bounded_output(&raw)?;
    let mut inventory = parse_inventory(node, &raw)?;
    if inventory.len() != configured_count || inventory.iter().any(|device| device.mig) {
        return Err(
            "GPU inventory differs from Slurm or uses MIG; device mapping is ambiguous".into(),
        );
    }
    // GRES indices follow configured device-file order. Slurm requires increasing file
    // numbers; matching the complete inventory avoids guessing when files are omitted.
    inventory.sort_by_key(|device| device.minor);
    let mut devices = Vec::with_capacity(allocated.len());
    for (index, typ) in allocated {
        let device = inventory
            .get(*index as usize)
            .ok_or("Allocated GPU index is absent from node inventory")?;
        let model = device
            .device
            .name
            .to_ascii_lowercase()
            .replace([' ', '-'], "_");
        let typ = typ.to_ascii_lowercase().replace('-', "_");
        if typ != "gpu" && !model.contains(&typ) {
            return Err(
                "Allocated GPU type differs from device inventory; mapping is ambiguous".into(),
            );
        }
        devices.push(device.device.clone());
    }
    Ok(devices)
}

fn ssh_args(node: &str) -> Vec<String> {
    [
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "RequestTTY=no",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "ControlPersist=no",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ForwardX11=no",
        "-o",
        "PermitLocalCommand=no",
        "-o",
        "RemoteCommand=none",
        "--",
        node,
        GPU_QUERY,
    ]
    .map(str::to_owned)
    .into()
}

fn parse_inventory(node: &str, raw: &str) -> Result<Vec<InventoryDevice>, String> {
    let mut devices = Vec::new();
    let mut indices = BTreeSet::new();
    let mut minors = BTreeSet::new();
    let mut uuids = BTreeSet::new();
    for line in raw.lines().filter(|line| !line.trim().is_empty()) {
        if devices.len() == MAX_DEVICES {
            return Err("NVIDIA inventory exceeds the device limit".into());
        }
        let fields = line.split(',').map(str::trim).collect::<Vec<_>>();
        if fields.len() != 8 {
            return Err("Unrecognized nvidia-smi GPU inventory output".into());
        }
        let index = fields[0]
            .parse::<u32>()
            .map_err(|_| "Invalid NVIDIA device index")?;
        let minor = fields[1]
            .parse::<u32>()
            .map_err(|_| "Invalid NVIDIA device minor number")?;
        if !indices.insert(index)
            || !minors.insert(minor)
            || !uuids.insert(fields[3])
            || fields[2].is_empty()
            || !fields[3].starts_with("GPU-")
        {
            return Err("NVIDIA device inventory has ambiguous identifiers".into());
        }
        let mig = match fields[7] {
            "Disabled" | "N/A" | "[N/A]" | "Not Supported" | "[Not Supported]" => false,
            "Enabled" => true,
            _ => return Err("Cannot determine NVIDIA MIG mode".into()),
        };
        devices.push(InventoryDevice {
            minor,
            mig,
            device: GpuDevice {
                node: node.into(),
                index,
                name: fields[2].into(),
                uuid: fields[3].into(),
                memory_used_bytes: mib(fields[4]),
                memory_total_bytes: mib(fields[5]),
                utilization_percent: fields[6]
                    .parse::<f64>()
                    .ok()
                    .filter(|value| value.is_finite() && (0.0..=100.0).contains(value)),
            },
        });
    }
    Ok(devices)
}

fn mib(raw: &str) -> Option<u64> {
    raw.parse::<u64>().ok()?.checked_mul(1 << 20)
}
