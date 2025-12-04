"""Tests for SLURM output parsers."""

from stoei.slurm.parser import (
    parse_sacct_output,
    parse_scontrol_output,
    parse_squeue_output,
)


class TestParseScontrolOutput:
    """Tests for scontrol output parsing."""

    def test_parse_basic_output(self, sample_scontrol_output: str) -> None:
        result = parse_scontrol_output(sample_scontrol_output)

        assert result["JobId"] == "12345"
        assert result["JobName"] == "test_job"
        assert result["JobState"] == "RUNNING"

    def test_parse_user_info(self, sample_scontrol_output: str) -> None:
        result = parse_scontrol_output(sample_scontrol_output)

        assert "UserId" in result
        assert "GroupId" in result

    def test_parse_timing_info(self, sample_scontrol_output: str) -> None:
        result = parse_scontrol_output(sample_scontrol_output)

        assert result["RunTime"] == "01:23:45"
        assert result["TimeLimit"] == "2-00:00:00"

    def test_parse_paths(self, sample_scontrol_output: str) -> None:
        result = parse_scontrol_output(sample_scontrol_output)

        assert result["WorkDir"] == "/home/testuser/project"
        assert "/home/testuser/project/logs/job.err" in result["StdErr"]

    def test_parse_empty_output(self) -> None:
        result = parse_scontrol_output("")
        assert result == {}

    def test_parse_completed_job(self, sample_scontrol_output_completed: str) -> None:
        result = parse_scontrol_output(sample_scontrol_output_completed)

        assert result["JobState"] == "COMPLETED"
        assert result["Restarts"] == "2"

    def test_parse_failed_job(self, sample_scontrol_output_failed: str) -> None:
        result = parse_scontrol_output(sample_scontrol_output_failed)

        assert result["JobState"] == "FAILED"
        assert result["ExitCode"] == "1:0"


class TestParseSqueueOutput:
    """Tests for squeue output parsing."""

    def test_parse_basic_output(self, sample_squeue_output: str) -> None:
        result = parse_squeue_output(sample_squeue_output)

        assert len(result) == 3

    def test_parse_job_fields(self, sample_squeue_output: str) -> None:
        result = parse_squeue_output(sample_squeue_output)

        # First job should be test_job
        first_job = result[0]
        assert "12345" in first_job[0]
        assert "test_job" in first_job[1]
        assert "RUNNING" in first_job[2]

    def test_parse_pending_job(self, sample_squeue_output: str) -> None:
        result = parse_squeue_output(sample_squeue_output)

        # Second job should be pending
        pending_job = result[1]
        assert "PENDING" in pending_job[2]

    def test_parse_empty_output(self) -> None:
        result = parse_squeue_output("")
        assert result == []

    def test_parse_header_only(self) -> None:
        header_only = "     JOBID|        JOBNAME|   STATE|      TIME|   NODES|      NODELIST"
        result = parse_squeue_output(header_only)
        assert result == []


class TestParseSacctOutput:
    """Tests for sacct output parsing."""

    def test_parse_basic_output(self, sample_sacct_output: str) -> None:
        jobs, total, requeues, max_req = parse_sacct_output(sample_sacct_output)

        assert len(jobs) == 4
        assert total == 4

    def test_parse_requeue_counts(self, sample_sacct_output: str) -> None:
        jobs, total, requeues, max_req = parse_sacct_output(sample_sacct_output)

        # 0 + 2 + 0 + 1 = 3 total requeues
        assert requeues == 3
        assert max_req == 2

    def test_jobs_sorted_by_id_descending(self, sample_sacct_output: str) -> None:
        jobs, _, _, _ = parse_sacct_output(sample_sacct_output)

        # Jobs should be sorted by ID descending
        job_ids = [int(job[0].split("_")[0]) for job in jobs]
        assert job_ids == sorted(job_ids, reverse=True)

    def test_parse_empty_output(self) -> None:
        jobs, total, requeues, max_req = parse_sacct_output("")

        assert jobs == []
        assert total == 0
        assert requeues == 0
        assert max_req == 0

    def test_parse_header_only(self) -> None:
        header_only = "JobID|JobName|State|Restart|Elapsed|ExitCode|NodeList"
        jobs, total, requeues, max_req = parse_sacct_output(header_only)

        assert jobs == []
        assert total == 0
