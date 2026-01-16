"""Tests for SLURM output formatters."""

from stoei.slurm.formatters import (
    format_compact_timeline,
    format_job_info,
    format_sacct_job_info,
    format_user_info,
    format_value,
)
from stoei.widgets.user_overview import UserStats


class TestFormatValue:
    """Tests for value formatting."""

    def test_empty_value(self) -> None:
        result = format_value("TestKey", "")
        assert "not set" in result

    def test_null_value(self) -> None:
        result = format_value("TestKey", "(null)")
        assert "not set" in result

    def test_running_state(self) -> None:
        result = format_value("JobState", "RUNNING")
        assert "green" in result
        assert "RUNNING" in result

    def test_pending_state(self) -> None:
        result = format_value("JobState", "PENDING")
        assert "yellow" in result
        assert "PENDING" in result

    def test_failed_state(self) -> None:
        result = format_value("JobState", "FAILED")
        assert "red" in result
        assert "FAILED" in result

    def test_completed_state(self) -> None:
        result = format_value("JobState", "COMPLETED")
        assert "cyan" in result
        assert "COMPLETED" in result

    def test_successful_exit_code(self) -> None:
        result = format_value("ExitCode", "0:0")
        assert "green" in result
        assert "✓" in result

    def test_failed_exit_code(self) -> None:
        result = format_value("ExitCode", "1:0")
        assert "red" in result
        assert "✗" in result

    def test_path_formatting(self) -> None:
        result = format_value("WorkDir", "/home/user/project")
        assert "cyan" in result
        assert "italic" in result

    def test_time_formatting(self) -> None:
        result = format_value("RunTime", "01:23:45")
        assert "yellow" in result

    def test_tres_formatting(self) -> None:
        result = format_value("TRES", "cpu=4,mem=16G")
        assert "magenta" in result

    def test_node_list_formatting(self) -> None:
        result = format_value("NodeList", "gpu-node-01")
        assert "blue" in result


class TestFormatJobInfo:
    """Tests for job info formatting."""

    def test_format_basic_info(self, sample_scontrol_output: str) -> None:
        result = format_job_info(sample_scontrol_output)

        # Should contain category headers
        assert "Identity" in result
        assert "Status" in result

    def test_format_includes_job_id(self, sample_scontrol_output: str) -> None:
        result = format_job_info(sample_scontrol_output)

        assert "JobId" in result
        assert "12345" in result

    def test_format_includes_job_state(self, sample_scontrol_output: str) -> None:
        result = format_job_info(sample_scontrol_output)

        assert "JobState" in result
        assert "RUNNING" in result

    def test_format_empty_output(self) -> None:
        result = format_job_info("")

        assert "No job information" in result

    def test_format_completed_job(self, sample_scontrol_output_completed: str) -> None:
        result = format_job_info(sample_scontrol_output_completed)

        assert "COMPLETED" in result

    def test_format_failed_job(self, sample_scontrol_output_failed: str) -> None:
        result = format_job_info(sample_scontrol_output_failed)

        assert "FAILED" in result
        assert "1:0" in result

    def test_format_includes_other_category(self) -> None:
        """Test that uncategorized fields go to 'Other' category."""
        # Create output with a field that's not in any category
        raw_output = "JobId=12345 JobName=test CustomField=custom_value"
        result = format_job_info(raw_output)

        # CustomField should be in "Other" section
        assert "Other" in result or "CustomField" in result


