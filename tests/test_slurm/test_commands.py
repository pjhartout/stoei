"""Tests for SLURM command execution with mock executables."""

from pathlib import Path


class TestGetRunningJobs:
    """Tests for get_running_jobs with mock squeue."""

    def test_returns_jobs_list(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_running_jobs

        jobs = get_running_jobs()

        assert isinstance(jobs, list)
        assert len(jobs) >= 2  # Mock returns 2-5 random jobs

    def test_job_tuple_structure(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_running_jobs

        jobs = get_running_jobs()

        assert len(jobs) > 0
        first_job = jobs[0]
        assert isinstance(first_job, tuple)
        assert len(first_job) >= 6  # JobID, Name, State, Time, Nodes, NodeList


class TestGetJobHistory:
    """Tests for get_job_history with mock sacct."""

    def test_returns_history_tuple(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_history

        jobs, total, requeues, max_req = get_job_history()

        assert isinstance(jobs, list)
        assert isinstance(total, int)
        assert isinstance(requeues, int)
        assert isinstance(max_req, int)

    def test_history_contains_jobs(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_history

        jobs, total, _, _ = get_job_history()

        assert len(jobs) == 10  # Mock has 10 history entries
        assert total == 10

    def test_requeue_counts(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_history

        _, _, requeues, max_req = get_job_history()

        # Mock data: 0+2+0+3+0+0+1+0+0+5 = 11 total, max = 5
        assert requeues == 11
        assert max_req == 5

    def test_jobs_sorted_descending(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_history

        jobs, _, _, _ = get_job_history()

        job_ids = [int(job[0].split("_")[0]) for job in jobs]
        assert job_ids == sorted(job_ids, reverse=True)


class TestGetJobInfo:
    """Tests for get_job_info with mock scontrol."""

    def test_existing_job_returns_info(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_info

        info, error = get_job_info("12345")

        assert error is None
        assert "train_model" in info
        assert "RUNNING" in info

    def test_completed_job_info(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_info

        info, error = get_job_info("12344")

        assert error is None
        assert "COMPLETED" in info
        assert "Restarts" in info

    def test_failed_job_info(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_info

        info, error = get_job_info("12342")

        assert error is None
        assert "FAILED" in info
        assert "1:0" in info  # Exit code

    def test_unknown_job_returns_default(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_info

        info, error = get_job_info("99999")

        assert error is None
        assert "unknown_job" in info

    def test_invalid_job_id_returns_error(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_info

        info, error = get_job_info("invalid")

        assert info == ""
        assert error is not None
        assert "Invalid job ID" in error
