package store

import (
	"testing"

	"github.com/pjhartout/stoei/internal/slurm"
)

func TestGetGPUTDP(t *testing.T) {
	cases := []struct {
		in   string
		want int
	}{
		{"H200", 700},
		{"H100", 700},
		{"A100", 400},
		{"V100", 300},
		{"T4", 70},
		{"h200", 700}, // case-insensitive
		{"a100", 400},
		{"UNKNOWN_GPU", fallbackDefaultGPUTDP},
		{"xyz123", fallbackDefaultGPUTDP},
		{"", fallbackDefaultGPUTDP},
		{"gpu", fallbackDefaultGPUTDP}, // generic
		{"NVIDIA_H200", 700},           // prefix strip / partial
		{"MI300X", 750},
		{"MI250X", 560},
		{"MI100", 300},
		{"A10", 150},
		{"A10G", 150},
		// Verbose gres.conf Type labels must match the specific model via the
		// declaration-order partial scan, not the alphabetically-earlier substring
		// (A100 -> 400, not A10 -> 150). Regression for the energy undercount.
		{"NVIDIA_A100_SXM4_80GB", 400},
		{"A100_SXM4", 400},
		{"A100X", 400},
	}
	for _, c := range cases {
		if got := GetGPUTDP(c.in); got != c.want {
			t.Errorf("GetGPUTDP(%q) = %d; want %d", c.in, got, c.want)
		}
	}
}

func TestCPUTDPPerCore(t *testing.T) {
	if got := CPUTDPPerCore(); got != 10 {
		t.Errorf("CPUTDPPerCore() = %d; want 10", got)
	}
}

func TestCalculateJobEnergyWh(t *testing.T) {
	cpuTDP := float64(CPUTDPPerCore())
	cases := []struct {
		name     string
		gpuCount int
		gpuType  string
		cpuCount int
		seconds  float64
		want     float64
	}{
		{"gpu only", 8, "H200", 0, 3600, 5600.0},
		{"cpu only", 0, "", 32, 3600, 32 * cpuTDP},
		{"combined", 4, "A100", 64, 7200, (4 * 400 * 2) + (64 * cpuTDP * 2)},
		{"zero duration", 8, "H200", 32, 0, 0},
		{"negative duration", 8, "H200", 32, -100, 0},
		{"unknown gpu uses default", 1, "UNKNOWN", 0, 3600, fallbackDefaultGPUTDP},
	}
	for _, c := range cases {
		got := CalculateJobEnergyWh(c.gpuCount, c.gpuType, c.cpuCount, c.seconds)
		if got != c.want {
			t.Errorf("%s: CalculateJobEnergyWh = %v; want %v", c.name, got, c.want)
		}
	}
}

func TestFormatEnergy(t *testing.T) {
	cases := []struct {
		in   float64
		want string
	}{
		{500, "500 Wh"},
		{100, "100 Wh"},
		{1, "1 Wh"},
		{1000, "1.0 kWh"},
		{5500, "5.5 kWh"},
		{999999, "1000.0 kWh"},
		{1_000_000, "1.00 MWh"},
		{1_234_567, "1.23 MWh"},
		{500_000_000, "500.00 MWh"},
		{1_000_000_000, "1.00 GWh"},
		{2_500_000_000, "2.50 GWh"},
		{0.5, "0.50 Wh"},
		{0.01, "0.01 Wh"},
		{-5, "0 Wh"},
	}
	for _, c := range cases {
		if got := FormatEnergy(c.in); got != c.want {
			t.Errorf("FormatEnergy(%v) = %q; want %q", c.in, got, c.want)
		}
	}
}

func TestAggregateEnergyStats(t *testing.T) {
	records := []slurm.EnergyRecord{
		{JobID: "1", User: "alice", Elapsed: "01:00:00", NCPUS: "32", AllocTRES: "cpu=32,mem=64G,gres/gpu:h200=8", State: "COMPLETED"},
		{JobID: "2", User: "alice", Elapsed: "00:30:00", NCPUS: "16", AllocTRES: "cpu=16", State: "COMPLETED"},
		{JobID: "3", User: "bob", Elapsed: "02:00:00", NCPUS: "", AllocTRES: "cpu=8,gres/gpu:a100=4", State: "COMPLETED"},
		{JobID: "4", User: "carol", Elapsed: "00:00:00", NCPUS: "8", AllocTRES: "cpu=8", State: "COMPLETED"},
	}
	got := AggregateEnergyStats(records)

	// Sorted by total energy descending: alice (6000) then bob (3360). carol
	// (zero duration) is skipped.
	if len(got) != 2 {
		t.Fatalf("len = %d; want 2 (carol skipped): %+v", len(got), got)
	}
	if got[0].Username != "alice" || got[0].TotalEnergyWh != 6000.0 || got[0].JobCount != 2 ||
		got[0].GPUHours != 8.0 || got[0].CPUHours != 40.0 {
		t.Errorf("alice = %+v; want energy 6000 jobs 2 gpuh 8 cpuh 40", got[0])
	}
	if got[1].Username != "bob" || got[1].TotalEnergyWh != 3360.0 || got[1].JobCount != 1 ||
		got[1].GPUHours != 8.0 || got[1].CPUHours != 16.0 {
		t.Errorf("bob = %+v; want energy 3360 jobs 1 gpuh 8 cpuh 16", got[1])
	}
}
