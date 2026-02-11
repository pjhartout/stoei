"""Tests for SLURM command execution with mock executables."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from stoei.slurm.commands import _parse_fixed_width_squeue_line, _validate_username


class TestValidateUsername:
    """Tests for username validation helper."""

    def test_valid_username(self) -> None:
        result = _validate_username("testuser")
        assert result is None

    def test_valid_username_with_underscore(self) -> None:
        result = _validate_username("test_user")
        assert result is None

    def test_valid_username_with_hyphen(self) -> None:
        result = _validate_username("test-user")
        assert result is None

    def test_valid_username_with_numbers(self) -> None:
        result = _validate_username("user123")
        assert result is None

    def test_empty_username(self) -> None:
        result = _validate_username("")
        assert result == "Invalid username"

    def test_whitespace_username(self) -> None:
        result = _validate_username("   ")
        assert result == "Invalid username"

    def test_username_with_special_chars(self) -> None:
        result = _validate_username("user@domain")
        assert result == "Invalid username characters"

    def test_username_with_spaces(self) -> None:
        result = _validate_username("user name")
        assert result == "Invalid username characters"


class TestParseFixedWidthSqueueLine:
    """Tests for _parse_fixed_width_squeue_line with wider NodeList column."""

    def test_parses_line_with_wide_nodelist(self) -> None:
        """Test parsing a fixed-width line with 80-char NodeList field."""
        # Build a line matching the format:
        # JobID:30, Name:50, UserName:15, Partition:15, StateCompact:10, TimeUsed:12, NumNodes:6, NodeList:80, tres:80
        job_id = "12345".ljust(30)
        name = "train_model".ljust(50)
        user = "testuser".ljust(15)
        partition = "gpu-a100".ljust(15)
        state = "R".ljust(10)
        time_used = "1:23:45".ljust(12)
        num_nodes = "4".ljust(6)
        node_list = "gpu-node[001-004],cpu-node[010-012]".ljust(80)
        tres = "cpu=128,mem=512G,gres/gpu:a100=16"

        line = job_id + name + user + partition + state + time_used + num_nodes + node_list + tres
        result = _parse_fixed_width_squeue_line(line)

        assert result is not None
        assert result[0] == "12345"
        assert result[1] == "train_model"
        assert result[2] == "testuser"
        assert result[3] == "gpu-a100"
        assert result[4] == "R"
        assert result[5] == "1:23:45"
        assert result[6] == "4"
        assert result[7] == "gpu-node[001-004],cpu-node[010-012]"
        assert "cpu=128" in result[8]

    def test_parses_line_with_short_nodelist(self) -> None:
        """Test parsing a line where NodeList is shorter than 80 chars."""
        job_id = "99999".ljust(30)
        name = "short_job".ljust(50)
        user = "alice".ljust(15)
        partition = "cpu".ljust(15)
        state = "R".ljust(10)
        time_used = "0:05:00".ljust(12)
        num_nodes = "1".ljust(6)
        node_list = "node01".ljust(80)
        tres = "cpu=4,mem=16G"

        line = job_id + name + user + partition + state + time_used + num_nodes + node_list + tres
        result = _parse_fixed_width_squeue_line(line)

        assert result is not None
        assert result[7] == "node01"


class TestGetUserJobs:
    """Tests for get_user_jobs function."""

    def test_returns_jobs_for_valid_user(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_user_jobs

        jobs, error = get_user_jobs("testuser")

        # Mock may not have user-specific data, but should not error
        assert error is None or "squeue" not in error.lower()
        assert isinstance(jobs, list)

    def test_invalid_username_returns_error(self) -> None:
        from stoei.slurm.commands import get_user_jobs

        jobs, error = get_user_jobs("")
        assert error == "Invalid username"
        assert jobs == []

    def test_username_with_special_chars_returns_error(self) -> None:
        from stoei.slurm.commands import get_user_jobs

        jobs, error = get_user_jobs("user@domain")
        assert error == "Invalid username characters"
        assert jobs == []

    def test_whitespace_username_returns_error(self) -> None:
        from stoei.slurm.commands import get_user_jobs

        jobs, error = get_user_jobs("   ")
        assert error == "Invalid username"
        assert jobs == []

    def test_username_is_stripped(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_user_jobs

        # Should work with leading/trailing whitespace
        jobs, error = get_user_jobs("  testuser  ")
        assert error is None or "squeue" not in error.lower()
        assert isinstance(jobs, list)


class TestGetRunningJobs:
    """Tests for get_running_jobs with mock squeue."""

    def test_returns_jobs_list(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_running_jobs

        jobs, error = get_running_jobs()

        assert error is None
        assert isinstance(jobs, list)
        assert len(jobs) >= 2  # Mock returns 2-5 random jobs

    def test_job_tuple_structure(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_running_jobs

        jobs, error = get_running_jobs()

        assert error is None
        assert len(jobs) > 0
        first_job = jobs[0]
        assert isinstance(first_job, tuple)
        assert len(first_job) >= 6  # JobID, Name, State, Time, Nodes, NodeList


class TestGetJobHistory:
    """Tests for get_job_history with mock sacct."""

    def test_returns_history_tuple(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_history

        jobs, total, requeues, max_req, error = get_job_history()

        assert error is None
        assert isinstance(jobs, list)
        assert isinstance(total, int)
        assert isinstance(requeues, int)
        assert isinstance(max_req, int)

    def test_history_contains_jobs(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_history

        jobs, total, _, _, error = get_job_history()

        assert error is None
        assert len(jobs) == 10  # Mock has 10 history entries
        assert total == 10

    def test_requeue_counts(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_history

        _, _, requeues, max_req, error = get_job_history()

        assert error is None
        # Mock data: 0+2+0+3+0+0+1+0+0+5 = 11 total, max = 5
        assert requeues == 11
        assert max_req == 5

    def test_jobs_sorted_descending(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_history

        jobs, _, _, _, error = get_job_history()

        assert error is None
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


class TestCancelJob:
    """Tests for cancel_job with mock scancel."""

    def test_cancel_running_job_success(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import cancel_job

        success, error = cancel_job("12345")

        assert success is True
        assert error is None

    def test_cancel_pending_job_success(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import cancel_job

        success, error = cancel_job("12347")

        assert success is True
        assert error is None

    def test_cancel_completed_job_fails(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import cancel_job

        success, error = cancel_job("12344")

        assert success is False
        assert error is not None
        assert "error" in error.lower()

    def test_cancel_invalid_job_id_fails(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import cancel_job

        success, error = cancel_job("invalid")

        assert success is False
        assert error is not None
        assert "Invalid job ID" in error

    def test_cancel_empty_job_id_fails(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import cancel_job

        success, error = cancel_job("")

        assert success is False
        assert error is not None

    def test_cancel_array_job(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import cancel_job

        success, error = cancel_job("12345_0")

        assert success is True
        assert error is None


class TestGetJobLogPaths:
    """Tests for get_job_log_paths function."""

    def test_returns_paths_for_running_job(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_log_paths

        stdout_path, stderr_path, error = get_job_log_paths("12345")

        assert error is None
        assert stdout_path is not None
        assert stderr_path is not None

    def test_returns_error_for_invalid_job(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_log_paths

        _stdout_path, _stderr_path, error = get_job_log_paths("invalid")

        assert error is not None
        assert "Invalid job ID" in error

    def test_expands_placeholders_in_paths(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_log_paths

        stdout_path, _stderr_path, _error = get_job_log_paths("12345")

        # Paths should not contain unexpanded placeholders
        if stdout_path:
            assert "%j" not in stdout_path
            assert "%J" not in stdout_path


class TestExpandLogPath:
    """Tests for _expand_log_path function."""

    def test_expands_job_id_placeholder(self) -> None:
        from stoei.slurm.commands import _expand_log_path

        job_info = {"UserId": "testuser", "JobName": "myjob"}
        result = _expand_log_path("/logs/job_%j.out", "12345", job_info)

        assert result == "/logs/job_12345.out"

    def test_expands_full_job_id_placeholder(self) -> None:
        from stoei.slurm.commands import _expand_log_path

        job_info = {"UserId": "testuser", "JobName": "myjob"}
        result = _expand_log_path("/logs/job_%J.out", "12345_0", job_info)

        assert result == "/logs/job_12345_0.out"

    def test_expands_array_job_placeholders(self) -> None:
        from stoei.slurm.commands import _expand_log_path

        job_info = {"UserId": "testuser", "JobName": "myjob"}
        result = _expand_log_path("/logs/job_%A_%a.out", "12345_42", job_info)

        assert result == "/logs/job_12345_42.out"

    def test_expands_username_placeholder(self) -> None:
        from stoei.slurm.commands import _expand_log_path

        job_info = {"UserId": "testuser(1000)", "JobName": "myjob"}
        result = _expand_log_path("/home/%u/logs/job.out", "12345", job_info)

        assert result == "/home/testuser/logs/job.out"

    def test_expands_job_name_placeholder(self) -> None:
        from stoei.slurm.commands import _expand_log_path

        job_info = {"UserId": "testuser", "JobName": "train_model"}
        result = _expand_log_path("/logs/%x.out", "12345", job_info)

        assert result == "/logs/train_model.out"

    def test_expands_node_placeholder(self) -> None:
        from stoei.slurm.commands import _expand_log_path

        job_info = {"UserId": "testuser", "JobName": "myjob", "NodeList": "gpu-node-01"}
        result = _expand_log_path("/logs/job_%N.out", "12345", job_info)

        assert result == "/logs/job_gpu-node-01.out"

    def test_multiple_placeholders(self) -> None:
        from stoei.slurm.commands import _expand_log_path

        job_info = {"UserId": "testuser(1000)", "JobName": "train", "NodeList": "node01"}
        result = _expand_log_path("/home/%u/logs/%x_%j.out", "12345", job_info)

        assert result == "/home/testuser/logs/train_12345.out"

    def test_handles_missing_user_info(self) -> None:
        from stoei.slurm.commands import _expand_log_path

        job_info = {}
        result = _expand_log_path("/logs/job_%j.out", "12345", job_info)

        assert result == "/logs/job_12345.out"


class TestGetJobInfoParsed:
    """Tests for get_job_info_parsed function."""

    def test_returns_dict_for_running_job(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_info_parsed

        info, error = get_job_info_parsed("12345")

        assert error is None
        assert isinstance(info, dict)
        assert "JobId" in info or "JobID" in info

    def test_returns_error_for_invalid_job(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_job_info_parsed

        info, error = get_job_info_parsed("invalid")

        assert error is not None
        assert info == {}


class TestRunScontrolForJob:
    """Tests for _run_scontrol_for_job function."""

    def test_returns_raw_output(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import _run_scontrol_for_job

        output, error = _run_scontrol_for_job("12345")

        assert error is None
        assert "JobId" in output or "RUNNING" in output

    def test_returns_error_for_invalid_job_id(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import _run_scontrol_for_job

        output, error = _run_scontrol_for_job("invalid_id")

        assert error is not None
        assert output == ""


class TestRunSacctForJob:
    """Tests for _run_sacct_for_job function."""

    def test_returns_raw_output(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import _run_sacct_for_job

        output, error = _run_sacct_for_job("12345")

        # May succeed or fail depending on mock, but should return proper types
        assert isinstance(output, str)
        assert error is None or isinstance(error, str)

    def test_returns_error_for_invalid_job_id(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import _run_sacct_for_job

        output, error = _run_sacct_for_job("invalid_id")

        assert error is not None
        assert output == ""


class TestCommandErrorPaths:
    """Tests for error handling in commands."""

    def test_get_running_jobs_handles_missing_squeue(self) -> None:
        from stoei.slurm.commands import get_running_jobs

        with patch("stoei.slurm.commands.resolve_executable", side_effect=FileNotFoundError):
            jobs, error = get_running_jobs()
            assert jobs == []
            assert error is not None
            assert "error" in error.lower() or "not found" in error.lower()

    def test_get_job_history_handles_missing_sacct(self) -> None:
        from stoei.slurm.commands import get_job_history

        with patch("stoei.slurm.commands.resolve_executable", side_effect=FileNotFoundError):
            jobs, total, _requeues, _max_req, error = get_job_history()
            assert jobs == []
            assert total == 0
            assert error is not None
            assert "error" in error.lower() or "not found" in error.lower()

    def test_cancel_job_handles_missing_scancel(self) -> None:
        from stoei.slurm.commands import cancel_job

        with patch("stoei.slurm.commands.resolve_executable", side_effect=FileNotFoundError):
            success, error = cancel_job("12345")
            assert success is False
            assert error is not None

    def test_get_job_info_handles_timeout(self, mock_slurm_path: Path) -> None:
        import subprocess

        from stoei.slurm.commands import get_job_info

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 10)):
            _info, error = get_job_info("12345")
            assert error is not None
            assert "timed out" in error.lower()

    def test_cancel_job_handles_timeout(self, mock_slurm_path: Path) -> None:
        import subprocess

        from stoei.slurm.commands import cancel_job

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 10)):
            success, error = cancel_job("12345")
            assert success is False
            assert error is not None

    def test_get_running_jobs_handles_subprocess_error(self) -> None:
        """Test handling of SubprocessError in get_running_jobs."""
        import subprocess

        from stoei.slurm.commands import get_running_jobs

        with (
            patch("stoei.slurm.commands.resolve_executable", return_value="/usr/bin/squeue"),
            patch("stoei.slurm.commands.get_current_username", return_value="testuser"),
            patch("subprocess.run", side_effect=subprocess.SubprocessError("Error")),
        ):
            jobs, error = get_running_jobs()
            assert jobs == []
            assert error is not None
            assert "error" in error.lower()

    def test_get_job_history_handles_subprocess_error(self) -> None:
        """Test handling of SubprocessError in get_job_history."""
        import subprocess

        from stoei.slurm.commands import get_job_history

        with (
            patch("stoei.slurm.commands.resolve_executable", return_value="/usr/bin/sacct"),
            patch("stoei.slurm.commands.get_current_username", return_value="testuser"),
            patch("subprocess.run", side_effect=subprocess.SubprocessError("Error")),
        ):
            jobs, total, _requeues, _max_req, error = get_job_history()
            assert jobs == []
            assert total == 0
            assert error is not None
            assert "error" in error.lower()

    def test_cancel_job_handles_subprocess_error(self) -> None:
        """Test handling of SubprocessError in cancel_job."""
        import subprocess

        from stoei.slurm.commands import cancel_job

        with (
            patch("stoei.slurm.commands.resolve_executable", return_value="/usr/bin/scancel"),
            patch("subprocess.run", side_effect=subprocess.SubprocessError("Error")),
        ):
            success, error = cancel_job("12345")
            assert success is False
            assert error is not None

    def test_get_running_jobs_handles_timeout(self) -> None:
        """Test handling of timeout in get_running_jobs."""
        import subprocess

        from stoei.slurm.commands import get_running_jobs

        with (
            patch("stoei.slurm.commands.resolve_executable", return_value="/usr/bin/squeue"),
            patch("stoei.slurm.commands.get_current_username", return_value="testuser"),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)),
        ):
            jobs, error = get_running_jobs()
            assert jobs == []
            assert error is not None
            assert "timed out" in error.lower()

    def test_get_job_history_handles_timeout(self) -> None:
        """Test handling of timeout in get_job_history."""
        import subprocess

        from stoei.slurm.commands import get_job_history

        with (
            patch("stoei.slurm.commands.resolve_executable", return_value="/usr/bin/sacct"),
            patch("stoei.slurm.commands.get_current_username", return_value="testuser"),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)),
        ):
            jobs, _total, _requeues, _max_req, error = get_job_history()
            assert jobs == []
            assert error is not None
            assert "timed out" in error.lower()

    def test_scontrol_handles_nonzero_exit_code(self) -> None:
        """Test handling of non-zero exit code from scontrol."""
        from stoei.slurm.commands import _run_scontrol_for_job

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Job not found"
        mock_result.stdout = ""

        with (
            patch("stoei.slurm.commands.resolve_executable", return_value="/usr/bin/scontrol"),
            patch("subprocess.run", return_value=mock_result),
        ):
            output, error = _run_scontrol_for_job("99999")
            assert output == ""
            assert error is not None

    def test_sacct_handles_nonzero_exit_code(self) -> None:
        """Test handling of non-zero exit code from sacct."""
        from stoei.slurm.commands import _run_sacct_for_job

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Database error"
        mock_result.stdout = ""

        with (
            patch("stoei.slurm.commands.resolve_executable", return_value="/usr/bin/sacct"),
            patch("subprocess.run", return_value=mock_result),
        ):
            output, error = _run_sacct_for_job("99999")
            assert output == ""
            assert error is not None


class TestGetWaitTimeJobHistory:
    """Tests for get_wait_time_job_history function."""

    def test_returns_jobs_list(self, mock_slurm_path: Path) -> None:
        from stoei.slurm.commands import get_wait_time_job_history

        jobs, error = get_wait_time_job_history(hours=1)

        assert error is None
        assert isinstance(jobs, list)

    def test_filters_out_unknown_start_times(self) -> None:
        """Test that jobs with Unknown start times are filtered out."""
        from stoei.slurm.commands import get_wait_time_job_history

        mock_result = MagicMock()
        mock_result.returncode = 0
        # Include a job with Unknown start time that should be filtered
        mock_result.stdout = """12345|gpu-a100|COMPLETED|2024-01-15T10:00:00|2024-01-15T10:05:00
