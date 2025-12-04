"""Shared test fixtures for stoei."""

import os
from pathlib import Path

import pytest

from tests.mocks import MOCKS_DIR


@pytest.fixture
def mock_slurm_path(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Add mock SLURM executables to PATH.

    This fixture prepends the mocks directory to PATH so that
    squeue, sacct, and scontrol commands use our mock implementations.

    Returns:
        Path to the mocks directory.
    """
    current_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{MOCKS_DIR}:{current_path}")
    return MOCKS_DIR


@pytest.fixture
def sample_scontrol_output() -> str:
    """Sample scontrol show jobid output for testing."""
    return """JobId=12345 JobName=test_job
   UserId=testuser(1000) GroupId=testgroup(1000)
   MCS_label=N/A
   Priority=4294901730 Nice=0 Account=default QOS=normal
   JobState=RUNNING Reason=None Dependency=(null)
   Requeue=1 Restarts=0 BatchFlag=1 Reboot=0 ExitCode=0:0
   RunTime=01:23:45 TimeLimit=2-00:00:00 TimeMin=N/A
   SubmitTime=2024-01-15T10:00:00 EligibleTime=2024-01-15T10:00:00
   AccrueTime=2024-01-15T10:00:00
   StartTime=2024-01-15T10:01:00 EndTime=2024-01-17T10:01:00 Deadline=N/A
   SuspendTime=None SecsPreSuspend=0 LastSchedEval=2024-01-15T10:00:30
   Partition=gpu NumNodes=1 NumCPUs=4 NumTasks=1 CPUs/Task=4 ReqB:S:C:T=0:0:*:*
   TRES=cpu=4,mem=16G,node=1,gres/gpu=1
   Socks/Node=* NtasksPerN:B:S:C=0:0:*:* CoreSpec=*
   MinCPUsNode=4 MinMemoryNode=16G MinTmpDiskNode=0
   Features=(null) DelayBoot=00:00:00
   OverSubscribe=OK Contiguous=0 Licenses=(null) Network=(null)
   Command=/home/testuser/scripts/run.sh
   WorkDir=/home/testuser/project
   StdErr=/home/testuser/project/logs/job.err
   StdOut=/home/testuser/project/logs/job.out
   Power=
   TresPerNode=gres:gpu:1
   NtasksPerTRES:0
   NodeList=gpu-node-01
   BatchHost=gpu-node-01
   ReqNodeList=(null) ExcNodeList=(null)"""


@pytest.fixture
def sample_scontrol_output_completed() -> str:
    """Sample scontrol output for a completed job."""
    return """JobId=12346 JobName=completed_job
   UserId=testuser(1000) GroupId=testgroup(1000)
   Priority=0 Nice=0 Account=default QOS=normal
   JobState=COMPLETED Reason=None Dependency=(null)
   Requeue=1 Restarts=2 BatchFlag=1 ExitCode=0:0
   RunTime=00:30:00 TimeLimit=1-00:00:00"""


@pytest.fixture
def sample_scontrol_output_failed() -> str:
    """Sample scontrol output for a failed job."""
    return """JobId=12347 JobName=failed_job
   UserId=testuser(1000) GroupId=testgroup(1000)
   Priority=0 Nice=0 Account=default QOS=normal
   JobState=FAILED Reason=NonZeroExitCode Dependency=(null)
   Requeue=0 Restarts=0 BatchFlag=1 ExitCode=1:0
   RunTime=00:05:00 TimeLimit=1-00:00:00"""


@pytest.fixture
def sample_squeue_output() -> str:
    """Sample squeue output for testing."""
    return """     JOBID|        JOBNAME|   STATE|      TIME|   NODES|      NODELIST
     12345|       test_job| RUNNING|   1:23:45|       1|   gpu-node-01
     12348|    pending_job| PENDING|      0:00|       1|      (Priority)
     12349|   array_job_1| RUNNING|   0:30:00|       2|gpu-node-[02-03]"""


@pytest.fixture
def sample_sacct_output() -> str:
    """Sample sacct output for testing."""
    return """JobID|JobName|State|Restart|Elapsed|ExitCode|NodeList
12345|test_job|RUNNING|0|01:23:45|0:0|gpu-node-01
12346|completed_job|COMPLETED|2|00:30:00|0:0|cpu-node-05
12347|failed_job|FAILED|0|00:05:00|1:0|gpu-node-02
12340|old_job|COMPLETED|1|02:00:00|0:0|cpu-node-01"""


@pytest.fixture
def valid_usernames() -> list[str]:
    """List of valid usernames for testing."""
    return ["testuser", "test_user", "test.user", "test-user", "user123"]


@pytest.fixture
def invalid_usernames() -> list[str]:
    """List of invalid usernames for testing."""
    return ["test user", "test@user", "test;user", "test'user", ""]


@pytest.fixture
def valid_job_ids() -> list[str]:
    """List of valid job IDs for testing."""
    return ["12345", "1", "9999999", "12345_0", "12345_999"]


@pytest.fixture
def invalid_job_ids() -> list[str]:
    """List of invalid job IDs for testing."""
    return ["abc", "12345_", "_12345", "12345_abc", "12.345", "", " ", "12345 "]
