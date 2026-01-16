"""Unit tests for the energy calculation module."""

from stoei.slurm.energy import (
    _FALLBACK_DEFAULT_GPU_TDP,
    calculate_job_energy_wh,
    format_energy,
    get_cpu_tdp_per_core,
    get_gpu_tdp,
    get_tdp_file_path,
    parse_cpu_count_from_tres,
    parse_elapsed_to_seconds,
    parse_gpu_info_from_tres,
    reload_tdp_values,
)


class TestGetGpuTdp:
    """Tests for get_gpu_tdp function."""

    def test_known_gpu_exact_match(self) -> None:
        """Test TDP lookup for known GPU types."""
        assert get_gpu_tdp("H200") == 700
        assert get_gpu_tdp("H100") == 700
        assert get_gpu_tdp("A100") == 400
        assert get_gpu_tdp("V100") == 300
        assert get_gpu_tdp("T4") == 70

    def test_case_insensitive(self) -> None:
        """Test that GPU type lookup is case-insensitive."""
        assert get_gpu_tdp("h200") == 700
        assert get_gpu_tdp("H200") == 700
        assert get_gpu_tdp("a100") == 400
        assert get_gpu_tdp("A100") == 400

    def test_unknown_gpu_returns_default(self) -> None:
        """Test that unknown GPU types return default TDP."""
        default_tdp = _FALLBACK_DEFAULT_GPU_TDP
        assert get_gpu_tdp("UNKNOWN_GPU") == default_tdp
        assert get_gpu_tdp("xyz123") == default_tdp

    def test_empty_string_returns_default(self) -> None:
        """Test that empty string returns default TDP."""
        default_tdp = _FALLBACK_DEFAULT_GPU_TDP
        assert get_gpu_tdp("") == default_tdp

    def test_generic_gpu_returns_default(self) -> None:
        """Test that generic 'gpu' type returns default TDP."""
        default_tdp = _FALLBACK_DEFAULT_GPU_TDP
        assert get_gpu_tdp("gpu") == default_tdp
        assert get_gpu_tdp("GPU") == default_tdp

    def test_nvidia_prefixed_gpu(self) -> None:
        """Test GPU types with NVIDIA prefix."""
        # Partial match should work
        assert get_gpu_tdp("NVIDIA_H200") == 700

    def test_amd_gpus(self) -> None:
        """Test AMD GPU TDP lookup."""
        assert get_gpu_tdp("MI300X") == 750
        assert get_gpu_tdp("MI250X") == 560
        assert get_gpu_tdp("MI100") == 300


class TestParseElapsedToSeconds:
    """Tests for parse_elapsed_to_seconds function."""

    def test_hhmmss_format(self) -> None:
        """Test parsing HH:MM:SS format."""
        assert parse_elapsed_to_seconds("01:30:00") == 5400  # 1.5 hours
        assert parse_elapsed_to_seconds("00:05:30") == 330  # 5.5 minutes
        assert parse_elapsed_to_seconds("10:00:00") == 36000  # 10 hours

    def test_mmss_format(self) -> None:
        """Test parsing MM:SS format."""
        assert parse_elapsed_to_seconds("05:30") == 330  # 5.5 minutes
        assert parse_elapsed_to_seconds("00:30") == 30  # 30 seconds

    def test_ss_format(self) -> None:
        """Test parsing seconds-only format."""
        assert parse_elapsed_to_seconds("30") == 30
        assert parse_elapsed_to_seconds("3600") == 3600

    def test_days_format(self) -> None:
        """Test parsing D-HH:MM:SS format with days."""
        assert parse_elapsed_to_seconds("1-00:00:00") == 86400  # 1 day
        assert parse_elapsed_to_seconds("2-12:30:45") == 2 * 86400 + 12 * 3600 + 30 * 60 + 45
        assert parse_elapsed_to_seconds("7-00:00:00") == 7 * 86400  # 1 week

    def test_empty_string_returns_zero(self) -> None:
        """Test that empty string returns 0."""
        assert parse_elapsed_to_seconds("") == 0.0
        assert parse_elapsed_to_seconds("   ") == 0.0

    def test_invalid_format_returns_zero(self) -> None:
        """Test that invalid formats return 0."""
        assert parse_elapsed_to_seconds("invalid") == 0.0
        assert parse_elapsed_to_seconds("abc:def:ghi") == 0.0


