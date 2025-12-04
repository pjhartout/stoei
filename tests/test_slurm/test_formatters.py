"""Tests for SLURM output formatters."""

from stoei.slurm.formatters import format_job_info, format_value


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
