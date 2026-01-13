"""SLURM command execution."""

import subprocess
import time

from stoei.logger import get_logger
from stoei.slurm.formatters import format_job_info, format_node_info, format_sacct_job_info
from stoei.slurm.parser import (
    parse_sacct_job_output,
    parse_sacct_output,
    parse_scontrol_nodes_output,
    parse_scontrol_output,
    parse_squeue_output,
)
from stoei.slurm.validation import (
    ValidationError,
    get_current_username,
    resolve_executable,
    validate_job_id,
)

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 1.5
DEFAULT_INITIAL_DELAY = 0.5

logger = get_logger(__name__)

# Fields to request from sacct for detailed job info
SACCT_JOB_FIELDS = [
    "JobID",
    "JobName",
    "User",
    "Account",
    "Partition",
    "State",
    "ExitCode",
    "Start",
    "End",
    "Elapsed",
    "TimelimitRaw",
    "NNodes",
    "NCPUS",
    "NTasks",
    "ReqMem",
    "MaxRSS",
    "MaxVMSize",
    "NodeList",
    "WorkDir",
    "StdOut",
    "StdErr",
    "Submit",
    "Priority",
    "QOS",
]


def _run_subprocess_command(
    command: list[str], timeout: int, command_name: str
) -> tuple[subprocess.CompletedProcess[str] | None, str | None]:
    """Run a subprocess command and handle common errors.

    Args:
        command: The command to run.
        timeout: Command timeout in seconds.
        command_name: Name of the command for error messages.

    Returns:
        Tuple of (result, optional error message). Result is None on error.
    """
    try:
        result = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        logger.exception(f"{command_name} not found")
        return None, f"{command_name} not found"
    except subprocess.TimeoutExpired:
        logger.exception(f"Timeout running {command_name}")
        return None, "Command timed out"
    except subprocess.SubprocessError:
        logger.exception(f"Error running {command_name}")
        return None, f"Error running {command_name}"
    else:
        return result, None


def _run_with_retry(  # noqa: PLR0913
    command: list[str],
    timeout: int,
    command_name: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
) -> tuple[subprocess.CompletedProcess[str] | None, str | None]:
    """Run a subprocess command with exponential backoff retry.

    Args:
        command: The command to run.
        timeout: Command timeout in seconds.
        command_name: Name of the command for error messages.
        max_retries: Maximum number of retry attempts (default: 3).
        backoff_factor: Factor to multiply delay by after each retry (default: 1.5).
        initial_delay: Initial delay in seconds before first retry (default: 0.5).

    Returns:
        Tuple of (result, optional error message). Result is None on error.
    """
    last_error: str | None = None
    delay = initial_delay

    for attempt in range(max_retries + 1):
        result, error = _run_subprocess_command(command, timeout, command_name)

        if result is not None and result.returncode == 0:
            if attempt > 0:
                logger.debug(f"{command_name} succeeded on attempt {attempt + 1}")
            return result, None

        # Check if error is retryable
        if error and ("not found" in error.lower()):
            # File not found is not retryable
            return result, error

        last_error = (
            error if error else f"{command_name} failed with return code {result.returncode if result else 'unknown'}"
        )

        if attempt < max_retries:
            logger.debug(f"{command_name} failed (attempt {attempt + 1}/{max_retries + 1}), retrying in {delay:.1f}s")
            time.sleep(delay)
            delay *= backoff_factor

    logger.warning(f"{command_name} failed after {max_retries + 1} attempts: {last_error}")
    return None, last_error


def _run_scontrol_for_job(job_id: str) -> tuple[str, str | None]:
    """Run scontrol show jobid and return raw output.

    Args:
        job_id: The SLURM job ID to query.

    Returns:
        Tuple of (raw output, optional error message).
    """
    try:
        validate_job_id(job_id)
    except ValidationError as exc:
        return "", str(exc)

    scontrol = resolve_executable("scontrol")
    command = [scontrol, "show", "jobid", job_id]
    logger.debug(f"Running command: {' '.join(command)}")

    result, error = _run_subprocess_command(command, timeout=10, command_name="scontrol")
    if error or result is None:
        return "", error or "Unknown error"

    if result.returncode != 0:
        error_msg = result.stderr.strip() or "Job not found or invalid job ID"
        logger.warning(f"scontrol returned error for job {job_id}: {error_msg}")
        return "", f"scontrol error: {error_msg}"

    raw_output = result.stdout.strip()
    if not raw_output:
        return "", "No information available for this job"

    return raw_output, None