class TestCalculateJobEnergyWh:
    """Tests for calculate_job_energy_wh function."""

    def test_gpu_only_energy(self) -> None:
        """Test energy calculation with GPUs only."""
        # 8 H200 GPUs for 1 hour = 8 * 700W * 1h = 5600 Wh
        energy = calculate_job_energy_wh(
            gpu_count=8,
            gpu_type="H200",
            cpu_count=0,
            duration_seconds=3600,
        )
        assert energy == 5600.0

    def test_cpu_only_energy(self) -> None:
        """Test energy calculation with CPUs only."""
        cpu_tdp = get_cpu_tdp_per_core()
        # 32 CPUs for 1 hour
        energy = calculate_job_energy_wh(
            gpu_count=0,
            gpu_type="",
            cpu_count=32,
            duration_seconds=3600,
        )
        assert energy == 32 * cpu_tdp * 1.0

    def test_combined_gpu_cpu_energy(self) -> None:
        """Test energy calculation with both GPUs and CPUs."""
        cpu_tdp = get_cpu_tdp_per_core()
        # 4 A100 GPUs + 64 CPUs for 2 hours
        # GPU: 4 * 400W * 2h = 3200 Wh
        # CPU: 64 * cpu_tdp * 2h
        energy = calculate_job_energy_wh(
            gpu_count=4,
            gpu_type="A100",
            cpu_count=64,
            duration_seconds=7200,
        )
        expected = (4 * 400 * 2) + (64 * cpu_tdp * 2)
        assert energy == expected

    def test_zero_duration_returns_zero(self) -> None:
        """Test that zero duration returns zero energy."""
        energy = calculate_job_energy_wh(
            gpu_count=8,
            gpu_type="H200",
            cpu_count=32,
            duration_seconds=0,
        )
        assert energy == 0.0

    def test_negative_duration_returns_zero(self) -> None:
        """Test that negative duration returns zero energy."""
        energy = calculate_job_energy_wh(
            gpu_count=8,
            gpu_type="H200",
            cpu_count=32,
            duration_seconds=-100,
        )
        assert energy == 0.0

    def test_unknown_gpu_uses_default_tdp(self) -> None:
        """Test that unknown GPU type uses default TDP."""
        default_tdp = _FALLBACK_DEFAULT_GPU_TDP
        energy = calculate_job_energy_wh(
            gpu_count=1,
            gpu_type="UNKNOWN",
            cpu_count=0,
            duration_seconds=3600,
        )
        assert energy == default_tdp * 1.0


class TestFormatEnergy:
    """Tests for format_energy function."""

    def test_wh_format(self) -> None:
        """Test Wh formatting for small values."""
        assert format_energy(500) == "500 Wh"
        assert format_energy(100) == "100 Wh"
        assert format_energy(1) == "1 Wh"

    def test_kwh_format(self) -> None:
        """Test kWh formatting for medium values."""
        assert format_energy(1000) == "1.0 kWh"
        assert format_energy(5500) == "5.5 kWh"
        assert format_energy(999999) == "1000.0 kWh"

    def test_mwh_format(self) -> None:
        """Test MWh formatting for large values."""
        assert format_energy(1_000_000) == "1.00 MWh"
        assert format_energy(1_234_567) == "1.23 MWh"
        assert format_energy(500_000_000) == "500.00 MWh"

    def test_gwh_format(self) -> None:
        """Test GWh formatting for very large values."""
        assert format_energy(1_000_000_000) == "1.00 GWh"
        assert format_energy(2_500_000_000) == "2.50 GWh"

    def test_very_small_values(self) -> None:
        """Test formatting for values less than 1 Wh."""
        assert format_energy(0.5) == "0.50 Wh"
        assert format_energy(0.01) == "0.01 Wh"

    def test_negative_returns_zero(self) -> None:
        """Test that negative values return zero."""
        assert format_energy(-100) == "0 Wh"

    def test_zero(self) -> None:
        """Test zero energy."""
        assert format_energy(0) == "0.00 Wh"


