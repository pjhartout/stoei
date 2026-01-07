"""Tests for GPU parser utilities."""

from stoei.slurm.gpu_parser import (
    aggregate_gpu_counts,
    calculate_total_gpus,
    format_gpu_types,
    has_specific_gpu_types,
    parse_gpu_entries,
    parse_gpu_from_gres,
)


class TestParseGpuEntries:
    """Tests for parse_gpu_entries function."""

    def test_empty_string(self) -> None:
        """Test parsing empty string."""
        result = parse_gpu_entries("")
        assert result == []

    def test_no_gpu_entries(self) -> None:
        """Test parsing TRES without GPUs."""
        result = parse_gpu_entries("cpu=32,mem=256G,node=4")
        assert result == []

    def test_generic_gpu(self) -> None:
        """Test parsing generic GPU entry."""
        result = parse_gpu_entries("cpu=32,mem=256G,gres/gpu=8")
        assert result == [("gpu", 8)]

    def test_typed_gpu(self) -> None:
        """Test parsing typed GPU entry."""
        result = parse_gpu_entries("cpu=32,mem=256G,gres/gpu:h200=8")
        assert result == [("h200", 8)]

    def test_multiple_gpu_types(self) -> None:
        """Test parsing multiple GPU types."""
        result = parse_gpu_entries("gres/gpu:a100=4,gres/gpu:v100=2")
        assert ("a100", 4) in result
        assert ("v100", 2) in result

    def test_generic_and_typed(self) -> None:
        """Test parsing both generic and typed entries."""
        result = parse_gpu_entries("gres/gpu=8,gres/gpu:h200=8")
        assert ("gpu", 8) in result
        assert ("h200", 8) in result

    def test_case_insensitive(self) -> None:
        """Test case insensitivity."""
        result = parse_gpu_entries("GRES/GPU:H200=4")
        assert result == [("H200", 4)]


class TestParseGpuFromGres:
    """Tests for parse_gpu_from_gres function."""

    def test_empty_string(self) -> None:
        """Test parsing empty string."""
        result = parse_gpu_from_gres("")
        assert result == []

    def test_no_gpu(self) -> None:
        """Test parsing Gres without GPUs."""
        result = parse_gpu_from_gres("scratch:1T")
        assert result == []

    def test_simple_gpu(self) -> None:
        """Test parsing simple GPU count."""
        result = parse_gpu_from_gres("gpu:4")
        assert result == [("GPU", 4)]

    def test_typed_gpu(self) -> None:
        """Test parsing typed GPU."""
        result = parse_gpu_from_gres("gpu:a100:4")
        assert result == [("A100", 4)]

    def test_gpu_with_socket_info(self) -> None:
        """Test parsing GPU with socket info."""
        result = parse_gpu_from_gres("gpu:h200:8(S:0-1)")
        assert result == [("H200", 8)]

    def test_multiple_types(self) -> None:
        """Test parsing multiple GPU types."""
        result = parse_gpu_from_gres("gpu:a100:4,gpu:v100:2")
        assert ("A100", 4) in result
        assert ("V100", 2) in result


class TestHasSpecificGpuTypes:
    """Tests for has_specific_gpu_types function."""

    def test_empty_list(self) -> None:
        """Test empty list."""
        assert has_specific_gpu_types([]) is False

    def test_only_generic(self) -> None:
        """Test only generic GPU type."""
        assert has_specific_gpu_types([("gpu", 8)]) is False

    def test_only_specific(self) -> None:
        """Test only specific GPU type."""
        assert has_specific_gpu_types([("h200", 8)]) is True

    def test_mixed_types(self) -> None:
        """Test mixed generic and specific types."""
        assert has_specific_gpu_types([("gpu", 8), ("h200", 8)]) is True


class TestAggregateGpuCounts:
    """Tests for aggregate_gpu_counts function."""

    def test_empty_list(self) -> None:
        """Test empty list."""
        result = aggregate_gpu_counts([])
        assert result == {}

    def test_single_type(self) -> None:
        """Test single GPU type."""
        result = aggregate_gpu_counts([("h200", 8)])
        assert result == {"H200": 8}

    def test_multiple_same_type(self) -> None:
        """Test multiple entries of same type."""
        result = aggregate_gpu_counts([("h200", 4), ("h200", 4)])
        assert result == {"H200": 8}

    def test_skip_generic_when_specific_exists(self) -> None:
        """Test that generic is skipped when specific exists."""
        result = aggregate_gpu_counts([("gpu", 8), ("h200", 8)])
        assert result == {"H200": 8}
        assert "GPU" not in result

    def test_keep_generic_when_no_specific(self) -> None:
        """Test that generic is kept when no specific exists."""
        result = aggregate_gpu_counts([("gpu", 8)])
        assert result == {"GPU": 8}

    def test_no_skip_generic_when_disabled(self) -> None:
        """Test that generic is kept when skip is disabled."""
        result = aggregate_gpu_counts([("gpu", 8), ("h200", 8)], skip_generic_if_specific=False)
        assert result == {"GPU": 8, "H200": 8}


class TestFormatGpuTypes:
    """Tests for format_gpu_types function."""

    def test_empty_dict(self) -> None:
        """Test empty dictionary."""
        result = format_gpu_types({})
        assert result == ""

    def test_single_type(self) -> None:
        """Test single GPU type."""
        result = format_gpu_types({"H200": 8})
        assert result == "8x H200"

    def test_multiple_types_sorted(self) -> None:
        """Test multiple types are sorted."""
        result = format_gpu_types({"V100": 2, "A100": 4})
        assert result == "4x A100, 2x V100"


class TestCalculateTotalGpus:
    """Tests for calculate_total_gpus function."""

    def test_empty_list(self) -> None:
        """Test empty list."""
        result = calculate_total_gpus([])
        assert result == 0

    def test_single_type(self) -> None:
        """Test single GPU type."""
        result = calculate_total_gpus([("h200", 8)])
        assert result == 8

    def test_multiple_types(self) -> None:
        """Test multiple types."""
        result = calculate_total_gpus([("a100", 4), ("v100", 2)])
        assert result == 6

    def test_skip_generic_when_specific(self) -> None:
        """Test generic is not double-counted."""
        result = calculate_total_gpus([("gpu", 8), ("h200", 8)])
        assert result == 8  # Not 16
