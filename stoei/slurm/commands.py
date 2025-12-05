"""SLURM command execution."""

import subprocess

from stoei.logging import get_logger
from stoei.slurm.formatters import format_job_info
from stoei.slurm.parser import parse_sacct_output, parse_scontrol_output, parse_squeue_output
from stoei.slurm.validation import (
    ValidationError,
    get_current_username,
    resolve_executable,
    validate_job_id,
)

logger = get_logger(__name__)


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


def get_job_info(job_id: str) -> tuple[str, str | None]:
    """Get detailed job information using scontrol show jobid.

    Args:
        job_id: The SLURM job ID to query.

    Returns:
        Tuple of (formatted job info, optional error message).
    """
    raw_output, error = _run_scontrol_for_job(job_id)
    if error:
        return "", error

    logger.info(f"Successfully retrieved info for job {job_id}")
    return format_job_info(raw_output), None


def get_job_info_parsed(job_id: str) -> tuple[dict[str, str], str | None]:
    """Get parsed job information as a dictionary.

    Args:
        job_id: The SLURM job ID to query.

    Returns:
        Tuple of (parsed job info dict, optional error message).
    """
    raw_output, error = _run_scontrol_for_job(job_id)
    if error:
        return {}, error

    parsed = parse_scontrol_output(raw_output)
    logger.info(f"Successfully parsed info for job {job_id}")
    return parsed, None


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

    # Get stdout and stderr paths, replacing %j with actual job ID
    stdout = parsed.get("StdOut")
    stderr = parsed.get("StdErr")

    # Replace %j placeholder with actual job ID (SLURM convention)
    base_job_id = job_id.split("_")[0]  # Handle array jobs like 12345_0
    if stdout:
        stdout = stdout.replace("%j", base_job_id)
    if stderr:
        stderr = stderr.replace("%j", base_job_id)

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