class TestFormatSacctJobInfo:
    """Tests for format_sacct_job_info function."""

    def test_format_basic_sacct_info(self) -> None:
        """Test formatting basic sacct job info."""
        parsed = {
            "JobID": "12345",
            "JobName": "test_job",
            "State": "COMPLETED",
            "ExitCode": "0:0",
        }

        result = format_sacct_job_info(parsed)

        assert "12345" in result
        assert "test_job" in result
        assert "COMPLETED" in result
        assert "sacct" in result.lower() or "historical" in result.lower()

    def test_format_empty_sacct_info(self) -> None:
        """Test formatting empty sacct info."""
        result = format_sacct_job_info({})

        assert "No job information" in result

    def test_format_includes_categories(self) -> None:
        """Test that sacct info includes category headers."""
        parsed = {
            "JobID": "12345",
            "JobName": "test_job",
            "User": "testuser",
            "State": "COMPLETED",
            "Start": "2024-01-15T10:00:00",
            "End": "2024-01-15T11:00:00",
            "Elapsed": "01:00:00",
            "WorkDir": "/home/testuser/project",
        }

        result = format_sacct_job_info(parsed)

        assert "Identity" in result
        assert "Status" in result
        assert "Timing" in result
        assert "Paths" in result

    def test_format_includes_resources(self) -> None:
        """Test that resource fields are formatted."""
        parsed = {
            "JobID": "12345",
            "NNodes": "4",
            "NCPUS": "16",
            "ReqMem": "64G",
            "Partition": "gpu",
        }

        result = format_sacct_job_info(parsed)

        assert "4" in result
        assert "16" in result
        assert "Resources" in result

    def test_format_state_colors(self) -> None:
        """Test that state values are colored."""
        parsed = {
            "JobID": "12345",
            "State": "FAILED",
            "ExitCode": "1:0",
        }

        result = format_sacct_job_info(parsed)

        assert "red" in result
        assert "FAILED" in result

    def test_format_remaining_fields(self) -> None:
        """Test that uncategorized fields go to 'Other' section."""
        parsed = {
            "JobID": "12345",
            "CustomField": "custom_value",
        }

        result = format_sacct_job_info(parsed)

        # Either in Other section or directly included
        assert "custom_value" in result or "CustomField" in result


class TestFormatValueEdgeCases:
    """Additional edge case tests for format_value."""

    def test_na_value(self) -> None:
        """Test N/A value formatting."""
        result = format_value("TestKey", "N/A")
        assert "not set" in result

    def test_none_value(self) -> None:
        """Test None string value formatting."""
        result = format_value("TestKey", "None")
        assert "not set" in result

    def test_state_with_extra_info(self) -> None:
        """Test state value with additional info."""
        result = format_value("JobState", "RUNNING by 12345")
        assert "green" in result
        assert "RUNNING" in result

    def test_derived_exit_code(self) -> None:
        """Test DerivedExitCode formatting."""
        result = format_value("DerivedExitCode", "1:0")
        assert "red" in result

    def test_stdin_path(self) -> None:
        """Test StdIn path formatting."""
        result = format_value("StdIn", "/dev/null")
        assert "cyan" in result

    def test_command_formatting(self) -> None:
        """Test Command path formatting."""
        result = format_value("Command", "/path/to/script.sh")
        assert "cyan" in result

    def test_time_with_na(self) -> None:
        """Test time value with N/A."""
        result = format_value("RunTime", "N/A")
        assert "not set" in result

    def test_num_nodes_formatting(self) -> None:
        """Test NumNodes formatting."""
        result = format_value("NumNodes", "4")
        assert "bold" in result

    def test_num_cpus_formatting(self) -> None:
        """Test NumCPUs formatting."""
        result = format_value("NumCPUs", "16")
        assert "bold" in result

    def test_priority_formatting(self) -> None:
        """Test Priority formatting."""
        result = format_value("Priority", "4294901730")
        assert "bold" in result

    def test_restarts_formatting(self) -> None:
        """Test Restarts formatting."""
        result = format_value("Restarts", "2")
        assert "bold" in result

    def test_gres_formatting(self) -> None:
        """Test Gres formatting."""
        result = format_value("Gres", "gpu:1")
        assert "magenta" in result

    def test_req_tres_formatting(self) -> None:
        """Test ReqTRES formatting."""
        result = format_value("ReqTRES", "cpu=4,mem=16G")
        assert "magenta" in result

    def test_batch_host_formatting(self) -> None:
        """Test BatchHost is returned as-is (no special formatting)."""
        result = format_value("BatchHost", "gpu-node-01")
        # BatchHost doesn't contain "Node" so it's not formatted as a node list
        assert result == "gpu-node-01"

    def test_req_node_list_formatting(self) -> None:
        """Test ReqNodeList node formatting."""
        result = format_value("ReqNodeList", "gpu-node-[01-04]")
        assert "blue" in result

    def test_regular_value(self) -> None:
        """Test regular value without special formatting."""
        result = format_value("Account", "default")
        assert result == "default"

    def test_cancelled_state(self) -> None:
        """Test CANCELLED state formatting."""
        result = format_value("JobState", "CANCELLED")
        assert "magenta" in result

    def test_timeout_state(self) -> None:
        """Test TIMEOUT state formatting."""
        result = format_value("JobState", "TIMEOUT")
        assert "red" in result

    def test_node_fail_state(self) -> None:
        """Test NODE_FAIL state formatting."""
        result = format_value("JobState", "NODE_FAIL")
        assert "red" in result

    def test_preempted_state(self) -> None:
        """Test PREEMPTED state formatting."""
        result = format_value("JobState", "PREEMPTED")
        assert "yellow" in result

    def test_suspended_state(self) -> None:
        """Test SUSPENDED state formatting."""
        result = format_value("JobState", "SUSPENDED")
        assert "yellow" in result

    def test_completing_state(self) -> None:
        """Test COMPLETING state formatting."""
        result = format_value("JobState", "COMPLETING")
        assert "green" in result

    def test_unknown_state_uses_white(self) -> None:
        """Test unknown state uses white color."""
        result = format_value("JobState", "CUSTOMSTATE")
        assert "white" in result


