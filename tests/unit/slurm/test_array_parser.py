"""Tests for array job parsing utilities."""

from stoei.slurm.array_parser import parse_array_size


class TestParseArraySize:
    """Tests for parse_array_size function."""

    def test_regular_job_id(self) -> None:
        """Regular job ID returns 1."""
        assert parse_array_size("12345") == 1

    def test_single_array_task(self) -> None:
        """Single array task (e.g., 12345_5) returns 1."""
        assert parse_array_size("12345_5") == 1
        assert parse_array_size("12345_0") == 1
        assert parse_array_size("12345_99") == 1

    def test_simple_range_zero_based(self) -> None:
        """Simple range starting from 0 (e.g., [0-99]) returns correct count."""
        assert parse_array_size("12345_[0-99]") == 100
        assert parse_array_size("12345_[0-9]") == 10
        assert parse_array_size("12345_[0-0]") == 1

    def test_simple_range_one_based(self) -> None:
        """Simple range starting from 1 (e.g., [1-100]) returns correct count."""
        assert parse_array_size("12345_[1-100]") == 100
        assert parse_array_size("12345_[1-10]") == 10
        assert parse_array_size("12345_[5-15]") == 11

    def test_range_with_throttle(self) -> None:
        """Range with throttle (e.g., [0-99%5]) returns task count, not throttle."""
        assert parse_array_size("12345_[0-99%5]") == 100
        assert parse_array_size("12345_[0-99%10]") == 100
        assert parse_array_size("12345_[1-50%2]") == 50

    def test_comma_separated_list(self) -> None:
        """Comma-separated list returns correct count."""
        assert parse_array_size("12345_[1,3,5]") == 3
        assert parse_array_size("12345_[0,1,2,3,4]") == 5
        assert parse_array_size("12345_[10]") == 1

    def test_mixed_list_and_range(self) -> None:
        """Mixed list and range returns correct count."""
        assert parse_array_size("12345_[1,3,5,7-10]") == 7  # 1,3,5 + 7,8,9,10
        assert parse_array_size("12345_[0-4,10,20]") == 7  # 0,1,2,3,4 + 10 + 20
        assert parse_array_size("12345_[1-3,5-7]") == 6  # 1,2,3 + 5,6,7

    def test_empty_string(self) -> None:
        """Empty string returns 1."""
        assert parse_array_size("") == 1

    def test_none_value(self) -> None:
        """None value returns 1."""
        assert parse_array_size(None) == 1  # type: ignore[arg-type]

    def test_whitespace_handling(self) -> None:
        """Whitespace is properly trimmed."""
        assert parse_array_size("  12345_[0-9]  ") == 10
        assert parse_array_size("12345") == 1

    def test_malformed_brackets(self) -> None:
        """Malformed bracket notation returns 1."""
        assert parse_array_size("12345_[") == 1
        assert parse_array_size("12345_[]") == 1
        assert parse_array_size("12345_[abc]") == 1

    def test_large_array(self) -> None:
        """Large array sizes are handled correctly."""
        assert parse_array_size("12345_[0-999]") == 1000
        assert parse_array_size("12345_[0-9999]") == 10000

    def test_real_world_examples(self) -> None:
        """Real-world SLURM job ID examples."""
        # From squeue output
        assert parse_array_size("47474_5") == 1  # Single task from array
        assert parse_array_size("47462_11") == 1  # Single task from array
        assert parse_array_size("47441") == 1  # Regular job
        # Pending array notation
        assert parse_array_size("47700_[0-49]") == 50
        assert parse_array_size("47700_[0-99%10]") == 100


class TestEdgeCases:
    """Edge case tests for array parser."""

    def test_invalid_range_start_greater_than_end(self) -> None:
        """Invalid range where start > end returns 1."""
        assert parse_array_size("12345_[10-5]") == 1

    def test_non_numeric_in_brackets(self) -> None:
        """Non-numeric content in brackets returns 1."""
        assert parse_array_size("12345_[a-b]") == 1
        assert parse_array_size("12345_[foo]") == 1

    def test_underscore_but_no_array(self) -> None:
        """Job ID with underscore but no array notation returns 1."""
        assert parse_array_size("12345_abc") == 1
        assert parse_array_size("job_name_123") == 1
