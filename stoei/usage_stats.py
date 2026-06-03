"""Shared user resource-usage data models.

These dataclasses are consumed by both the SLURM formatters and the user
overview widget. They live in a dependency-free module so either side can
import them without creating an import cycle.
"""

from dataclasses import dataclass


@dataclass
class UserStats:
    """User resource usage statistics."""

    username: str
    job_count: int
    total_cpus: int
    total_memory_gb: float
    total_gpus: int
    total_nodes: int
    gpu_types: str = ""
    node_names: str = ""
    array_count: int = 0
    plain_job_count: int = 0


@dataclass
class UserPendingStats:
    """User pending job resource statistics."""

    username: str
    pending_job_count: int
    pending_cpus: int
    pending_memory_gb: float
    pending_gpus: int
    pending_gpu_types: str = ""


@dataclass
class UserEnergyStats:
    """User energy usage statistics over a historical period."""

    username: str
    total_energy_wh: float  # Total energy in Watt-hours
    job_count: int  # Number of completed jobs
    gpu_hours: float  # Total GPU-hours used
    cpu_hours: float  # Total CPU-hours used
