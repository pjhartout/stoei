"""Formatting utilities for SLURM job information."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from stoei.slurm.parser import parse_scontrol_output

if TYPE_CHECKING:
    from stoei.widgets.user_overview import UserStats

# Fields categorized for better display
JOB_CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "identity": ("🏷️  Identity", ["JobId", "JobName", "UserId", "GroupId", "Account", "QOS"]),
    "status": (
        "📊 Status",
        ["JobState", "Reason", "ExitCode", "DerivedExitCode", "RunTime", "TimeLimit", "Restarts", "Requeue"],
    ),
    "resources": (
        "💻 Resources",
        [
            "Partition",
            "NumNodes",
            "NumCPUs",
            "NumTasks",
            "CPUs/Task",
            "TRES",
            "MinCPUsNode",
            "MinMemoryNode",
            "MinMemoryCPU",
            "ReqTRES",
            "AllocTRES",
            "Gres",
            "TresPerNode",
        ],
    ),
    "nodes": ("🖥️  Nodes", ["NodeList", "BatchHost", "ReqNodeList", "ExcNodeList", "Features", "Reservation"]),
    "timing": (
        "⏱️  Timing",
        [
            "SubmitTime",
            "EligibleTime",
            "AccrueTime",
            "StartTime",
            "EndTime",
            "Deadline",
            "SuspendTime",
            "PreemptTime",
            "PreemptEligibleTime",
            "LastSchedEval",
        ],
    ),
    "paths": ("📁 Paths", ["WorkDir", "StdErr", "StdOut", "StdIn", "Command", "BatchFlag"]),
    "scheduling": (
        "⚙️  Scheduling",
        [
            "Priority",
            "Nice",
            "Contiguous",
            "Licenses",
            "Network",
            "Power",
            "NtasksPerN:B:S:C",
            "CoreSpec",
            "Shared",
            "OverSubscribe",
        ],
    ),
}

# State color mapping using Rich markup
STATE_COLORS: dict[str, str] = {
    "RUNNING": "bold green",
    "PENDING": "bold yellow",
    "COMPLETED": "bold cyan",
    "FAILED": "bold red",
    "CANCELLED": "bold magenta",
    "TIMEOUT": "bold red",
    "NODE_FAIL": "bold red",
    "PREEMPTED": "bold yellow",
    "SUSPENDED": "bold yellow",
    "COMPLETING": "bold green",
}


def format_value(key: str, value: str) -> str:
    """Format a value with appropriate coloring based on key and content.

    Args:
        key: The field name.
        value: The field value.

    Returns:
        Formatted string with Rich markup.
    """
    if not value or value in ("(null)", "N/A", "None", ""):
        return "[italic](not set)[/italic]"

    # State coloring
    if key in ("JobState", "State"):
        base_state = value.split()[0]  # Handle "RUNNING by 12345" etc.
        color = STATE_COLORS.get(base_state, "white")
        formatted = f"[{color}]{value}[/{color}]"
    # Exit codes
    elif "ExitCode" in key:
        formatted = "[green]0:0 ✓[/green]" if value == "0:0" else f"[red]{value} ✗[/red]"
    # Paths
    elif key in ("WorkDir", "StdErr", "StdOut", "StdIn", "Command"):
        formatted = f"[italic cyan]{value}[/italic cyan]"
    # Time values
    elif "Time" in key and value not in ("Unknown", "N/A"):
        formatted = f"[yellow]{value}[/yellow]"
    # Numbers and resources
    elif key in ("NumNodes", "NumCPUs", "NumTasks", "Priority", "Nice", "Restarts"):
        formatted = f"[bold]{value}[/bold]"
    # TRES (trackable resources)
    elif "TRES" in key or key == "Gres":
        formatted = f"[magenta]{value}[/magenta]"
    # Node lists
    elif "Node" in key and key != "NumNodes":
        formatted = f"[blue]{value}[/blue]"
    else:
        formatted = value

    return formatted


def format_job_info(raw_output: str) -> str:
    """Format job info with categories and colors.

    Args:
        raw_output: Raw output from scontrol show jobid command.

    Returns:
        Formatted string with Rich markup for display.
    """
    parsed = parse_scontrol_output(raw_output)

    if not parsed:
        return "[italic]No job information could be parsed.[/italic]"

    lines: list[str] = []
    seen_keys: set[str] = set()

    # Display categorized fields
    for _category_id, (category_title, fields) in JOB_CATEGORIES.items():
        category_lines: list[str] = []
        for field in fields:
            if field in parsed:
                formatted = format_value(field, parsed[field])
                category_lines.append(f"  [bold cyan]{field:.<24}[/bold cyan] {formatted}")
                seen_keys.add(field)

        if category_lines:
            lines.append(f"\n[bold reverse] {category_title} [/bold reverse]")
            lines.extend(category_lines)

    # Display any remaining fields not in categories
    remaining = {k: v for k, v in parsed.items() if k not in seen_keys}
    if remaining:
        lines.append("\n[bold reverse] 📋 Other [/bold reverse]")
        for key, value in sorted(remaining.items()):
            formatted = format_value(key, value)
            lines.append(f"  [bold cyan]{key:.<24}[/bold cyan] {formatted}")

    return "\n".join(lines)


# Field mapping for sacct output to display names
SACCT_FIELD_DISPLAY: dict[str, str] = {
    "JobID": "Job ID",
    "JobName": "Job Name",
    "User": "User",
    "Account": "Account",
    "Partition": "Partition",
    "State": "State",
    "ExitCode": "Exit Code",
    "Start": "Start Time",
    "End": "End Time",
    "Elapsed": "Elapsed Time",
    "TimelimitRaw": "Time Limit (min)",
    "NNodes": "Nodes",
    "NCPUS": "CPUs",
    "NTasks": "Tasks",
    "ReqMem": "Requested Memory",
    "MaxRSS": "Max RSS",
    "MaxVMSize": "Max VM Size",
    "NodeList": "Node List",
    "WorkDir": "Work Directory",
    "StdOut": "StdOut Path",
    "StdErr": "StdErr Path",
    "Submit": "Submit Time",
    "Priority": "Priority",
    "QOS": "QOS",
}

# Categories for sacct fields
SACCT_CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "identity": ("🏷️  Identity", ["JobID", "JobName", "User", "Account", "QOS"]),
    "status": ("📊 Status", ["State", "ExitCode", "Priority"]),
    "resources": ("💻 Resources", ["Partition", "NNodes", "NCPUS", "NTasks", "ReqMem", "MaxRSS", "MaxVMSize"]),
    "nodes": ("🖥️  Nodes", ["NodeList"]),
    "timing": ("⏱️  Timing", ["Submit", "Start", "End", "Elapsed", "TimelimitRaw"]),
    "paths": ("📁 Paths", ["WorkDir", "StdOut", "StdErr"]),
}


def format_sacct_job_info(parsed: dict[str, str]) -> str:
    """Format sacct job info with categories and colors.

    Args:
        parsed: Dictionary of parsed sacct field values.

    Returns:
        Formatted string with Rich markup for display.
    """
    if not parsed:
        return "[italic]No job information could be parsed.[/italic]"

    lines: list[str] = []
    seen_keys: set[str] = set()

    # Add header indicating this is historical data
    lines.append("[dim italic](i) Historical data from sacct (job completed)[/dim italic]")

    # Display categorized fields
    for _category_id, (category_title, fields) in SACCT_CATEGORIES.items():
        category_lines: list[str] = []
        for field in fields:
            if field in parsed:
                display_name = SACCT_FIELD_DISPLAY.get(field, field)
                formatted = format_value(field, parsed[field])
                category_lines.append(f"  [bold cyan]{display_name:.<24}[/bold cyan] {formatted}")
                seen_keys.add(field)

        if category_lines:
            lines.append(f"\n[bold reverse] {category_title} [/bold reverse]")
            lines.extend(category_lines)

    # Display any remaining fields not in categories
    remaining = {k: v for k, v in parsed.items() if k not in seen_keys}
    if remaining:
        lines.append("\n[bold reverse] 📋 Other [/bold reverse]")
        for key, value in sorted(remaining.items()):
            display_name = SACCT_FIELD_DISPLAY.get(key, key)
            formatted = format_value(key, value)
            lines.append(f"  [bold cyan]{display_name:.<24}[/bold cyan] {formatted}")

    return "\n".join(lines)


# Categories for node fields
NODE_CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "identity": ("🏷️  Identity", ["NodeName", "NodeAddr", "NodeHostName", "Arch", "OS", "Version"]),
    "status": ("📊 Status", ["State", "Reason", "Owner", "MCS_label"]),
    "resources": (
        "💻 Resources",
        [
            "CPUTot",
            "CPUAlloc",
            "CPULoad",
            "CPUEfctv",
            "RealMemory",
            "AllocMem",
            "FreeMem",
            "CfgTRES",
            "AllocTRES",
            "Gres",
            "TmpDisk",
        ],
    ),
    "hardware": (
        "🔧 Hardware",
        [
            "CoresPerSocket",
            "Sockets",
            "Boards",
            "ThreadsPerCore",
            "Weight",
            "AvailableFeatures",
            "ActiveFeatures",
        ],
    ),
    "partitions": ("📦 Partitions", ["Partitions"]),
    "timing": (
        "⏱️  Timing",
        [
            "BootTime",
            "SlurmdStartTime",
            "LastBusyTime",
            "ResumeAfterTime",
        ],
    ),
    "power": ("⚡ Power", ["CurrentWatts", "AveWatts"]),
}


def format_node_info(raw_output: str) -> str:
    """Format node info with categories and colors.

    Args:
        raw_output: Raw output from scontrol show node command.

    Returns:
        Formatted string with Rich markup for display.
    """
    parsed = parse_scontrol_output(raw_output)

    if not parsed:
        return "[italic]No node information could be parsed.[/italic]"

    lines: list[str] = []
    seen_keys: set[str] = set()

    # Display categorized fields
    for _category_id, (category_title, fields) in NODE_CATEGORIES.items():
        category_lines: list[str] = []
        for field in fields:
            if field in parsed:
                formatted = format_value(field, parsed[field])
                category_lines.append(f"  [bold cyan]{field:.<24}[/bold cyan] {formatted}")
                seen_keys.add(field)

        if category_lines:
            lines.append(f"\n[bold reverse] {category_title} [/bold reverse]")
            lines.extend(category_lines)

    # Display any remaining fields not in categories
    remaining = {k: v for k, v in parsed.items() if k not in seen_keys}
    if remaining:
        lines.append("\n[bold reverse] 📋 Other [/bold reverse]")
        for key, value in sorted(remaining.items()):
            formatted = format_value(key, value)
            lines.append(f"  [bold cyan]{key:.<24}[/bold cyan] {formatted}")

    return "\n".join(lines)


def _format_compact_time(timestamp_str: str) -> str:
    """Format a SLURM timestamp to compact display format.

    Args:
        timestamp_str: SLURM timestamp string (format: 2024-01-15T14:30:00).

    Returns:
        Compact time string (HH:MM if today, MM-DD HH:MM otherwise).
        Returns empty string if timestamp cannot be parsed.
    """
    if not timestamp_str or timestamp_str.lower() in ("unknown", "n/a", "none", ""):
        return ""

    try:
        # Parse SLURM timestamp format
        dt = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S")
        today = datetime.now().date()

        if dt.date() == today:
            return dt.strftime("%H:%M")
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return ""


def format_compact_timeline(
    submit_time: str,
    start_time: str,
    end_time: str,
    state: str,
    restarts: int = 0,
) -> str:
    """Format job times into a compact timeline string.

    Args:
        submit_time: Submit timestamp string.
        start_time: Start timestamp string.
        end_time: End timestamp string.
        state: Job state string.
        restarts: Number of job restarts/requeues.

    Returns:
        Compact timeline like "14:30 → 14:35" or "14:30 ⏳".
    """
    submit_fmt = _format_compact_time(submit_time)
    start_fmt = _format_compact_time(start_time)
    end_fmt = _format_compact_time(end_time)

    state_upper = state.upper()

    # Build timeline based on state and available times
    if not submit_fmt:
        return "—"

    result = ""

    if "PENDING" in state_upper:
        # Pending: show submit time with waiting icon
        result = f"{submit_fmt} ⏳"
    elif "RUNNING" in state_upper:
        # Running: show submit → start
        result = f"{submit_fmt} → {start_fmt}" if start_fmt else f"{submit_fmt} ⏳"
    elif end_fmt:
        # Completed/Failed/etc: show full timeline submit → start → end
        result = f"{submit_fmt} → {start_fmt} → {end_fmt}" if start_fmt else f"{submit_fmt} → {end_fmt}"
    elif start_fmt:
        # Has start but no end
        result = f"{submit_fmt} → {start_fmt}"
    else:
        # Only submit time available
        result = submit_fmt

    # Append requeue indicator if restarts > 0
    if restarts > 0:
        result = f"{result}  ↻ {restarts}"

    return result


# Display width constants for user info job list
_USER_INFO_JOBID_WIDTH = 12
_USER_INFO_NAME_WIDTH = 15
_USER_INFO_PARTITION_WIDTH = 12
_USER_INFO_TIME_WIDTH = 10
_USER_INFO_MIN_JOB_FIELDS = 6
_USER_INFO_STATE_INDEX = 3


def format_user_info(
    username: str,
    user_stats: UserStats,
    jobs: list[tuple[str, ...]],
) -> str:
    """Format user information with their jobs for display.

    Args:
        username: The username.
        user_stats: Aggregated user statistics from UserStats.
        jobs: List of job tuples for this user.
            Each tuple: (JobID, Name, Partition, State, Time, Nodes, NodeList, TRES).

    Returns:
        Formatted string with Rich markup for display.
    """
    lines: list[str] = []

    # Summary section
    lines.append("\n[bold reverse] 👤 User Summary [/bold reverse]")
    lines.append(f"  [bold cyan]{'Username':.<24}[/bold cyan] [bold]{username}[/bold]")
    lines.append(f"  [bold cyan]{'Total Jobs':.<24}[/bold cyan] [bold]{user_stats.job_count}[/bold]")
    lines.append(f"  [bold cyan]{'Total CPUs':.<24}[/bold cyan] {user_stats.total_cpus}")
    lines.append(f"  [bold cyan]{'Total Memory (GB)':.<24}[/bold cyan] {user_stats.total_memory_gb:.1f}")
    lines.append(f"  [bold cyan]{'Total GPUs':.<24}[/bold cyan] {user_stats.total_gpus}")
    if user_stats.gpu_types:
        lines.append(f"  [bold cyan]{'GPU Types':.<24}[/bold cyan] [magenta]{user_stats.gpu_types}[/magenta]")
    lines.append(f"  [bold cyan]{'Total Nodes':.<24}[/bold cyan] {user_stats.total_nodes}")

    # Jobs by state
    running_count = 0
    pending_count = 0

    for job in jobs:
        if len(job) > _USER_INFO_STATE_INDEX:
            state = job[_USER_INFO_STATE_INDEX].strip().upper()
            if state in ("RUNNING", "R"):
                running_count += 1
            elif state in ("PENDING", "PD"):
                pending_count += 1

    lines.append("\n[bold reverse] 📊 Jobs by State [/bold reverse]")
    lines.append(f"  [bold cyan]{'Running':.<24}[/bold cyan] [bold green]{running_count}[/bold green]")
    lines.append(f"  [bold cyan]{'Pending':.<24}[/bold cyan] [bold yellow]{pending_count}[/bold yellow]")

    # Jobs list
    if jobs:
        lines.append("\n[bold reverse] 📋 Job List [/bold reverse]")
        lines.append("")
        # Header
        lines.append(
            f"  [dim]{'JobID':<12} {'Name':<15} {'State':<8} {'Partition':<12} {'Time':<10} {'Nodes':<6}[/dim]"
        )
        lines.append(f"  [dim]{'─' * 70}[/dim]")

        for job in jobs:
            if len(job) < _USER_INFO_MIN_JOB_FIELDS:
                continue

            job_id = job[0][:_USER_INFO_JOBID_WIDTH] if len(job[0]) > _USER_INFO_JOBID_WIDTH else job[0]
            name = job[1][:_USER_INFO_NAME_WIDTH] if len(job[1]) > _USER_INFO_NAME_WIDTH else job[1]
            partition = job[2][:_USER_INFO_PARTITION_WIDTH] if len(job[2]) > _USER_INFO_PARTITION_WIDTH else job[2]
            state = job[3]
            time_used = job[4][:_USER_INFO_TIME_WIDTH] if len(job[4]) > _USER_INFO_TIME_WIDTH else job[4]
            nodes = job[5]

            # Color-code the state
            state_upper = state.strip().upper()
            if state_upper in ("RUNNING", "R"):
                state_display = f"[bold green]{state:<8}[/bold green]"
            elif state_upper in ("PENDING", "PD"):
                state_display = f"[bold yellow]{state:<8}[/bold yellow]"
            else:
                state_display = f"{state:<8}"

            lines.append(f"  {job_id:<12} {name:<15} {state_display} {partition:<12} {time_used:<10} {nodes:<6}")
    else:
        lines.append("\n[italic]No active jobs found for this user.[/italic]")

    return "\n".join(lines)
