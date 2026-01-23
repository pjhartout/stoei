"""Tests for wait time calculation utilities."""

from stoei.slurm.wait_time import (
    PartitionWaitStats,
    calculate_partition_wait_stats,
    calculate_wait_time_seconds,
    format_wait_time,
    parse_slurm_timestamp,
)


class TestParseSlumTimestamp:
    """Tests for parse_slurm_timestamp function."""

    def test_parse_valid_timestamp(self) -> None:
        """Test parsing a valid SLURM timestamp."""
        result = parse_slurm_timestamp("2024-01-15T10:30:00")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30
        assert result.second == 0

    def test_parse_invalid_timestamp(self) -> None:
        """Test parsing an invalid timestamp format."""
        result = parse_slurm_timestamp("not-a-timestamp")
        assert result is None

    def test_parse_unknown_timestamp(self) -> None:
        """Test parsing 'Unknown' timestamp."""
        assert parse_slurm_timestamp("Unknown") is None
        assert parse_slurm_timestamp("None") is None
        assert parse_slurm_timestamp("N/A") is None
        assert parse_slurm_timestamp("") is None

    def test_parse_timestamp_with_whitespace(self) -> None:
        """Test parsing timestamp with surrounding whitespace."""
        result = parse_slurm_timestamp("  2024-01-15T10:30:00  ")
        assert result is not None
        assert result.year == 2024


class TestCalculateWaitTime:
    """Tests for calculate_wait_time_seconds function."""

    def test_calculate_valid_times(self) -> None:
        """Test calculating wait time with valid timestamps."""
        submit = "2024-01-15T10:30:00"
        start = "2024-01-15T10:35:00"
        result = calculate_wait_time_seconds(submit, start)
        assert result == 300.0  # 5 minutes = 300 seconds

    def test_calculate_missing_start(self) -> None:
        """Test with missing/unknown start time."""
        submit = "2024-01-15T10:30:00"
        result = calculate_wait_time_seconds(submit, "Unknown")
        assert result is None

    def test_calculate_missing_submit(self) -> None:
        """Test with missing/unknown submit time."""
        start = "2024-01-15T10:35:00"
        result = calculate_wait_time_seconds("Unknown", start)
        assert result is None

    def test_calculate_invalid_times(self) -> None:
        """Test with invalid timestamp formats."""
        result = calculate_wait_time_seconds("invalid", "also-invalid")
        assert result is None

    def test_calculate_zero_wait_time(self) -> None:
        """Test when submit and start are the same."""
        timestamp = "2024-01-15T10:30:00"
        result = calculate_wait_time_seconds(timestamp, timestamp)
        assert result == 0.0

    def test_calculate_negative_wait_time(self) -> None:
        """Test when start is before submit (data error)."""
        submit = "2024-01-15T10:35:00"
        start = "2024-01-15T10:30:00"
        result = calculate_wait_time_seconds(submit, start)
        assert result is None  # Should return None for negative wait

    def test_calculate_long_wait_time(self) -> None:
        """Test calculating a long wait time (hours)."""
        submit = "2024-01-15T10:00:00"
        start = "2024-01-15T12:30:00"
        result = calculate_wait_time_seconds(submit, start)
        assert result == 9000.0  # 2.5 hours = 9000 seconds


class TestFormatWaitTime:
    """Tests for format_wait_time function."""

    def test_format_seconds(self) -> None:
        """Test formatting seconds."""
        assert format_wait_time(0) == "0s"
        assert format_wait_time(30) == "30s"
        assert format_wait_time(59) == "59s"

    def test_format_minutes(self) -> None:
        """Test formatting minutes."""
        assert format_wait_time(60) == "1m"
        assert format_wait_time(300) == "5m"
        assert format_wait_time(3599) == "59m"

    def test_format_hours(self) -> None:
        """Test formatting hours."""
        assert format_wait_time(3600) == "1.0h"
        assert format_wait_time(7200) == "2.0h"
        assert format_wait_time(36000) == "10h"  # >= 10 hours shows integer
        assert format_wait_time(86399) == "23h"  # Just under 24 hours

    def test_format_days(self) -> None:
        """Test formatting days."""
        assert format_wait_time(86400) == "1.0d"
        assert format_wait_time(172800) == "2.0d"
        assert format_wait_time(864000) == "10d"  # >= 10 days shows integer

    def test_format_negative(self) -> None:
        """Test formatting negative values."""
        assert format_wait_time(-1) == "0s"
        assert format_wait_time(-100) == "0s"