def _run_sacct_for_job(job_id: str) -> tuple[str, str | None]:
    """Run sacct for a specific job and return raw output.

    This is used as a fallback for completed jobs that are no longer in scontrol.

    Args:
        job_id: The SLURM job ID to query.

    Returns:
        Tuple of (raw output, optional error message).
    """
    try:
        validate_job_id(job_id)
    except ValidationError as exc:
        return "", str(exc)

    sacct = resolve_executable("sacct")
    format_str = ",".join(SACCT_JOB_FIELDS)
    command = [
        sacct,
        "-j",
        job_id,
        f"--format={format_str}",
        "-P",  # Parseable output with | delimiter
        "--noheader",
    ]
    logger.debug(f"Running sacct command: {' '.join(command)}")

    result, error = _run_subprocess_command(command, timeout=10, command_name="sacct")
    if error or result is None:
        return "", error or "Unknown error"

    if result.returncode != 0:
        error_msg = result.stderr.strip() or "Job not found in accounting database"
        logger.warning(f"sacct returned error for job {job_id}: {error_msg}")
        return "", f"sacct error: {error_msg}"

    raw_output = result.stdout.strip()
    if not raw_output:
        return "", "No accounting information available for this job"

    return raw_output, None


def get_job_info(job_id: str) -> tuple[str, str | None]:
    """Get detailed job information using scontrol, falling back to sacct.

    For running/pending jobs, uses scontrol which provides more detail.
    For completed jobs, falls back to sacct which has historical data.

    Args:
        job_id: The SLURM job ID to query.

    Returns:
        Tuple of (formatted job info, optional error message).
    """
    # First try scontrol (works for active jobs)
    raw_output, scontrol_error = _run_scontrol_for_job(job_id)
    if not scontrol_error:
        logger.info(f"Successfully retrieved info for job {job_id} via scontrol")
        return format_job_info(raw_output), None

    # Fall back to sacct for completed jobs
    logger.debug(f"scontrol failed for {job_id}, trying sacct: {scontrol_error}")
    raw_output, sacct_error = _run_sacct_for_job(job_id)
    if not sacct_error:
        parsed = parse_sacct_job_output(raw_output, SACCT_JOB_FIELDS)
        if parsed:
            logger.info(f"Successfully retrieved info for job {job_id} via sacct")
            return format_sacct_job_info(parsed), None
        return "", "Could not parse sacct output"

    # Both failed
    logger.warning(f"Could not get info for job {job_id}: scontrol={scontrol_error}, sacct={sacct_error}")
    return "", f"Job not found. scontrol: {scontrol_error}"


def get_job_info_parsed(job_id: str) -> tuple[dict[str, str], str | None]:
    """Get parsed job information as a dictionary.

    Tries scontrol first, falls back to sacct for completed jobs.

    Args:
        job_id: The SLURM job ID to query.

    Returns:
        Tuple of (parsed job info dict, optional error message).
    """
    # Try scontrol first
    raw_output, scontrol_error = _run_scontrol_for_job(job_id)
    if not scontrol_error:
        parsed = parse_scontrol_output(raw_output)
        logger.info(f"Successfully parsed info for job {job_id} via scontrol")
        return parsed, None

    # Fall back to sacct
    logger.debug(f"scontrol failed for {job_id}, trying sacct")
    raw_output, sacct_error = _run_sacct_for_job(job_id)
    if not sacct_error:
        parsed = parse_sacct_job_output(raw_output, SACCT_JOB_FIELDS)
        if parsed:
            logger.info(f"Successfully parsed info for job {job_id} via sacct")
            return parsed, None
        return {}, "Could not parse sacct output"

    return {}, f"Job not found: {scontrol_error}"


