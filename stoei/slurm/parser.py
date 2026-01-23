"""Parsers for SLURM command output."""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Constants for parsing
MIN_SQUEUE_PARTS = 8  # JobID, Name, State, Time, Nodes, NodeList, SubmitTime, StartTime
MIN_SACCT_PARTS = 10  # JobID, Name, State, Restarts, Elapsed, ExitCode, NodeList, Submit, Start, End


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
        if len(parts) >= MIN_SQUEUE_PARTS:
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
        if len(parts) >= MIN_SACCT_PARTS:
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


def parse_sacct_job_output(raw_output: str, fields: list[str]) -> dict[str, str]:
    """Parse sacct output for a single job into key-value pairs.

    Args:
        raw_output: Raw output from sacct command (pipe-delimited, no header).
        fields: List of field names corresponding to the output columns.

    Returns:
        Dictionary of parsed key-value pairs. Returns the first (main) job entry.
    """
    lines = raw_output.strip().split("\n")
    if not lines:
        return {}

    # Take the first line (main job, not sub-steps like .batch, .extern)
    # Sub-steps have IDs like "12345.batch" or "12345.0"
    main_line = None
    for line in lines:
        parts = line.split("|")
        if parts:
            job_id = parts[0]
            # Skip sub-steps (contain a dot after the main ID)
            if "." not in job_id or job_id.endswith("."):
                main_line = line
                break

    if not main_line:
        # Fallback to first line if no main job found
        main_line = lines[0]

    parts = main_line.split("|")

    result: dict[str, str] = {}
    for i, field in enumerate(fields):
        if i < len(parts):
            value = parts[i].strip()
            if value:
                result[field] = value

    return result


def parse_scontrol_nodes_output(raw_output: str) -> list[dict[str, str]]:
    """Parse scontrol show nodes output into a list of node dictionaries.

    Args:
        raw_output: Raw output from 'scontrol show nodes' command.

    Returns:
        List of dictionaries, each containing node information.
    """
    nodes: list[dict[str, str]] = []
    current_node: dict[str, str] = {}

    # Split by double newlines (node separator) or single newline with NodeName
    lines = raw_output.split("\n")
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            if current_node:
                nodes.append(current_node)
                current_node = {}
            continue

        # Check if this is a new node entry (starts with NodeName=)
        if stripped_line.startswith("NodeName="):
            if current_node:
                nodes.append(current_node)
            current_node = {}

        # Parse key=value pairs
        # Both first line and continuation lines can have multiple key=value pairs
        # Continuation lines start with spaces/tabs

        # Parse all key=value pairs on this line using regex
        # Pattern matches: Key=Value where Key is alphanumeric with possible slashes/colons
        # and Value is everything until the next Key= or end of line
        pattern = r"(\w+(?:[/:]\w+)*)=([^\s=]+(?:\s+[^\s=]+)*?)(?=\s+\w+(?:[/:]\w+)*=|$)"
        matches = re.finditer(pattern, stripped_line)
        for match in matches:
            key = match.group(1)
            value = match.group(2).strip()
            current_node[key] = value

    # Add last node if exists
    if current_node:
        nodes.append(current_node)

    return nodes


def parse_sshare_output(
    entries: list[tuple[str, ...]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Parse sshare output into user and account priority data.

    Separates entries into user-level and account-level data based on
    whether the User field is empty (account) or populated (user).

    Args:
        entries: List of sshare tuples from get_fair_share_priority().
            Format: (Account, User, RawShares, NormShares, RawUsage,
            NormUsage, EffectvUsage, FairShare).

    Returns:
        Tuple of (user_priorities, account_priorities).
        Each is a list of dicts with keys matching SSHARE_FIELDS.
    """
    user_priorities: list[dict[str, str]] = []
    account_priorities: list[dict[str, str]] = []

    field_names = ["Account", "User", "RawShares", "NormShares", "RawUsage", "NormUsage", "EffectvUsage", "FairShare"]

    for entry in entries:
        if len(entry) < len(field_names):
            continue

        data = {field_names[i]: entry[i].strip() for i in range(len(field_names))}

        # User field empty means this is an account-level entry
        if not data["User"]:
            account_priorities.append(data)
        else:
            user_priorities.append(data)

    return user_priorities, account_priorities


def parse_sprio_output(entries: list[tuple[str, ...]]) -> list[dict[str, str]]:
    """Parse sprio output into job priority data.

    Args:
        entries: List of sprio tuples from get_pending_job_priority().
            Format: (JobID, User, Account, Priority, Age, FairShare,
            JobSize, Partition, QOS).

    Returns:
        List of dicts with keys matching SPRIO_FIELDS.
    """
    job_priorities: list[dict[str, str]] = []

    field_names = ["JobID", "User", "Account", "Priority", "Age", "FairShare", "JobSize", "Partition", "QOS"]

    for entry in entries:
        if len(entry) < len(field_names):
            continue

        data = {field_names[i]: entry[i].strip() for i in range(len(field_names))}
        job_priorities.append(data)

    # Sort by priority descending (highest priority first)
    def priority_sort_key(job: dict[str, str]) -> float:
        try:
            return float(job.get("Priority", "0"))
        except ValueError:
            return 0.0

    job_priorities.sort(key=priority_sort_key, reverse=True)

    return job_priorities
