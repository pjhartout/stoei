"""Formatting utilities for SLURM job information."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from stoei.colors import FALLBACK_COLORS, ThemeColors
from stoei.slurm.energy import ENERGY_KWH_THRESHOLD, ENERGY_MWH_THRESHOLD
from stoei.slurm.gpu_parser import calculate_total_gpus
from stoei.slurm.parser import parse_scontrol_output, parse_tres_resources

if TYPE_CHECKING:
    from stoei.widgets.user_overview import UserEnergyStats, UserPendingStats, UserStats


def _get_default_colors() -> ThemeColors:
    """Get default theme colors for formatting.

    Returns:
        ThemeColors instance with fallback colors.
    """
    return ThemeColors(
        success=FALLBACK_COLORS["success"],
        warning=FALLBACK_COLORS["warning"],
        error=FALLBACK_COLORS["error"],
        primary=FALLBACK_COLORS["primary"],
        accent=FALLBACK_COLORS["accent"],
        secondary=FALLBACK_COLORS["secondary"],
        foreground=FALLBACK_COLORS["foreground"],
        text_muted=FALLBACK_COLORS["text_muted"],
        background=FALLBACK_COLORS["background"],
        surface=FALLBACK_COLORS["surface"],
        panel=FALLBACK_COLORS["panel"],
        border=FALLBACK_COLORS["border"],
    )


# Fields categorized for better display
JOB_CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "identity": ("Identity", ["JobId", "JobName", "UserId", "GroupId", "Account", "QOS"]),
    "status": (
        "Status",
        ["JobState", "Reason", "ExitCode", "DerivedExitCode", "RunTime", "TimeLimit", "Restarts", "Requeue"],
    ),
    "resources": (
        "Resources",
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
    "nodes": ("Nodes", ["NodeList", "BatchHost", "ReqNodeList", "ExcNodeList", "Features", "Reservation"]),
    "timing": (
        "Timing",
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
    "paths": ("Paths", ["WorkDir", "StdErr", "StdOut", "StdIn", "Command", "BatchFlag"]),
    "scheduling": (
        "Scheduling",
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


def _get_state_color(state: str, colors: ThemeColors) -> str:
    """Get the hex color for a job state.

    Args:
        state: Job state string (e.g., 'RUNNING', 'PENDING').
        colors: Theme colors to use.

    Returns:
        Hex color string for the state.
    """
    return colors.state_color(state)


def format_value(key: str, value: str, colors: ThemeColors | None = None) -> str:
    """Format a value with appropriate coloring based on key and content.

    Args:
        key: The field name.
        value: The field value.
        colors: Optional theme colors. Uses fallback colors if not provided.

    Returns:
        Formatted string with Rich markup.
    """
    if colors is None:
        colors = _get_default_colors()

    if not value or value in ("(null)", "N/A", "None", ""):
        return "[italic](not set)[/italic]"

    # State coloring
    if key in ("JobState", "State"):
        base_state = value.split(maxsplit=1)[0]  # Handle "RUNNING by 12345" etc.
        color = _get_state_color(base_state, colors)
        formatted = f"[bold {color}]{value}[/bold {color}]"
    # Exit codes
    elif "ExitCode" in key:
        if value == "0:0":
            formatted = f"[{colors.success}]0:0 ✓[/{colors.success}]"
        else:
            formatted = f"[{colors.error}]{value} ✗[/{colors.error}]"
    # Paths
    elif key in ("WorkDir", "StdErr", "StdOut", "StdIn", "Command"):
        formatted = f"[italic {colors.primary}]{value}[/italic {colors.primary}]"
    # Time values
    elif "Time" in key and value not in ("Unknown", "N/A"):
        formatted = f"[{colors.warning}]{value}[/{colors.warning}]"
    # Numbers and resources
    elif key in ("NumNodes", "NumCPUs", "NumTasks", "Priority", "Nice", "Restarts"):
        formatted = f"[bold]{value}[/bold]"
    # TRES (trackable resources)
    elif "TRES" in key or key == "Gres":
        formatted = f"[{colors.accent}]{value}[/{colors.accent}]"
    # Node lists
    elif "Node" in key and key != "NumNodes":
        formatted = f"[{colors.primary}]{value}[/{colors.primary}]"
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
        lines.append("\n[bold reverse] Other [/bold reverse]")
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
    "identity": ("Identity", ["JobID", "JobName", "User", "Account", "QOS"]),
    "status": ("Status", ["State", "ExitCode", "Priority"]),
    "resources": ("Resources", ["Partition", "NNodes", "NCPUS", "NTasks", "ReqMem", "MaxRSS", "MaxVMSize"]),
    "nodes": ("Nodes", ["NodeList"]),
    "timing": ("Timing", ["Submit", "Start", "End", "Elapsed", "TimelimitRaw"]),
    "paths": ("Paths", ["WorkDir", "StdOut", "StdErr"]),
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
        lines.append("\n[bold reverse] Other [/bold reverse]")
        for key, value in sorted(remaining.items()):
            display_name = SACCT_FIELD_DISPLAY.get(key, key)
            formatted = format_value(key, value)
            lines.append(f"  [bold cyan]{display_name:.<24}[/bold cyan] {formatted}")

    return "\n".join(lines)


# Categories for node fields
NODE_CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "identity": ("Identity", ["NodeName", "NodeAddr", "NodeHostName", "Arch", "OS", "Version"]),
    "status": ("Status", ["State", "Reason", "Owner", "MCS_label"]),
    "resources": (
        "Resources",
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
        "Hardware",
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
    "partitions": ("Partitions", ["Partitions"]),
    "timing": (
        "Timing",
        [
            "BootTime",
            "SlurmdStartTime",
            "LastBusyTime",
            "ResumeAfterTime",
        ],
    ),
    "power": ("Power", ["CurrentWatts", "AveWatts"]),
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
        lines.append("\n[bold reverse] Other [/bold reverse]")
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
_USER_INFO_STATE_WIDTH = 8
_USER_INFO_NODES_WIDTH = 6
_USER_INFO_NODELIST_WIDTH = 20

# Display widths for user priority table
_USER_INFO_PRIORITY_WIDTH = 10
_USER_INFO_AGE_WIDTH = 8
_USER_INFO_FAIR_SHARE_WIDTH = 10
_USER_INFO_JOB_SIZE_WIDTH = 10

# Fair-share thresholds for color coding
_FAIR_SHARE_SUCCESS_THRESHOLD = 0.5
_FAIR_SHARE_WARNING_THRESHOLD = 0.2

# Display limits for list sections
_USER_INFO_MAX_PRIORITY_JOBS = 10
_ACCOUNT_INFO_MAX_USERS = 15
_ACCOUNT_INFO_MAX_PRIORITY_JOBS = 15
_ACCOUNT_INFO_MAX_RUNNING_JOBS = 20

# Display widths for account info tables
_ACCOUNT_INFO_USER_WIDTH = 12
_ACCOUNT_INFO_JOBID_WIDTH = 12
_ACCOUNT_INFO_PRIORITY_WIDTH = 10
_ACCOUNT_INFO_AGE_WIDTH = 8
_ACCOUNT_INFO_PARTITION_WIDTH = 12
_ACCOUNT_INFO_NAME_WIDTH = 15
_ACCOUNT_INFO_TIME_WIDTH = 10
_ACCOUNT_INFO_NODES_WIDTH = 6
_ACCOUNT_INFO_TIME_FIELD_INDEX = 5
_ACCOUNT_INFO_NODES_FIELD_INDEX = 6


def _truncate(value: str, width: int) -> str:
    """Truncate a string to a maximum width.

    Args:
        value: The string to truncate.
        width: Maximum width.

    Returns:
        The truncated string (or original if already short enough).
    """
    return value[:width] if len(value) > width else value


def _safe_float(value: str, default: float = 0.0) -> float:
    """Parse a float from a string safely.

    Args:
        value: String value to parse.
        default: Default value if parsing fails.

    Returns:
        Parsed float or default.
    """
    try:
        return float(value)
    except ValueError:
        return default


def _format_fair_share_value(
    fair_share: str,
    colors: ThemeColors,
    *,
    width: int | None = None,
    bold: bool = True,
) -> str:
    """Format a fair-share factor with color coding when numeric.

    Args:
        fair_share: Fair-share factor as string.
        colors: Theme colors.
        width: Optional display width (pads with spaces for alignment).
        bold: Whether to render the value in bold.

    Returns:
        A formatted string (possibly with Rich markup color).
    """
    raw = fair_share.strip()
    fair_share_val = _safe_float(raw, default=float("nan"))
    display = _truncate(raw, width) if width is not None else raw
    if width is not None:
        display = f"{display:<{width}}"
    if math.isnan(fair_share_val):
        return display

    if fair_share_val >= _FAIR_SHARE_SUCCESS_THRESHOLD:
        color = colors.success
    elif fair_share_val >= _FAIR_SHARE_WARNING_THRESHOLD:
        color = colors.warning
    else:
        color = colors.error

    if bold:
        return f"[bold {color}]{display}[/bold {color}]"
    return f"[{color}]{display}[/{color}]"


def fair_share_color(fair_share: str, colors: ThemeColors) -> str:
    """Get the appropriate color for a fair-share value.

    Args:
        fair_share: Fair-share factor as string.
        colors: Theme colors.

    Returns:
        Hex color string based on the fair-share thresholds.
    """
    val = _safe_float(fair_share, default=float("nan"))
    if math.isnan(val):
        return colors.foreground
    if val >= _FAIR_SHARE_SUCCESS_THRESHOLD:
        return colors.success
    if val >= _FAIR_SHARE_WARNING_THRESHOLD:
        return colors.warning
    return colors.error


def fair_share_status(fair_share: str) -> str:
    """Get a human-readable status label for a fair-share value.

    Args:
        fair_share: Fair-share factor as string.

    Returns:
        Status label: "Under-served", "Fair", or "Over-served".
    """
    val = _safe_float(fair_share, default=float("nan"))
    if math.isnan(val):
        return ""
    if val >= _FAIR_SHARE_SUCCESS_THRESHOLD:
        return "Under-served"
    if val >= _FAIR_SHARE_WARNING_THRESHOLD:
        return "Fair"
    return "Over-served"


def _format_energy_wh(wh: float) -> str:
    """Format an energy value in Wh as Wh/kWh/MWh.

    Args:
        wh: Energy in watt-hours.

    Returns:
        Human-friendly energy string.
    """
    if wh >= ENERGY_MWH_THRESHOLD:
        return f"{wh / ENERGY_MWH_THRESHOLD:.2f} MWh"
    if wh >= ENERGY_KWH_THRESHOLD:
        return f"{wh / ENERGY_KWH_THRESHOLD:.2f} kWh"
    return f"{wh:.1f} Wh"


def _parse_node_count(nodes_str: str) -> int:
    """Parse node count from a node count string.

    Args:
        nodes_str: Node string in format "4" or "4-8".

    Returns:
        Parsed number of nodes, or 0 if parsing fails.
    """
    try:
        if "-" in nodes_str:
            parts = nodes_str.split("-")
            range_parts_count = 2
            if len(parts) == range_parts_count:
                start = int(parts[0])
                end = int(parts[1])
                return end - start + 1
        return int(nodes_str)
    except ValueError:
        return 0


@dataclass(frozen=True, slots=True)
class AccountResourceUsage:
    """Aggregate resource usage across a set of running jobs."""

    total_cpus: int
    total_memory_gb: float
    total_gpus: int
    total_nodes: int


def format_user_info(  # noqa: PLR0913, PLR0912, PLR0915
    username: str,
    user_stats: UserStats,
    jobs: list[tuple[str, ...]],
    colors: ThemeColors | None = None,
    pending_stats: UserPendingStats | None = None,
    energy_stats: UserEnergyStats | None = None,
    priority_info: dict[str, str] | None = None,
    job_priorities: list[dict[str, str]] | None = None,
) -> str:
    """Format user information with their jobs for display.

    Args:
        username: The username.
        user_stats: Aggregated user statistics from UserStats.
        jobs: List of job tuples for this user.
            Each tuple: (JobID, Name, Partition, State, Time, Nodes, NodeList, TRES).
        colors: Optional theme colors. Uses fallback colors if not provided.
        pending_stats: Optional pending job statistics.
        energy_stats: Optional energy usage statistics.
        priority_info: Optional fair-share priority information.
        job_priorities: Optional list of pending job priority factors.

    Returns:
        Formatted string with Rich markup for display.
    """
    if colors is None:
        colors = _get_default_colors()

    lines: list[str] = []
    c = colors  # Short alias for cleaner formatting

    # Summary section
    lines.append("\n[bold reverse] User Summary [/bold reverse]")
    lines.append(f"  [bold {c.primary}]{'Username':.<24}[/bold {c.primary}] [bold]{username}[/bold]")
    lines.append(f"  [bold {c.primary}]{'Running Jobs':.<24}[/bold {c.primary}] [bold]{user_stats.job_count}[/bold]")
    lines.append(f"  [bold {c.primary}]{'Total CPUs':.<24}[/bold {c.primary}] {user_stats.total_cpus}")
    lines.append(f"  [bold {c.primary}]{'Total Memory (GB)':.<24}[/bold {c.primary}] {user_stats.total_memory_gb:.1f}")
    lines.append(f"  [bold {c.primary}]{'Total GPUs':.<24}[/bold {c.primary}] {user_stats.total_gpus}")
    if user_stats.gpu_types:
        lines.append(
            f"  [bold {c.primary}]{'GPU Types':.<24}[/bold {c.primary}] [{c.accent}]{user_stats.gpu_types}[/{c.accent}]"
        )
    lines.append(f"  [bold {c.primary}]{'Total Nodes':.<24}[/bold {c.primary}] {user_stats.total_nodes}")
    if user_stats.node_names:
        lines.append(
            f"  [bold {c.primary}]{'NodeList':.<24}[/bold {c.primary}] [{c.accent}]{user_stats.node_names}[/{c.accent}]"
        )

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

    lines.append("\n[bold reverse] Jobs by State [/bold reverse]")
    lines.append(
        f"  [bold {c.primary}]{'Running':.<24}[/bold {c.primary}] [bold {c.success}]{running_count}[/bold {c.success}]"
    )
    lines.append(
        f"  [bold {c.primary}]{'Pending':.<24}[/bold {c.primary}] [bold {c.warning}]{pending_count}[/bold {c.warning}]"
    )

    # Pending resources section
    if pending_stats:
        lines.append("\n[bold reverse] Pending Resources [/bold reverse]")
        lines.append(
            f"  [bold {c.primary}]{'Pending Jobs':.<24}[/bold {c.primary}] "
            f"[bold {c.warning}]{pending_stats.pending_job_count}[/bold {c.warning}]"
        )
        lines.append(f"  [bold {c.primary}]{'Requested CPUs':.<24}[/bold {c.primary}] {pending_stats.pending_cpus}")
        lines.append(
            f"  [bold {c.primary}]{'Requested Memory (GB)':.<24}[/bold {c.primary}] "
            f"{pending_stats.pending_memory_gb:.1f}"
        )
        lines.append(f"  [bold {c.primary}]{'Requested GPUs':.<24}[/bold {c.primary}] {pending_stats.pending_gpus}")
        if pending_stats.pending_gpu_types:
            lines.append(
                f"  [bold {c.primary}]{'GPU Types':.<24}[/bold {c.primary}] "
                f"[{c.accent}]{pending_stats.pending_gpu_types}[/{c.accent}]"
            )

    # Fair-share priority section
    if priority_info:
        lines.append("\n[bold reverse] Fair-Share Priority [/bold reverse]")
        lines.append(f"  [bold {c.primary}]{'Account':.<24}[/bold {c.primary}] {priority_info['account']}")
        lines.append(f"  [bold {c.primary}]{'Raw Shares':.<24}[/bold {c.primary}] {priority_info['raw_shares']}")
        lines.append(f"  [bold {c.primary}]{'Norm Shares':.<24}[/bold {c.primary}] {priority_info['norm_shares']}")
        lines.append(f"  [bold {c.primary}]{'Raw Usage':.<24}[/bold {c.primary}] {priority_info['raw_usage']}")
        lines.append(
            f"  [bold {c.primary}]{'Effective Usage':.<24}[/bold {c.primary}] {priority_info['effective_usage']}"
        )
        fair_share = priority_info["fair_share"]
        fair_share_label = f"  [bold {c.primary}]{'Fair-Share Factor':.<24}[/bold {c.primary}] "
        lines.append(f"{fair_share_label}{_format_fair_share_value(fair_share, c)}")

    # Energy consumption section
    if energy_stats:
        lines.append("\n[bold reverse] Energy (6 months) [/bold reverse]")
        energy_display = _format_energy_wh(energy_stats.total_energy_wh)
        lines.append(
            f"  [bold {c.primary}]{'Total Energy':.<24}[/bold {c.primary}] [{c.accent}]{energy_display}[/{c.accent}]"
        )
        lines.append(f"  [bold {c.primary}]{'Completed Jobs':.<24}[/bold {c.primary}] {energy_stats.job_count}")
        lines.append(f"  [bold {c.primary}]{'GPU-Hours':.<24}[/bold {c.primary}] {energy_stats.gpu_hours:.1f}")
        lines.append(f"  [bold {c.primary}]{'CPU-Hours':.<24}[/bold {c.primary}] {energy_stats.cpu_hours:.1f}")

    # Pending job priorities section
    if job_priorities:
        lines.append("\n[bold reverse] Pending Job Priorities [/bold reverse]")
        lines.append("")
        # Header
        lines.append(
            "  [dim]"
            f"{'JobID':<{_USER_INFO_JOBID_WIDTH}} "
            f"{'Priority':<{_USER_INFO_PRIORITY_WIDTH}} "
            f"{'Age':<{_USER_INFO_AGE_WIDTH}} "
            f"{'FairShare':<{_USER_INFO_FAIR_SHARE_WIDTH}} "
            f"{'JobSize':<{_USER_INFO_JOB_SIZE_WIDTH}} "
            f"{'Partition':<{_USER_INFO_PARTITION_WIDTH}}"
            "[/dim]"
        )
        lines.append(f"  [dim]{'─' * 70}[/dim]")

        # Sort by priority descending
        sorted_priorities = sorted(
            job_priorities,
            key=lambda p: _safe_float(p.get("priority", "0")),
            reverse=True,
        )

        # Show top jobs
        for prio in sorted_priorities[:_USER_INFO_MAX_PRIORITY_JOBS]:
            job_id = _truncate(prio["job_id"], _USER_INFO_JOBID_WIDTH)
            priority = _truncate(prio["priority"], _USER_INFO_PRIORITY_WIDTH)
            age = _truncate(prio["age"], _USER_INFO_AGE_WIDTH)
            fair_share = _truncate(prio["fair_share"], _USER_INFO_FAIR_SHARE_WIDTH)
            job_size = _truncate(prio["job_size"], _USER_INFO_JOB_SIZE_WIDTH)
            partition = _truncate(prio["partition"], _USER_INFO_PARTITION_WIDTH)

            lines.append(f"  {job_id:<12} {priority:<10} {age:<8} {fair_share:<10} {job_size:<10} {partition:<12}")

        if len(job_priorities) > _USER_INFO_MAX_PRIORITY_JOBS:
            lines.append(f"  [dim]... and {len(job_priorities) - _USER_INFO_MAX_PRIORITY_JOBS} more pending jobs[/dim]")

    # Jobs list
    if jobs:
        lines.append("\n[bold reverse] Job List [/bold reverse]")
        lines.append("")
        # Header
        lines.append(
            "  [dim]"
            f"{'JobID':<{_USER_INFO_JOBID_WIDTH}} "
            f"{'Name':<{_USER_INFO_NAME_WIDTH}} "
            f"{'State':<{_USER_INFO_STATE_WIDTH}} "
            f"{'Partition':<{_USER_INFO_PARTITION_WIDTH}} "
            f"{'Time':<{_USER_INFO_TIME_WIDTH}} "
            f"{'Nodes':<{_USER_INFO_NODES_WIDTH}} "
            f"{'NodeList':<{_USER_INFO_NODELIST_WIDTH}}"
            "[/dim]"
        )
        lines.append(f"  [dim]{'─' * 92}[/dim]")

        for job in jobs:
            if len(job) < _USER_INFO_MIN_JOB_FIELDS:
                continue

            job_id = job[0][:_USER_INFO_JOBID_WIDTH] if len(job[0]) > _USER_INFO_JOBID_WIDTH else job[0]
            name = job[1][:_USER_INFO_NAME_WIDTH] if len(job[1]) > _USER_INFO_NAME_WIDTH else job[1]
            partition = job[2][:_USER_INFO_PARTITION_WIDTH] if len(job[2]) > _USER_INFO_PARTITION_WIDTH else job[2]
            state = job[3]
            time_used = job[4][:_USER_INFO_TIME_WIDTH] if len(job[4]) > _USER_INFO_TIME_WIDTH else job[4]
            nodes = job[5]
            nodelist_index = 6
            nodelist = job[nodelist_index] if len(job) > nodelist_index else ""
            nodelist = nodelist[:_USER_INFO_NODELIST_WIDTH]

            # Color-code the state
            state_upper = state.strip().upper()
            state_color = colors.state_color(state_upper)
            if state_upper in ("RUNNING", "R", "PENDING", "PD"):
                state_display = f"[bold {state_color}]{state:<{_USER_INFO_STATE_WIDTH}}[/bold {state_color}]"
            else:
                state_display = f"{state:<{_USER_INFO_STATE_WIDTH}}"

            lines.append(
                f"  {job_id:<12} {name:<15} {state_display} {partition:<12} "
                f"{time_used:<10} {nodes:<6} {nodelist:<{_USER_INFO_NODELIST_WIDTH}}"
            )
    else:
        lines.append("\n[italic]No active jobs found for this user.[/italic]")

    return "\n".join(lines)


def format_account_info(  # noqa: PLR0913, PLR0912, PLR0915
    account_name: str,
    account_priority: dict[str, str],
    users_in_account: list[dict[str, str]],
    running_jobs: list[tuple[str, ...]],
    pending_jobs: list[tuple[str, ...]],
    job_priorities: list[dict[str, str]] | None = None,
    colors: ThemeColors | None = None,
) -> str:
    """Format account/institute information for display.

    Args:
        account_name: The account/institute name.
        account_priority: Account-level fair-share priority info from sshare.
        users_in_account: List of users in this account with their priority info.
        running_jobs: List of running jobs for users in this account.
        pending_jobs: List of pending jobs for users in this account.
        job_priorities: Optional list of pending job priority factors.
        colors: Optional theme colors. Uses fallback colors if not provided.

    Returns:
        Formatted string with Rich markup for display.
    """
    if colors is None:
        colors = _get_default_colors()

    lines: list[str] = []
    c = colors  # Short alias for cleaner formatting

    # Account Summary section
    lines.append("\n[bold reverse] Account Summary [/bold reverse]")
    lines.append(f"  [bold {c.primary}]{'Account Name':.<24}[/bold {c.primary}] [bold]{account_name}[/bold]")
    lines.append(
        f"  [bold {c.primary}]{'Users in Account':.<24}[/bold {c.primary}] [bold]{len(users_in_account)}[/bold]"
    )
    lines.append(
        f"  [bold {c.primary}]{'Running Jobs':.<24}[/bold {c.primary}] "
        f"[bold {c.success}]{len(running_jobs)}[/bold {c.success}]"
    )
    lines.append(
        f"  [bold {c.primary}]{'Pending Jobs':.<24}[/bold {c.primary}] "
        f"[bold {c.warning}]{len(pending_jobs)}[/bold {c.warning}]"
    )

    # Account Fair-Share Priority section
    if account_priority:
        lines.append("\n[bold reverse] Account Fair-Share Priority [/bold reverse]")
        lines.append(
            f"  [bold {c.primary}]{'Raw Shares':.<24}[/bold {c.primary}] {account_priority.get('raw_shares', 'N/A')}"
        )
        lines.append(
            f"  [bold {c.primary}]{'Norm Shares':.<24}[/bold {c.primary}] {account_priority.get('norm_shares', 'N/A')}"
        )
        lines.append(
            f"  [bold {c.primary}]{'Raw Usage':.<24}[/bold {c.primary}] {account_priority.get('raw_usage', 'N/A')}"
        )
        lines.append(
            f"  [bold {c.primary}]{'Effective Usage':.<24}[/bold {c.primary}] "
            f"{account_priority.get('effective_usage', 'N/A')}"
        )
        fair_share = account_priority.get("fair_share", "N/A")
        fair_share_label = f"  [bold {c.primary}]{'Fair-Share Factor':.<24}[/bold {c.primary}] "
        lines.append(f"{fair_share_label}{_format_fair_share_value(fair_share, c)}")

    # Calculate aggregate resource usage from running jobs
    min_running_job_fields = 9
    nodes_index = 6
    tres_index = 8

    total_cpus = 0
    total_memory_gb = 0.0
    total_gpus = 0
    total_nodes = 0

    for job in running_jobs:
        if len(job) < min_running_job_fields:
            continue

        tres_str = job[tres_index].strip()
        cpus, memory_gb, gpu_entries = parse_tres_resources(tres_str)
        total_cpus += cpus
        total_memory_gb += memory_gb
        total_gpus += calculate_total_gpus(gpu_entries)

        nodes_str = job[nodes_index].strip()
        total_nodes += _parse_node_count(nodes_str)

    # Resource Usage section
    lines.append("\n[bold reverse] Current Resource Usage [/bold reverse]")
    lines.append(f"  [bold {c.primary}]{'Total CPUs':.<24}[/bold {c.primary}] {total_cpus}")
    lines.append(f"  [bold {c.primary}]{'Total Memory (GB)':.<24}[/bold {c.primary}] {total_memory_gb:.1f}")
    lines.append(f"  [bold {c.primary}]{'Total GPUs':.<24}[/bold {c.primary}] {total_gpus}")
    lines.append(f"  [bold {c.primary}]{'Total Nodes':.<24}[/bold {c.primary}] {total_nodes}")

    # Users in Account section
    if users_in_account:
        lines.append("\n[bold reverse] Users in Account [/bold reverse]")
        lines.append("")
        # Header
        lines.append(
            f"  [dim]{'User':<15} {'RawShares':<12} {'NormShares':<12} {'EffectvUsage':<12} {'FairShare':<10}[/dim]"
        )
        lines.append(f"  [dim]{'─' * 65}[/dim]")

        # Sort by fair share descending
        sorted_users = sorted(
            users_in_account,
            key=lambda u: _safe_float(u.get("fair_share", "0")),
            reverse=True,
        )

        for user in sorted_users[:_ACCOUNT_INFO_MAX_USERS]:
            username = user.get("username", "")[:_USER_INFO_NAME_WIDTH]
            raw_shares = user.get("raw_shares", "")[:12]
            norm_shares = user.get("norm_shares", "")[:12]
            effective_usage = user.get("effective_usage", "")[:12]
            fair_share = user.get("fair_share", "")
            fs_display = _format_fair_share_value(
                fair_share,
                c,
                width=_USER_INFO_FAIR_SHARE_WIDTH,
                bold=False,
            )

            lines.append(f"  {username:<15} {raw_shares:<12} {norm_shares:<12} {effective_usage:<12} {fs_display}")

        if len(users_in_account) > _ACCOUNT_INFO_MAX_USERS:
            lines.append(f"  [dim]... and {len(users_in_account) - _ACCOUNT_INFO_MAX_USERS} more users[/dim]")

    # Pending Job Priorities section
    if job_priorities:
        lines.append("\n[bold reverse] Pending Job Priorities [/bold reverse]")
        lines.append("")
        # Header
        lines.append(
            f"  [dim]{'JobID':<12} {'User':<12} {'Priority':<10} {'Age':<8} {'FairShare':<10} {'Partition':<12}[/dim]"
        )
        lines.append(f"  [dim]{'─' * 70}[/dim]")

        # Sort by priority descending
        sorted_priorities = sorted(
            job_priorities,
            key=lambda p: _safe_float(p.get("priority", "0")),
            reverse=True,
        )

        for prio in sorted_priorities[:_ACCOUNT_INFO_MAX_PRIORITY_JOBS]:
            job_id = _truncate(prio["job_id"], _ACCOUNT_INFO_JOBID_WIDTH)
            user = _truncate(prio.get("user", ""), _ACCOUNT_INFO_USER_WIDTH)
            priority = _truncate(prio["priority"], _ACCOUNT_INFO_PRIORITY_WIDTH)
            age = _truncate(prio["age"], _ACCOUNT_INFO_AGE_WIDTH)
            fair_share = _truncate(prio["fair_share"], _USER_INFO_FAIR_SHARE_WIDTH)
            partition = _truncate(prio["partition"], _ACCOUNT_INFO_PARTITION_WIDTH)

            lines.append(f"  {job_id:<12} {user:<12} {priority:<10} {age:<8} {fair_share:<10} {partition:<12}")

        if len(job_priorities) > _ACCOUNT_INFO_MAX_PRIORITY_JOBS:
            lines.append(
                f"  [dim]... and {len(job_priorities) - _ACCOUNT_INFO_MAX_PRIORITY_JOBS} more pending jobs[/dim]"
            )

    # Running Jobs section
    if running_jobs:
        lines.append("\n[bold reverse] Running Jobs [/bold reverse]")
        lines.append("")
        # Header
        lines.append(
            f"  [dim]{'JobID':<12} {'User':<12} {'Name':<15} {'Partition':<12} {'Time':<10} {'Nodes':<6}[/dim]"
        )
        lines.append(f"  [dim]{'─' * 75}[/dim]")

        for job in running_jobs[:_ACCOUNT_INFO_MAX_RUNNING_JOBS]:
            if len(job) < _USER_INFO_MIN_JOB_FIELDS:
                continue

            job_id = _truncate(job[0], _ACCOUNT_INFO_JOBID_WIDTH)
            name = _truncate(job[1], _ACCOUNT_INFO_NAME_WIDTH)
            user = _truncate(job[2], _ACCOUNT_INFO_USER_WIDTH)
            partition = _truncate(job[3], _ACCOUNT_INFO_PARTITION_WIDTH)
            time_used = (
                _truncate(job[_ACCOUNT_INFO_TIME_FIELD_INDEX], _ACCOUNT_INFO_TIME_WIDTH)
                if len(job) > _ACCOUNT_INFO_TIME_FIELD_INDEX
                else ""
            )
            nodes = (
                _truncate(job[_ACCOUNT_INFO_NODES_FIELD_INDEX], _ACCOUNT_INFO_NODES_WIDTH)
                if len(job) > _ACCOUNT_INFO_NODES_FIELD_INDEX
                else ""
            )

            lines.append(f"  {job_id:<12} {user:<12} {name:<15} {partition:<12} {time_used:<10} {nodes:<6}")

        if len(running_jobs) > _ACCOUNT_INFO_MAX_RUNNING_JOBS:
            lines.append(f"  [dim]... and {len(running_jobs) - _ACCOUNT_INFO_MAX_RUNNING_JOBS} more running jobs[/dim]")
    else:
        lines.append("\n[italic]No running jobs found for this account.[/italic]")

    return "\n".join(lines)