def _expand_log_path(path: str, job_id: str, job_info: dict[str, str]) -> str:
    """Expand SLURM placeholders in a log path.

    Args:
        path: The log path with potential placeholders.
        job_id: The job ID (may include array task like "12345_0").
        job_info: Parsed job information dictionary.

    Returns:
        Path with placeholders replaced.
    """
    # Parse job ID parts
    array_parts = job_id.split("_")
    base_job_id = array_parts[0]
    array_task_id = array_parts[1] if len(array_parts) > 1 else "0"

    # Get job info values (with fallbacks)
    username = job_info.get("UserId", job_info.get("User", ""))
    # UserId from scontrol is "user(uid)", extract just the username
    if "(" in username:
        username = username.split("(")[0]
    job_name = job_info.get("JobName", job_info.get("Name", "job"))

    # Replace common SLURM placeholders
    path = path.replace("%j", base_job_id)  # Job ID
    path = path.replace("%J", job_id)  # Job ID with array task
    path = path.replace("%A", base_job_id)  # Array job ID
    path = path.replace("%a", array_task_id)  # Array task ID
    path = path.replace("%u", username)  # Username
    path = path.replace("%x", job_name)  # Job name
    path = path.replace("%N", job_info.get("NodeList", job_info.get("BatchHost", "node")))  # Node name

    return path


def get_job_log_paths(job_id: str) -> tuple[str | None, str | None, str | None]:
    """Get log file paths for a job.

    Args:
        job_id: The SLURM job ID to query.

    Returns:
        Tuple of (stdout_path, stderr_path, error_message).
        Paths are None if not available, error_message is None on success.
    """
    parsed, error = get_job_info_parsed(job_id)
    if error:
        return None, None, error

    # Get stdout and stderr paths
    stdout = parsed.get("StdOut")
    stderr = parsed.get("StdErr")

    # Expand placeholders using job info
    if stdout:
        stdout = _expand_log_path(stdout, job_id, parsed)
        # Normalize empty/whitespace paths to None
        if not stdout or not stdout.strip():
            stdout = None
    else:
        stdout = None

    if stderr:
        stderr = _expand_log_path(stderr, job_id, parsed)
        # Normalize empty/whitespace paths to None
        if not stderr or not stderr.strip():
            stderr = None
    else:
        stderr = None

    logger.debug(f"Log paths for job {job_id}: stdout={stdout}, stderr={stderr}")
    return stdout, stderr, None


def get_running_jobs() -> tuple[list[tuple[str, ...]], str | None]:
    """Return running/pending jobs from squeue.

    Returns:
        Tuple of (List of tuples containing job information, optional error message).
    """
    try:
        username = get_current_username()
        squeue = resolve_executable("squeue")
        command = [
            squeue,
            "-u",
            username,
            "-o",
            "%.10i|%.15j|%.8T|%.10M|%.4D|%.12R",
        ]
        logger.debug(f"Running squeue command for user {username}")

        result = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, ValidationError):
        logger.exception("Error setting up squeue command")
        return [], "Error setting up squeue"
    except subprocess.TimeoutExpired:
        logger.exception("Timeout getting running jobs")
        return [], "Timeout getting running jobs"
    except subprocess.SubprocessError:
        logger.exception("Error getting running jobs")
        return [], "Error getting running jobs"

    if result.returncode != 0:
        logger.warning(f"squeue returned non-zero exit code: {result.returncode}")
        return [], f"squeue error: {result.stderr}"

    jobs = parse_squeue_output(result.stdout)
    logger.debug(f"Found {len(jobs)} running/pending jobs")
    return jobs, None


def get_job_history(days: int = 7) -> tuple[list[tuple[str, ...]], int, int, int, str | None]:
    """Return job history for the last N days (sacct).

    Args:
        days: Number of days to look back for job history (default: 7).

    Returns:
        Tuple of (jobs list, total jobs count, total requeues, max requeues, optional error message).
    """
    try:
        username = get_current_username()
        sacct = resolve_executable("sacct")
        command = [
            sacct,
            "-u",
            username,
            "--format=JobID,JobName,State,Restart,Elapsed,ExitCode,NodeList",
            "-S",
            f"now-{days}days",
            "-X",
            "-P",
        ]
        logger.debug(f"Running sacct command for user {username} (last {days} days)")

        result = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, ValidationError):
        logger.exception("Error setting up sacct command")
        return [], 0, 0, 0, "Error setting up sacct"
    except subprocess.TimeoutExpired:
        logger.exception("Timeout getting job history")
        return [], 0, 0, 0, "Timeout getting job history"
    except subprocess.SubprocessError:
        logger.exception("Error getting job history")
        return [], 0, 0, 0, "Error getting job history"

    if result.returncode != 0:
        logger.warning(f"sacct returned non-zero exit code: {result.returncode}")
        return [], 0, 0, 0, f"sacct error: {result.stderr}"

    jobs, total_jobs, total_requeues, max_requeues = parse_sacct_output(result.stdout)
    logger.debug(f"Found {total_jobs} jobs in history (last {days} days) with {total_requeues} total requeues")
    return jobs, total_jobs, total_requeues, max_requeues, None