12346|cpu|PENDING|2024-01-15T10:00:00|Unknown
12347|gpu-h200|RUNNING|2024-01-15T10:00:00|2024-01-15T10:10:00"""
        mock_result.stderr = ""

        with (
            patch("stoei.slurm.commands.resolve_executable", return_value="/usr/bin/sacct"),
            patch("subprocess.run", return_value=mock_result),
        ):
            jobs, error = get_wait_time_job_history(hours=1)

            assert error is None
            assert len(jobs) == 2  # Only 2 jobs have valid start times
            assert all(job[4] != "Unknown" for job in jobs)

    def test_handles_timeout(self) -> None:
        """Test handling of timeout in get_wait_time_job_history."""
        import subprocess

        from stoei.slurm.commands import get_wait_time_job_history

        with (
            patch("stoei.slurm.commands.resolve_executable", return_value="/usr/bin/sacct"),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)),
        ):
            jobs, error = get_wait_time_job_history(hours=1)
            assert jobs == []
            assert error is not None
            assert "timed out" in error.lower()

    def test_handles_subprocess_error(self) -> None:
        """Test handling of SubprocessError in get_wait_time_job_history."""
        import subprocess

        from stoei.slurm.commands import get_wait_time_job_history

        with (
            patch("stoei.slurm.commands.resolve_executable", return_value="/usr/bin/sacct"),
            patch("subprocess.run", side_effect=subprocess.SubprocessError("Error")),
        ):
            jobs, error = get_wait_time_job_history(hours=1)
            assert jobs == []
            assert error is not None
            assert "error" in error.lower()

    def test_handles_nonzero_exit_code(self) -> None:
        """Test handling of non-zero exit code from sacct."""
        from stoei.slurm.commands import get_wait_time_job_history

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Database error"
        mock_result.stdout = ""

        with (
            patch("stoei.slurm.commands.resolve_executable", return_value="/usr/bin/sacct"),
            patch("subprocess.run", return_value=mock_result),
        ):
            jobs, error = get_wait_time_job_history(hours=1)
            assert jobs == []
            assert error is not None

    def test_hours_parameter(self) -> None:
        """Test that hours parameter is passed correctly."""
        from stoei.slurm.commands import get_wait_time_job_history

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            patch("stoei.slurm.commands.resolve_executable", return_value="/usr/bin/sacct"),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            get_wait_time_job_history(hours=6)
            # Check that the command includes the correct hours parameter
            call_args = mock_run.call_args[0][0]
            assert any("now-6hours" in arg for arg in call_args)


class TestRunWithRetry:
    """Tests for _run_with_retry function."""

    def test_succeeds_on_first_try(self) -> None:
        """Test that successful command returns immediately."""
        from stoei.slurm.commands import _run_with_retry

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "success"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result, error = _run_with_retry(
                ["test", "cmd"],
                timeout=5,
                command_name="test",
                max_retries=3,
                initial_delay=0.01,
            )
            assert result is not None
            assert result.returncode == 0
            assert error is None

    def test_retries_on_failure(self) -> None:
        """Test that command is retried on failure."""
        from stoei.slurm.commands import _run_with_retry

        fail_result = MagicMock()
        fail_result.returncode = 1
        fail_result.stdout = ""
        fail_result.stderr = "error"

        success_result = MagicMock()
        success_result.returncode = 0
        success_result.stdout = "success"
        success_result.stderr = ""

        # Fail twice, then succeed
        with patch("subprocess.run", side_effect=[fail_result, fail_result, success_result]):
            result, error = _run_with_retry(
                ["test", "cmd"],
                timeout=5,
                command_name="test",
                max_retries=3,
                initial_delay=0.01,
                backoff_factor=1.0,
            )
            assert result is not None
            assert result.returncode == 0
            assert error is None

    def test_gives_up_after_max_retries(self) -> None:
        """Test that command fails after max retries."""
        from stoei.slurm.commands import _run_with_retry

        fail_result = MagicMock()
        fail_result.returncode = 1
        fail_result.stdout = ""
        fail_result.stderr = "persistent error"

        with patch("subprocess.run", return_value=fail_result):
            result, error = _run_with_retry(
                ["test", "cmd"],
                timeout=5,
                command_name="test",
                max_retries=2,
                initial_delay=0.01,
                backoff_factor=1.0,
            )
            assert result is None
            assert error is not None

    def test_no_retry_on_file_not_found(self) -> None:
        """Test that FileNotFoundError is not retried."""
        from stoei.slurm.commands import _run_with_retry

        with patch("subprocess.run", side_effect=FileNotFoundError("command not found")):
            result, error = _run_with_retry(
                ["nonexistent", "cmd"],
                timeout=5,
                command_name="test",
                max_retries=3,
                initial_delay=0.01,
            )
            assert result is None
            assert error is not None
            assert "not found" in error.lower()
