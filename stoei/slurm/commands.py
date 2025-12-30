"""SLURM command execution."""

import subprocess

from stoei.logger import get_logger
from stoei.slurm.formatters import format_job_info, format_sacct_job_info
from stoei.slurm.parser import (
    parse_sacct_job_output,
    parse_sacct_output,
    parse_scontrol_output,
    parse_squeue_output,
)
from stoei.slurm.validation import (
    ValidationError,
    get_current_username,
    resolve_executable,
    validate_job_id,
)

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

    try:
        scontrol = resolve_executable("scontrol")
        command = [scontrol, "show", "jobid", job_id]
        logger.debug(f"Running command: {' '.join(command)}")

        result = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError as exc:
        logger.error(f"scontrol not found: {exc}")
        return "", f"scontrol not found: {exc}"
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout getting job info for {job_id}")
        return "", "Command timed out"
    except subprocess.SubprocessError as exc:
        logger.error(f"Error running scontrol: {exc}")
        return "", f"Error running scontrol: {exc}"

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

    try:
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

        result = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError as exc:
        logger.error(f"sacct not found: {exc}")
        return "", f"sacct not found: {exc}"
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout getting job info via sacct for {job_id}")
        return "", "Command timed out"
    except subprocess.SubprocessError as exc:
        logger.error(f"Error running sacct: {exc}")
        return "", f"Error running sacct: {exc}"

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


def get_running_jobs() -> list[tuple[str, ...]]:
    """Return running/pending jobs from squeue.

    Returns:
        List of tuples containing job information.
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
    except (FileNotFoundError, ValidationError) as exc:
        logger.error(f"Error setting up squeue command: {exc}")
        return []
    except subprocess.TimeoutExpired:
        logger.error("Timeout getting running jobs")
        return []
    except subprocess.SubprocessError as exc:
        logger.error(f"Error getting running jobs: {exc}")
        return []

    if result.returncode != 0:
        logger.warning(f"squeue returned non-zero exit code: {result.returncode}")
        return []

    jobs = parse_squeue_output(result.stdout)
    logger.debug(f"Found {len(jobs)} running/pending jobs")
    return jobs


def get_job_history() -> tuple[list[tuple[str, ...]], int, int, int]:
    """Return job history for the last 30 days (sacct).

    Returns:
        Tuple of (jobs list, total jobs count, total requeues, max requeues).
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
            "now-30days",
            "-X",
            "-P",
        ]
        logger.debug(f"Running sacct command for user {username}")

        result = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, ValidationError) as exc:
        logger.error(f"Error setting up sacct command: {exc}")
        return [], 0, 0, 0
    except subprocess.TimeoutExpired:
        logger.error("Timeout getting job history")
        return [], 0, 0, 0
    except subprocess.SubprocessError as exc:
        logger.error(f"Error getting job history: {exc}")
        return [], 0, 0, 0

    if result.returncode != 0:
        logger.warning(f"sacct returned non-zero exit code: {result.returncode}")
        return [], 0, 0, 0

    jobs, total_jobs, total_requeues, max_requeues = parse_sacct_output(result.stdout)
    logger.debug(f"Found {total_jobs} jobs in history with {total_requeues} total requeues")
    return jobs, total_jobs, total_requeues, max_requeues


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
    except FileNotFoundError as exc:
        logger.error(f"scancel not found: {exc}")
        return False, f"scancel not found: {exc}"
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout cancelling job {job_id}")
        return False, "Command timed out"
    except subprocess.SubprocessError as exc:
        logger.error(f"Error running scancel: {exc}")
        return False, f"Error running scancel: {exc}"

    if result.returncode != 0:
        error_msg = result.stderr.strip() or "Failed to cancel job"
        logger.warning(f"scancel returned error for job {job_id}: {error_msg}")
        return False, f"scancel error: {error_msg}"

    logger.info(f"Successfully cancelled job {job_id}")
    return True, None