def cancel_job(job_id: str) -> tuple[bool, str | None]:
    """Cancel a SLURM job.

    Args:
        job_id: The SLURM job ID to cancel.

    Returns:
        Tuple of (success, optional error message).
    """
    try:
        validate_job_id(job_id)
    except ValidationError as exc:
        return False, str(exc)

    try:
        scancel = resolve_executable("scancel")
        command = [scancel, job_id]
        logger.debug(f"Running command: {' '.join(command)}")

        result = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        logger.exception("scancel not found")
        return False, "scancel not found"
    except subprocess.TimeoutExpired:
        logger.exception(f"Timeout cancelling job {job_id}")
        return False, "Command timed out"
    except subprocess.SubprocessError:
        logger.exception("Error running scancel")
        return False, "Error running scancel"

    if result.returncode != 0:
        error_msg = result.stderr.strip() or "Failed to cancel job"
        logger.warning(f"scancel returned error for job {job_id}: {error_msg}")
        return False, f"scancel error: {error_msg}"

    logger.info(f"Successfully cancelled job {job_id}")
    return True, None


def get_cluster_nodes() -> tuple[list[dict[str, str]], str | None]:
    """Get information about all cluster nodes.

    Uses retry logic with exponential backoff for transient failures.

    Returns:
        Tuple of (list of node info dictionaries, optional error message).
    """
    try:
        scontrol = resolve_executable("scontrol")
    except (FileNotFoundError, ValidationError):
        logger.exception("scontrol not found")
        return [], "scontrol not found"

    command = [scontrol, "show", "nodes"]
    logger.debug(f"Running command: {' '.join(command)}")

    result, error = _run_with_retry(command, timeout=15, command_name="scontrol show nodes")
    if error or result is None:
        return [], error or "Unknown error"

    if result.returncode != 0:
        error_msg = result.stderr.strip() or "Failed to get cluster nodes"
        logger.warning(f"scontrol returned error: {error_msg}")
        return [], f"scontrol error: {error_msg}"

    raw_output = result.stdout.strip()
    if not raw_output:
        return [], "No node information available"

    nodes = parse_scontrol_nodes_output(raw_output)
    logger.debug(f"Found {len(nodes)} cluster nodes")
    return nodes, None


def get_node_info(node_name: str) -> tuple[str, str | None]:
    """Get detailed node information using scontrol.

    Args:
        node_name: The node name to query.

    Returns:
        Tuple of (formatted node info, optional error message).
    """
    try:
        scontrol = resolve_executable("scontrol")
        command = [scontrol, "show", "node", node_name]
        logger.debug(f"Running command: {' '.join(command)}")

        result, error = _run_subprocess_command(command, timeout=10, command_name="scontrol")
        if error or result is None:
            return "", error or "Unknown error"

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Node not found or invalid node name"
            logger.warning(f"scontrol returned error for node {node_name}: {error_msg}")
            return "", f"scontrol error: {error_msg}"

        raw_output = result.stdout.strip()
        if not raw_output:
            return "", "No information available for this node"

        logger.info(f"Successfully retrieved info for node {node_name}")
        return format_node_info(raw_output), None

    except Exception as exc:
        logger.exception(f"Error getting node info for {node_name}")
        return "", f"Error: {exc}"


# Fixed-width column positions for squeue -O format
# Format: JobID:20,Name:20,UserName:15,Partition:15,StateCompact:10,TimeUsed:12,NumNodes:6,NodeList:30,tres:80
_SQUEUE_COL_JOBID_END = 20
_SQUEUE_COL_NAME_END = 40
_SQUEUE_COL_USER_END = 55
_SQUEUE_COL_PARTITION_END = 70
_SQUEUE_COL_STATE_END = 80
_SQUEUE_COL_TIME_END = 92
_SQUEUE_COL_NODES_END = 98
_SQUEUE_COL_NODELIST_END = 128


