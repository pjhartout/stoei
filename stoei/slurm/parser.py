"""Parsers for SLURM command output."""

import re


def parse_scontrol_output(raw_output: str) -> dict[str, str]:
    """Parse scontrol output into key-value pairs.

    Args:
        raw_output: Raw output from scontrol command.

    Returns:
        Dictionary of parsed key-value pairs.
    """
    result: dict[str, str] = {}

    # scontrol output has Key=Value pairs, possibly spanning multiple lines
    # Join continuation lines (lines starting with spaces)
    current_line = raw_output.replace("\n   ", " ")

    # Match Key=Value patterns
    pattern = re.compile(r"(\w+(?:/\w+)*)=(\S+|(?=\s+\w+=))")
    for match in pattern.finditer(current_line):
        key, value = match.groups()
        result[key] = value.strip() if value else ""

    return result


def parse_squeue_output(raw_output: str) -> list[tuple[str, ...]]:
    """Parse squeue output into a list of job tuples.

    Args:
        raw_output: Raw output from squeue command.

    Returns:
        List of tuples containing job information.
    """
    lines = raw_output.strip().split("\n")
    if len(lines) <= 1:  # Only header or empty
        return []

    jobs: list[tuple[str, ...]] = []
    for line in lines[1:]:  # Skip header
        parts = line.split("|")
        if len(parts) >= 6:
            jobs.append(tuple(parts))

    return jobs


def parse_sacct_output(raw_output: str) -> tuple[list[tuple[str, ...]], int, int, int]:
    """Parse sacct output into job history data.

    Args:
        raw_output: Raw output from sacct command.

    Returns:
        Tuple of (jobs list, total jobs count, total requeues, max requeues).
    """
    lines = raw_output.strip().split("\n")
    if len(lines) <= 1:  # Only header or empty
        return [], 0, 0, 0

    jobs: list[tuple[str, ...]] = []
    total_requeues = 0
    max_requeues = 0

    for line in lines[1:]:  # Skip header
        parts = line.split("|")
        if len(parts) >= 7:
            jobs.append(tuple(parts))
            try:
                restart_count = int(parts[3])
                total_requeues += restart_count
                max_requeues = max(max_requeues, restart_count)
            except (ValueError, IndexError):
                pass

    total_jobs = len(jobs)

    # Sort by JobID descending (most recent first)
    def job_sort_key(job: tuple[str, ...]) -> int:
        job_id = job[0].split("_")[0].strip()
        try:
            return int(job_id)
        except ValueError:
            return 0

    jobs.sort(key=job_sort_key, reverse=True)

    return jobs, total_jobs, total_requeues, max_requeues