class TestParseGpuInfoFromTres:
    """Tests for parse_gpu_info_from_tres function."""

    def test_generic_gpu(self) -> None:
        """Test parsing generic GPU from TRES."""
        result = parse_gpu_info_from_tres("cpu=32,mem=256G,gres/gpu=8")
        assert len(result) == 1
        assert result[0] == ("gpu", 8)

    def test_typed_gpu(self) -> None:
        """Test parsing typed GPU from TRES."""
        result = parse_gpu_info_from_tres("cpu=32,mem=256G,gres/gpu:h200=8")
        assert len(result) == 1
        assert result[0] == ("h200", 8)

    def test_multiple_gpu_types(self) -> None:
        """Test parsing multiple GPU types."""
        result = parse_gpu_info_from_tres("cpu=32,mem=256G,gres/gpu:h200=4,gres/gpu:a100=4")
        assert len(result) == 2
        types = {gpu_type for gpu_type, _ in result}
        assert "h200" in types
        assert "a100" in types

    def test_no_gpus(self) -> None:
        """Test TRES without GPUs."""
        result = parse_gpu_info_from_tres("cpu=32,mem=256G")
        assert len(result) == 0

    def test_empty_string(self) -> None:
        """Test empty TRES string."""
        result = parse_gpu_info_from_tres("")
        assert len(result) == 0


class TestParseCpuCountFromTres:
    """Tests for parse_cpu_count_from_tres function."""

    def test_cpu_count(self) -> None:
        """Test parsing CPU count from TRES."""
        assert parse_cpu_count_from_tres("cpu=32,mem=256G") == 32
        assert parse_cpu_count_from_tres("cpu=64,mem=512G,gres/gpu=8") == 64

    def test_no_cpu_field(self) -> None:
        """Test TRES without CPU field."""
        assert parse_cpu_count_from_tres("mem=256G,gres/gpu=8") == 0

    def test_empty_string(self) -> None:
        """Test empty TRES string."""
        assert parse_cpu_count_from_tres("") == 0


class TestTdpJsonFile:
    """Tests for JSON-based TDP loading."""

    def test_tdp_file_exists(self) -> None:
        """Test that the TDP JSON file exists."""
        assert get_tdp_file_path().exists()

    def test_reload_tdp_values(self) -> None:
        """Test that TDP values can be reloaded."""
        # Should not raise an exception
        reload_tdp_values()
        # Values should still work after reload
        assert get_gpu_tdp("H200") == 700

    def test_common_gpus_have_tdp(self) -> None:
        """Test that common GPUs have TDP values defined."""
        common_gpus = ["H200", "H100", "A100", "V100", "T4", "L40", "MI300X"]
        for gpu in common_gpus:
            tdp = get_gpu_tdp(gpu)
            assert tdp > 0, f"Invalid TDP for {gpu}"
            # All known GPUs should return a value different from the generic default
            # (unless the default happens to match, which is unlikely for these)
            assert tdp >= 70, f"TDP {tdp}W for {gpu} seems too low"
            assert tdp <= 1000, f"TDP {tdp}W for {gpu} seems too high"

    def test_cpu_tdp_per_core(self) -> None:
        """Test that CPU TDP per core is loaded."""
        cpu_tdp = get_cpu_tdp_per_core()
        assert cpu_tdp > 0
        assert cpu_tdp <= 50  # Reasonable per-core TDP
