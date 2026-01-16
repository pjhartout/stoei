"""Energy calculation utilities for SLURM jobs.

This module provides functions to estimate energy consumption based on
GPU and CPU usage, using manufacturer TDP (Thermal Design Power) values.

TDP values are loaded from stoei/data/tdp_values.json for easy editing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from stoei.logger import get_logger

logger = get_logger(__name__)

# Path to the TDP values JSON file
_TDP_JSON_PATH = Path(__file__).parent.parent / "data" / "tdp_values.json"


# Fallback defaults if JSON file cannot be loaded
_FALLBACK_DEFAULT_GPU_TDP: int = 300
_FALLBACK_CPU_TDP_PER_CORE: int = 10

# Seconds per hour for conversion
SECONDS_PER_HOUR: float = 3600.0

# Constants for time parsing
TIME_PARTS_HHMMSS: int = 3
TIME_PARTS_MMSS: int = 2
TIME_PARTS_SS: int = 1

# Constants for energy unit thresholds (in Wh)
ENERGY_GWH_THRESHOLD: int = 1_000_000_000
ENERGY_MWH_THRESHOLD: int = 1_000_000
ENERGY_KWH_THRESHOLD: int = 1000


def _load_tdp_values() -> tuple[dict[str, int], int, int]:
    """Load TDP values from the JSON configuration file.

    Returns:
        Tuple of (gpu_tdp_dict, default_gpu_tdp, cpu_tdp_per_core).
    """
    gpu_tdp: dict[str, int] = {}
    default_gpu_tdp = _FALLBACK_DEFAULT_GPU_TDP
    cpu_tdp_per_core = _FALLBACK_CPU_TDP_PER_CORE

    try:
        with _TDP_JSON_PATH.open() as f:
            data = json.load(f)

        # Parse GPU TDP values
        gpu_data = data.get("gpu", {})
        default_gpu_tdp = gpu_data.get("_default", _FALLBACK_DEFAULT_GPU_TDP)

        # Flatten nested GPU categories into a single lookup dict
        for key, value in gpu_data.items():
            if key.startswith("_"):
                # Skip metadata fields like _comment, _default
                continue
            if isinstance(value, dict):
                # This is a category (e.g., "NVIDIA Hopper/Ada")
                for gpu_model, tdp in value.items():
                    if isinstance(tdp, int):
                        gpu_tdp[gpu_model.upper()] = tdp
            elif isinstance(value, int):
                # Direct GPU -> TDP mapping
                gpu_tdp[key.upper()] = value

        # Parse CPU TDP
        cpu_data = data.get("cpu", {})
        cpu_tdp_per_core = cpu_data.get("_default_per_core", _FALLBACK_CPU_TDP_PER_CORE)

        logger.debug(
            f"Loaded TDP values: {len(gpu_tdp)} GPUs, default GPU={default_gpu_tdp}W, CPU={cpu_tdp_per_core}W/core"
        )

    except FileNotFoundError:
        logger.warning(f"TDP values file not found at {_TDP_JSON_PATH}, using fallback defaults")
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse TDP values JSON: {e}, using fallback defaults")
    except Exception as e:
        logger.warning(f"Error loading TDP values: {e}, using fallback defaults")

    return gpu_tdp, default_gpu_tdp, cpu_tdp_per_core


class _TdpCache:
    """Cache holder for TDP values to avoid global statement."""

    gpu_tdp: dict[str, int] | None = None
    default_gpu_tdp: int | None = None
    cpu_tdp_per_core: int | None = None


_tdp_cache = _TdpCache()


def _get_cached_tdp_values() -> tuple[dict[str, int], int, int]:
    """Get cached TDP values, loading from file if needed.

    Returns:
        Tuple of (gpu_tdp_dict, default_gpu_tdp, cpu_tdp_per_core).
    """
    if _tdp_cache.gpu_tdp is None:
        (
            _tdp_cache.gpu_tdp,
            _tdp_cache.default_gpu_tdp,
            _tdp_cache.cpu_tdp_per_core,
        ) = _load_tdp_values()

    return (
        _tdp_cache.gpu_tdp,
        _tdp_cache.default_gpu_tdp or _FALLBACK_DEFAULT_GPU_TDP,
        _tdp_cache.cpu_tdp_per_core or _FALLBACK_CPU_TDP_PER_CORE,
    )


def reload_tdp_values() -> None:
    """Force reload of TDP values from the JSON file.

    Call this after editing the tdp_values.json file to pick up changes.
    """
    _tdp_cache.gpu_tdp = None
    _tdp_cache.default_gpu_tdp = None
    _tdp_cache.cpu_tdp_per_core = None
    _get_cached_tdp_values()  # Reload immediately
    logger.info("TDP values reloaded from configuration file")


def get_gpu_tdp(gpu_type: str) -> int:
    """Get the TDP (Thermal Design Power) for a GPU type.

    Args:
        gpu_type: GPU type string (e.g., "H200", "A100", "V100").
            Case-insensitive matching is performed.

    Returns:
        TDP in Watts. Returns default TDP for unknown types.
    """
    gpu_tdp_dict, default_tdp, _ = _get_cached_tdp_values()

    if not gpu_type:
        return default_tdp

    # Normalize: uppercase and remove common prefixes/suffixes
    normalized = gpu_type.upper().strip()

    # Try exact match first
    if normalized in gpu_tdp_dict:
        return gpu_tdp_dict[normalized]

    # Try matching without common prefixes (nvidia_, amd_, etc.)
    for prefix in ("NVIDIA_", "NVIDIA-", "AMD_", "AMD-", "INTEL_", "INTEL-"):
        if normalized.startswith(prefix):
            stripped = normalized[len(prefix) :]
            if stripped in gpu_tdp_dict:
                return gpu_tdp_dict[stripped]

    # Try partial matching for common patterns
    for known_gpu, tdp in gpu_tdp_dict.items():
        if known_gpu in normalized or normalized in known_gpu:
            return tdp

    return default_tdp


def get_cpu_tdp_per_core() -> int:
    """Get the TDP per CPU core.

    Returns:
        TDP in Watts per core.
    """
    _, _, cpu_tdp = _get_cached_tdp_values()
    return cpu_tdp


def parse_elapsed_to_seconds(elapsed: str) -> float:
    """Parse SLURM elapsed time string to seconds.

    Args:
        elapsed: Elapsed time in SLURM format.
            Formats: "D-HH:MM:SS", "HH:MM:SS", "MM:SS", "SS"

    Returns:
        Duration in seconds. Returns 0.0 for invalid formats.
    """
    if not elapsed or not elapsed.strip():
        return 0.0

    elapsed = elapsed.strip()

    # Handle "D-HH:MM:SS" format (days)
    days = 0
    if "-" in elapsed:
        parts = elapsed.split("-", 1)
        try:
            days = int(parts[0])
        except ValueError:
            return 0.0
        elapsed = parts[1] if len(parts) > 1 else "0"

    # Split remaining by colons
    time_parts = elapsed.split(":")

    try:
        if len(time_parts) == TIME_PARTS_HHMMSS:
            # HH:MM:SS
            hours = int(time_parts[0])
            minutes = int(time_parts[1])
            seconds = float(time_parts[2])
        elif len(time_parts) == TIME_PARTS_MMSS:
            # MM:SS
            hours = 0
            minutes = int(time_parts[0])
            seconds = float(time_parts[1])
        elif len(time_parts) == TIME_PARTS_SS:
            # SS only
            hours = 0
            minutes = 0
            seconds = float(time_parts[0])
        else:
            return 0.0

        total_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds
        return max(0.0, total_seconds)
    except ValueError:
        return 0.0


def calculate_job_energy_wh(
    gpu_count: int,
    gpu_type: str,
    cpu_count: int,
    duration_seconds: float,
) -> float:
    """Calculate estimated energy consumption for a job in Watt-hours.

    Assumes 100% resource utilization for the entire duration.

    Args:
        gpu_count: Number of GPUs allocated.
        gpu_type: Type of GPU (e.g., "H200", "A100").
        cpu_count: Number of CPU cores allocated.
        duration_seconds: Job duration in seconds.

    Returns:
        Estimated energy consumption in Watt-hours (Wh).
    """
    if duration_seconds <= 0:
        return 0.0

    duration_hours = duration_seconds / SECONDS_PER_HOUR

    # GPU energy
    gpu_tdp = get_gpu_tdp(gpu_type) if gpu_count > 0 else 0
    gpu_energy_wh = gpu_count * gpu_tdp * duration_hours

    # CPU energy
    cpu_tdp_per_core = get_cpu_tdp_per_core()
    cpu_energy_wh = cpu_count * cpu_tdp_per_core * duration_hours

    return gpu_energy_wh + cpu_energy_wh


def format_energy(wh: float) -> str:
    """Format energy value with auto-scaling units.

    Automatically selects the most appropriate unit (Wh, kWh, MWh, GWh)
    based on the magnitude of the value.

    Args:
        wh: Energy in Watt-hours.

    Returns:
        Formatted string with appropriate unit (e.g., "1.23 MWh", "456 kWh").
    """
    if wh < 0:
        return "0 Wh"

    # GWh threshold (1 billion Wh)
    if wh >= ENERGY_GWH_THRESHOLD:
        return f"{wh / ENERGY_GWH_THRESHOLD:.2f} GWh"

    # MWh threshold (1 million Wh)
    if wh >= ENERGY_MWH_THRESHOLD:
        return f"{wh / ENERGY_MWH_THRESHOLD:.2f} MWh"

    # kWh threshold (1000 Wh)
    if wh >= ENERGY_KWH_THRESHOLD:
        return f"{wh / ENERGY_KWH_THRESHOLD:.1f} kWh"

    # Wh for small values
    if wh >= 1:
        return f"{wh:.0f} Wh"

    # Very small values
    return f"{wh:.2f} Wh"


def parse_gpu_info_from_tres(tres_str: str) -> list[tuple[str, int]]:
    """Parse GPU type and count from TRES string.

    Args:
        tres_str: TRES string (e.g., "cpu=32,mem=256G,gres/gpu:h200=8").

    Returns:
        List of (gpu_type, gpu_count) tuples.
    """
    if not tres_str:
        return []

    gpu_pattern = re.compile(r"gres/gpu(?::([^=,]+))?=(\d+)", re.IGNORECASE)
    gpu_entries: list[tuple[str, int]] = []

    for match in gpu_pattern.finditer(tres_str):
        gpu_type = match.group(1) if match.group(1) else "gpu"
        try:
            gpu_count = int(match.group(2))
            gpu_entries.append((gpu_type, gpu_count))
        except ValueError:
            pass

    return gpu_entries


def parse_cpu_count_from_tres(tres_str: str) -> int:
    """Parse CPU count from TRES string.

    Args:
        tres_str: TRES string (e.g., "cpu=32,mem=256G").

    Returns:
        Number of CPUs, or 0 if not found.
    """
    if not tres_str:
        return 0

    cpu_match = re.search(r"cpu=(\d+)", tres_str, re.IGNORECASE)
    if cpu_match:
        try:
            return int(cpu_match.group(1))
        except ValueError:
            pass

    return 0


def get_tdp_file_path() -> Path:
    """Get the path to the TDP values JSON file.

    Returns:
        Path to the tdp_values.json file.
    """
    return _TDP_JSON_PATH
