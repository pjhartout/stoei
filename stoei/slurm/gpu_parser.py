"""GPU parsing utilities for SLURM TRES and Gres strings.

This module provides functions to parse GPU information from SLURM's
TRES (Trackable Resources) and Gres (Generic Resources) strings.
"""

import re


def parse_gpu_entries(tres_string: str) -> list[tuple[str, int]]:
    """Parse GPU entries from TRES string.

    Args:
        tres_string: TRES string (CfgTRES, AllocTRES, or similar).

    Examples:
            - "cpu=32,mem=256G,gres/gpu=8"
            - "cpu=32,mem=256G,gres/gpu:h200=8,gres/gpu=8"

    Returns:
        List of (gpu_type, gpu_count) tuples. The gpu_type is "gpu" for
        generic entries or a specific type like "h200", "a100", etc.
    """
    gpu_pattern = re.compile(r"gres/gpu(?::([^=,]+))?=(\d+)", re.IGNORECASE)
    gpu_entries: list[tuple[str, int]] = []

    for match in gpu_pattern.finditer(tres_string):
        gpu_type = match.group(1) if match.group(1) else "gpu"
        try:
            gpu_count = int(match.group(2))
            gpu_entries.append((gpu_type, gpu_count))
        except ValueError:
            pass

    return gpu_entries


def parse_gpu_from_gres(gres_string: str) -> list[tuple[str, int]]:
    """Parse GPU entries from Gres field string.

    This is a fallback parser for when TRES data is not available.

    Args:
        gres_string: Gres string from node or job info.

    Examples:
            - "gpu:4"
            - "gpu:a100:4"
            - "gpu:h200:8(S:0-1)"

    Returns:
        List of (gpu_type, gpu_count) tuples.
    """
    gpu_entries: list[tuple[str, int]] = []

    if "gpu:" not in gres_string.lower():
        return gpu_entries

    # Match patterns like: gpu:type:count or gpu:count
    # Also handle socket info like (S:0-1)
    gpu_pattern = re.compile(r"gpu(?::([^:(),]+))?:(\d+)(?:\([^)]+\))?", re.IGNORECASE)

    for match in gpu_pattern.finditer(gres_string):
        gpu_type = match.group(1) if match.group(1) else "gpu"
        try:
            gpu_count = int(match.group(2))
            gpu_entries.append((gpu_type.upper(), gpu_count))
        except ValueError:
            pass

    return gpu_entries


def has_specific_gpu_types(gpu_entries: list[tuple[str, int]]) -> bool:
    """Check if GPU entries contain specific (non-generic) GPU types.

    When both generic (gres/gpu=8) and specific (gres/gpu:h200=8) entries
    exist, they represent the same GPUs. This helper identifies if we have
    specific types to avoid double-counting.

    Args:
        gpu_entries: List of (gpu_type, gpu_count) tuples.

    Returns:
        True if any entry has a specific GPU type (not "gpu").
    """
    return any(gpu_type.lower() != "gpu" for gpu_type, _ in gpu_entries)


def aggregate_gpu_counts(
    gpu_entries: list[tuple[str, int]],
    skip_generic_if_specific: bool = True,
) -> dict[str, int]:
    """Aggregate GPU entries into a dictionary of type -> count.

    Handles the case where both generic and specific GPU entries exist
    to avoid double-counting.

    Args:
        gpu_entries: List of (gpu_type, gpu_count) tuples.
        skip_generic_if_specific: If True and specific types exist,
            skip generic "gpu" entries to avoid double-counting.

    Returns:
        Dictionary mapping GPU type (uppercase) to total count.
    """
    has_specific = has_specific_gpu_types(gpu_entries)
    result: dict[str, int] = {}

    for gpu_type, gpu_count in gpu_entries:
        # Skip generic if we have specific types (to avoid double-counting)
        if skip_generic_if_specific and has_specific and gpu_type.lower() == "gpu":
            continue

        gpu_type_upper = gpu_type.upper()
        result[gpu_type_upper] = result.get(gpu_type_upper, 0) + gpu_count

    return result


def format_gpu_types(gpu_counts: dict[str, int]) -> str:
    """Format GPU counts into a human-readable string.

    Args:
        gpu_counts: Dictionary mapping GPU type to count.

    Returns:
        Formatted string like "8x H200" or "4x A100, 2x V100".
        Empty string if no GPUs.
    """
    if not gpu_counts:
        return ""

    gpu_type_strs = [f"{count}x {gpu_type}" for gpu_type, count in sorted(gpu_counts.items())]
    return ", ".join(gpu_type_strs)


def calculate_total_gpus(
    gpu_entries: list[tuple[str, int]],
    skip_generic_if_specific: bool = True,
) -> int:
    """Calculate total GPU count from entries.

    Args:
        gpu_entries: List of (gpu_type, gpu_count) tuples.
        skip_generic_if_specific: If True and specific types exist,
            skip generic "gpu" entries to avoid double-counting.

    Returns:
        Total number of GPUs.
    """
    return sum(aggregate_gpu_counts(gpu_entries, skip_generic_if_specific).values())