class TestCalculatePartitionWaitStats:
    """Tests for calculate_partition_wait_stats function."""

    def test_single_partition(self) -> None:
        """Test with jobs in a single partition."""
        jobs = [
            ("12345", "gpu-a100", "COMPLETED", "2024-01-15T10:00:00", "2024-01-15T10:05:00"),
            ("12346", "gpu-a100", "COMPLETED", "2024-01-15T10:10:00", "2024-01-15T10:15:00"),
            ("12347", "gpu-a100", "COMPLETED", "2024-01-15T10:20:00", "2024-01-15T10:30:00"),
        ]
        result = calculate_partition_wait_stats(jobs)

        assert "gpu-a100" in result
        stats = result["gpu-a100"]
        assert stats.job_count == 3
        assert stats.min_seconds == 300.0  # 5 minutes
        assert stats.max_seconds == 600.0  # 10 minutes
        # Mean of [300, 300, 600] = 400
        assert stats.mean_seconds == 400.0
        # Median of [300, 300, 600] = 300
        assert stats.median_seconds == 300.0

    def test_multiple_partitions(self) -> None:
        """Test with jobs across multiple partitions."""
        jobs = [
            ("12345", "gpu-a100", "COMPLETED", "2024-01-15T10:00:00", "2024-01-15T10:05:00"),
            ("12346", "cpu", "COMPLETED", "2024-01-15T10:00:00", "2024-01-15T10:01:00"),
            ("12347", "gpu-h200", "COMPLETED", "2024-01-15T10:00:00", "2024-01-15T10:30:00"),
        ]
        result = calculate_partition_wait_stats(jobs)

        assert len(result) == 3
        assert "gpu-a100" in result
        assert "cpu" in result
        assert "gpu-h200" in result

        assert result["gpu-a100"].mean_seconds == 300.0  # 5 min
        assert result["cpu"].mean_seconds == 60.0  # 1 min
        assert result["gpu-h200"].mean_seconds == 1800.0  # 30 min

    def test_empty_jobs(self) -> None:
        """Test with empty job list."""
        result = calculate_partition_wait_stats([])
        assert result == {}

    def test_jobs_without_start_time(self) -> None:
        """Test filtering out jobs without valid start times."""
        jobs = [
            ("12345", "gpu-a100", "PENDING", "2024-01-15T10:00:00", "Unknown"),
            ("12346", "gpu-a100", "COMPLETED", "2024-01-15T10:00:00", "2024-01-15T10:05:00"),
            ("12347", "gpu-a100", "PENDING", "2024-01-15T10:00:00", ""),
        ]
        result = calculate_partition_wait_stats(jobs)

        # Only one job should have valid wait time
        assert "gpu-a100" in result
        assert result["gpu-a100"].job_count == 1
        assert result["gpu-a100"].mean_seconds == 300.0

    def test_jobs_with_missing_fields(self) -> None:
        """Test handling jobs with missing fields."""
        jobs = [
            ("12345", "gpu-a100"),  # Missing fields
            ("12346", "gpu-a100", "COMPLETED", "2024-01-15T10:00:00", "2024-01-15T10:05:00"),
        ]
        result = calculate_partition_wait_stats(jobs)

        # Only the complete job should be counted
        assert "gpu-a100" in result
        assert result["gpu-a100"].job_count == 1

    def test_unknown_partition(self) -> None:
        """Test handling jobs with empty partition."""
        jobs = [
            ("12345", "", "COMPLETED", "2024-01-15T10:00:00", "2024-01-15T10:05:00"),
        ]
        result = calculate_partition_wait_stats(jobs)

        assert "unknown" in result
        assert result["unknown"].job_count == 1


class TestPartitionWaitStatsDataclass:
    """Tests for PartitionWaitStats dataclass."""

    def test_dataclass_creation(self) -> None:
        """Test creating a PartitionWaitStats instance."""
        stats = PartitionWaitStats(
            partition="gpu-a100",
            job_count=10,
            mean_seconds=300.0,
            median_seconds=250.0,
            min_seconds=60.0,
            max_seconds=3600.0,
        )
        assert stats.partition == "gpu-a100"
        assert stats.job_count == 10
        assert stats.mean_seconds == 300.0
        assert stats.median_seconds == 250.0
        assert stats.min_seconds == 60.0
        assert stats.max_seconds == 3600.0
