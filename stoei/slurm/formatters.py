"""Formatting utilities for SLURM job information."""

from stoei.slurm.parser import parse_scontrol_output

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