class TestFormatCompactTimeline:
    """Tests for compact timeline formatting."""

    def test_running_job_shows_submit_and_start(self) -> None:
        """Test running job shows submit time and start time."""
        result = format_compact_timeline(
            "2024-01-15T10:30:00",
            "2024-01-15T10:35:00",
            "",
            "RUNNING",
        )
        assert "10:30" in result or "01-15" in result
        assert "10:35" in result or "01-15" in result
        assert "→" in result

    def test_pending_job_shows_submit_and_waiting(self) -> None:
        """Test pending job shows submit time with waiting icon."""
        result = format_compact_timeline(
            "2024-01-15T10:30:00",
            "Unknown",
            "",
            "PENDING",
        )
        assert "10:30" in result or "01-15" in result
        assert "⏳" in result

    def test_completed_job_shows_full_timeline(self) -> None:
        """Test completed job shows full timeline."""
        result = format_compact_timeline(
            "2024-01-15T10:30:00",
            "2024-01-15T10:35:00",
            "2024-01-15T11:00:00",
            "COMPLETED",
        )
        assert "10:30" in result or "01-15" in result
        assert "10:35" in result or "01-15" in result
        assert "11:00" in result or "01-15" in result

    def test_requeue_indicator_shown(self) -> None:
        """Test requeue indicator is shown when restarts > 0."""
        result = format_compact_timeline(
            "2024-01-15T10:30:00",
            "2024-01-15T10:35:00",
            "",
            "RUNNING",
            restarts=3,
        )
        assert "↻ 3" in result

    def test_handles_empty_times(self) -> None:
        """Test handling of empty time values."""
        result = format_compact_timeline("", "", "", "UNKNOWN")
        assert result == "—"

    def test_handles_unknown_start_time(self) -> None:
        """Test handling of Unknown start time."""
        result = format_compact_timeline(
            "2024-01-15T10:30:00",
            "Unknown",
            "",
            "RUNNING",
        )
        assert "⏳" in result

    def test_failed_job_shows_full_timeline(self) -> None:
        """Test failed job shows submit, start, and end times."""
        result = format_compact_timeline(
            "2024-01-15T10:30:00",
            "2024-01-15T10:35:00",
            "2024-01-15T10:40:00",
            "FAILED",
        )
        assert "→" in result
        assert "10:40" in result or "01-15" in result

    def test_cancelled_job_shows_timeline(self) -> None:
        """Test cancelled job shows timeline."""
        result = format_compact_timeline(
            "2024-01-15T10:30:00",
            "2024-01-15T10:35:00",
            "2024-01-15T10:36:00",
            "CANCELLED",
        )
        assert "→" in result

    def test_timeout_job_shows_timeline(self) -> None:
        """Test timeout job shows timeline."""
        result = format_compact_timeline(
            "2024-01-15T10:30:00",
            "2024-01-15T10:35:00",
            "2024-01-15T11:35:00",
            "TIMEOUT",
        )
        assert "→" in result

    def test_zero_restarts_no_indicator(self) -> None:
        """Test zero restarts does not show indicator."""
        result = format_compact_timeline(
            "2024-01-15T10:30:00",
            "2024-01-15T10:35:00",
            "",
            "RUNNING",
            restarts=0,
        )
        assert "↻" not in result

    def test_handles_na_time(self) -> None:
        """Test handling of N/A time value."""
        result = format_compact_timeline(
            "2024-01-15T10:30:00",
            "N/A",
            "",
            "RUNNING",
        )
        assert "⏳" in result

    def test_handles_none_time(self) -> None:
        """Test handling of None time value."""
        result = format_compact_timeline(
            "2024-01-15T10:30:00",
            "None",
            "",
            "RUNNING",
        )
        assert "⏳" in result