def _parse_fixed_width_squeue_line(line: str) -> tuple[str, ...] | None:
    """Parse a fixed-width squeue output line into a tuple.

    Args:
        line: Single line from squeue -O output.

    Returns:
        Tuple of (job_id, name, user, partition, state, time_used, num_nodes, node_list, tres) or None.
    """
    if len(line) < _SQUEUE_COL_JOBID_END:
        return None

    job_id = line[0:_SQUEUE_COL_JOBID_END].strip()
    if not job_id:
        return None

    name = line[_SQUEUE_COL_JOBID_END:_SQUEUE_COL_NAME_END].strip() if len(line) > _SQUEUE_COL_JOBID_END else ""
    user = line[_SQUEUE_COL_NAME_END:_SQUEUE_COL_USER_END].strip() if len(line) > _SQUEUE_COL_NAME_END else ""
    partition = line[_SQUEUE_COL_USER_END:_SQUEUE_COL_PARTITION_END].strip() if len(line) > _SQUEUE_COL_USER_END else ""
    state = (
        line[_SQUEUE_COL_PARTITION_END:_SQUEUE_COL_STATE_END].strip() if len(line) > _SQUEUE_COL_PARTITION_END else ""
    )
    time_used = line[_SQUEUE_COL_STATE_END:_SQUEUE_COL_TIME_END].strip() if len(line) > _SQUEUE_COL_STATE_END else ""
    num_nodes = line[_SQUEUE_COL_TIME_END:_SQUEUE_COL_NODES_END].strip() if len(line) > _SQUEUE_COL_TIME_END else ""
    node_list = (
        line[_SQUEUE_COL_NODES_END:_SQUEUE_COL_NODELIST_END].strip() if len(line) > _SQUEUE_COL_NODES_END else ""
    )
    tres = line[_SQUEUE_COL_NODELIST_END:].strip() if len(line) > _SQUEUE_COL_NODELIST_END else ""

    return (job_id, name, user, partition, state, time_used, num_nodes, node_list, tres)


def get_all_running_jobs() -> tuple[list[tuple[str, ...]], str | None]:
    """Return all RUNNING and PENDING jobs from squeue (all users) - single command, no loops.

    Uses squeue's -O format with Tres field to get all data in one call.
    Fetches both RUNNING and PENDING jobs so queued jobs are included.

    Returns:
        Tuple of (List of tuples containing job information, optional error message).
    """
    try:
        squeue = resolve_executable("squeue")
        # Use -O format which supports Tres field directly
        # This eliminates the need for per-job scontrol calls
        command = [
            squeue,
            "-O",
            "JobID:20,Name:20,UserName:15,Partition:15,StateCompact:10,TimeUsed:12,NumNodes:6,NodeList:30,tres:80",
            "-a",  # Show all partitions
            "-t",
            "RUNNING,PENDING",
            "--noheader",
        ]
        logger.debug("Running squeue command for all active jobs (running+pending) (single command)")

        result = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except FileNotFoundError:
        logger.exception("Error setting up squeue command")
        return [], "squeue not found"
    except subprocess.TimeoutExpired:
        logger.exception("Timeout getting all running jobs")
        return [], "Timeout getting all running jobs"
    except subprocess.SubprocessError:
        logger.exception("Error getting all running jobs")
        return [], "Error getting all running jobs"

    if result.returncode != 0:
        logger.warning(f"squeue returned non-zero exit code: {result.returncode}")
        return [], f"squeue error: {result.stderr}"

    # Parse fixed-width format output from -O option
    jobs: list[tuple[str, ...]] = []
    lines = result.stdout.strip().split("\n")

    for line in lines:
        if not line.strip():
            continue

        parsed = _parse_fixed_width_squeue_line(line)
        if parsed:
            jobs.append(parsed)

    logger.debug(f"Found {len(jobs)} active jobs (all users) with TRES in single command")
    return jobs, None


def get_all_users_jobs() -> tuple[list[tuple[str, ...]], str | None]:
    """Return all running/pending jobs from squeue (all users).

    Backward compatible wrapper - now calls get_all_running_jobs().

    Returns:
        Tuple of (List of tuples containing job information, optional error message).
    """
    return get_all_running_jobs()