class TestFormatUserInfo:
    """Tests for format_user_info function."""

    def test_format_basic_user_info(self) -> None:
        """Test formatting basic user info."""
        user_stats = UserStats(
            username="testuser",
            job_count=3,
            total_cpus=32,
            total_memory_gb=128.0,
            total_gpus=4,
            total_nodes=2,
            gpu_types="4x A100",
        )
        jobs: list[tuple[str, ...]] = [
            ("12345", "train_model", "gpu", "R", "1:30:00", "2", "node01,node02", "cpu=16,mem=64G,gres/gpu=2"),
            ("12346", "preprocess", "cpu", "PD", "0:00:00", "1", "", "cpu=8,mem=32G"),
        ]

        result = format_user_info("testuser", user_stats, jobs)

        # Check summary section
        assert "User Summary" in result
        assert "testuser" in result
        assert "32" in result  # CPUs
        assert "128" in result  # Memory
        assert "4" in result  # GPUs
        assert "A100" in result  # GPU type

    def test_format_includes_job_counts(self) -> None:
        """Test that job counts by state are included."""
        user_stats = UserStats(
            username="testuser",
            job_count=2,
            total_cpus=16,
            total_memory_gb=64.0,
            total_gpus=0,
            total_nodes=1,
        )
        jobs: list[tuple[str, ...]] = [
            ("12345", "job1", "gpu", "RUNNING", "1:00:00", "1", "node01", ""),
            ("12346", "job2", "cpu", "PENDING", "0:00:00", "1", "", ""),
        ]

        result = format_user_info("testuser", user_stats, jobs)

        assert "Jobs by State" in result
        assert "Running" in result
        assert "Pending" in result

    def test_format_includes_job_list(self) -> None:
        """Test that job list is included."""
        user_stats = UserStats(
            username="testuser",
            job_count=1,
            total_cpus=8,
            total_memory_gb=32.0,
            total_gpus=0,
            total_nodes=1,
        )
        jobs: list[tuple[str, ...]] = [
            ("12345", "test_job", "default", "R", "0:30:00", "1", "node01", ""),
        ]

        result = format_user_info("testuser", user_stats, jobs)

        assert "Job List" in result
        assert "12345" in result
        assert "test_job" in result

    def test_format_empty_jobs_list(self) -> None:
        """Test formatting with no jobs."""
        user_stats = UserStats(
            username="testuser",
            job_count=0,
            total_cpus=0,
            total_memory_gb=0.0,
            total_gpus=0,
            total_nodes=0,
        )
        jobs: list[tuple[str, ...]] = []

        result = format_user_info("testuser", user_stats, jobs)

        assert "No active jobs" in result

    def test_format_job_state_colors_running(self) -> None:
        """Test that running state is colored green."""
        user_stats = UserStats(
            username="testuser",
            job_count=1,
            total_cpus=8,
            total_memory_gb=32.0,
            total_gpus=0,
            total_nodes=1,
        )
        jobs: list[tuple[str, ...]] = [
            ("12345", "job1", "gpu", "RUNNING", "1:00:00", "1", "node01", ""),
        ]

        result = format_user_info("testuser", user_stats, jobs)

        assert "green" in result

    def test_format_job_state_colors_pending(self) -> None:
        """Test that pending state is colored yellow."""
        user_stats = UserStats(
            username="testuser",
            job_count=1,
            total_cpus=8,
            total_memory_gb=32.0,
            total_gpus=0,
            total_nodes=1,
        )
        jobs: list[tuple[str, ...]] = [
            ("12345", "job1", "gpu", "PENDING", "0:00:00", "1", "", ""),
        ]

        result = format_user_info("testuser", user_stats, jobs)

        assert "yellow" in result

    def test_format_truncates_long_values(self) -> None:
        """Test that long values are truncated."""
        user_stats = UserStats(
            username="testuser",
            job_count=1,
            total_cpus=8,
            total_memory_gb=32.0,
            total_gpus=0,
            total_nodes=1,
        )
        jobs: list[tuple[str, ...]] = [
            ("123456789012345", "very_long_job_name_here", "long_partition_name", "R", "1:00:00", "1", "node01", ""),
        ]

        result = format_user_info("testuser", user_stats, jobs)

        # Should be truncated, not showing full strings
        assert "123456789012345"[:12] in result

    def test_format_without_gpu_types(self) -> None:
        """Test formatting when no GPU types are specified."""
        user_stats = UserStats(
            username="testuser",
            job_count=1,
            total_cpus=8,
            total_memory_gb=32.0,
            total_gpus=0,
            total_nodes=1,
            gpu_types="",
        )
        jobs: list[tuple[str, ...]] = []

        result = format_user_info("testuser", user_stats, jobs)

        # Should not include GPU Types line when empty
        # (it's included only if gpu_types is truthy)
        assert "User Summary" in result

    def test_format_with_gpu_types(self) -> None:
        """Test formatting when GPU types are specified."""
        user_stats = UserStats(
            username="testuser",
            job_count=1,
            total_cpus=8,
            total_memory_gb=32.0,
            total_gpus=4,
            total_nodes=1,
            gpu_types="4x H100",
        )
        jobs: list[tuple[str, ...]] = []

        result = format_user_info("testuser", user_stats, jobs)

        assert "GPU Types" in result
        assert "H100" in result
        assert "magenta" in result

    def test_format_skips_short_job_tuples(self) -> None:
        """Test that job tuples with fewer than 6 fields are skipped."""
        user_stats = UserStats(
            username="testuser",
            job_count=2,
            total_cpus=16,
            total_memory_gb=64.0,
            total_gpus=0,
            total_nodes=2,
        )
        jobs: list[tuple[str, ...]] = [
            ("12345", "job1", "gpu", "R", "1:00:00", "1", "node01", ""),  # Valid
            ("12346", "job2"),  # Too short, should be skipped
        ]

        result = format_user_info("testuser", user_stats, jobs)

        assert "12345" in result
        # 12346 should not appear in job list (but may appear in count)
