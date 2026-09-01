package store

import (
	"testing"

	"github.com/pjhartout/stoei/internal/slurm"
)

func TestDeriveJobEfficiencySacctCarriesAllocation(t *testing.T) {
	u := slurm.JobUsage{
		Source:         "sacct",
		Sampled:        true,
		ElapsedSec:     1000,
		AllocCPUs:      4,
		GPUs:           []slurm.GPUEntry{{Type: "h100", Count: 1}},
		CPUTimeSec:     2000,
		MaxRSSBytes:    1 << 30,
		DiskReadBytes:  4000,
		DiskWriteBytes: 2000,
		GPUUtilPercent: 43,
		GPUUtilKnown:   true,
		GPUMemBytes:    14 << 30,
		GPUMemKnown:    true,
	}
	eff := DeriveJobEfficiency(u, map[string]string{"TRES": "cpu=4,mem=2G,node=1"})

	if !eff.CPUKnown || eff.CPUPercent != 50 {
		t.Errorf("CPU%% = %v (known=%v), want 50", eff.CPUPercent, eff.CPUKnown)
	}
	if eff.Live {
		t.Error("sacct usage flagged live")
	}
	if !eff.MemKnown || eff.MemPercent != 50 {
		t.Errorf("Mem%% = %v (known=%v), want 50", eff.MemPercent, eff.MemKnown)
	}
	if eff.GPUCount != 1 || !eff.GPUUtilKnown || eff.GPUUtilPercent != 43 {
		t.Errorf("GPU util = %v over %d GPUs (known=%v), want 43 over 1", eff.GPUUtilPercent, eff.GPUCount, eff.GPUUtilKnown)
	}
	if eff.ReadBytesPerSec != 4 || eff.WriteBytesPerSec != 2 {
		t.Errorf("IO rates = %v/%v, want 4/2", eff.ReadBytesPerSec, eff.WriteBytesPerSec)
	}
}

func TestDeriveJobEfficiencySstatFillsAllocationFromFields(t *testing.T) {
	u := slurm.JobUsage{Source: "sstat", Sampled: true, CPUTimeSec: 71}
	fields := map[string]string{
		"RunTime": "00:01:06",
		"NumCPUs": "2",
		"TRES":    "cpu=2,mem=2G,node=1",
	}
	eff := DeriveJobEfficiency(u, fields)

	if !eff.Live {
		t.Error("sstat usage not flagged live")
	}
	if !eff.CPUKnown {
		t.Fatal("CPU efficiency unknown despite RunTime and NumCPUs fields")
	}
	if eff.CPUAvailSec != 132 {
		t.Errorf("CPUAvailSec = %v, want 132", eff.CPUAvailSec)
	}
	if eff.CPUPercent < 53 || eff.CPUPercent > 54 {
		t.Errorf("CPU%% = %v, want ~53.8", eff.CPUPercent)
	}
}

// TestDeriveJobEfficiencyMemFromAllocTRES covers newer scontrol output, which
// emits AllocTRES/ReqTRES instead of the older bare TRES field.
func TestDeriveJobEfficiencyMemFromAllocTRES(t *testing.T) {
	u := slurm.JobUsage{Source: "sstat", Sampled: true, MaxRSSBytes: 1 << 30}
	eff := DeriveJobEfficiency(u, map[string]string{"AllocTRES": "cpu=8,mem=4G,node=1,billing=8"})
	if !eff.MemKnown || eff.MemPercent != 25 {
		t.Errorf("Mem%% = %v (known=%v), want 25 from AllocTRES", eff.MemPercent, eff.MemKnown)
	}
}

func TestDeriveJobEfficiencyMIGUtilNotAMeasurement(t *testing.T) {
	u := slurm.JobUsage{
		Source:       "sacct",
		Sampled:      true,
		GPUUtilKnown: true, // accounted as 0, but NVML cannot sample MIG
		GPUMemBytes:  12 << 30,
		GPUMemKnown:  true,
	}
	fields := map[string]string{"TresPerNode": "gres/gpu:h100_pcie_2g.20gb:1"}
	eff := DeriveJobEfficiency(u, fields)

	if !eff.GPUIsMIG {
		t.Error("MIG slice not detected from TresPerNode")
	}
	if eff.GPUUtilKnown {
		t.Error("MIG utilization presented as a measurement")
	}
	if !eff.GPUMemKnown {
		t.Error("MIG GPU memory dropped; it is measured")
	}
}

func TestDeriveJobEfficiencyMultiGPUUtilNormalizedAndClamped(t *testing.T) {
	u := slurm.JobUsage{
		Source:         "sacct",
		Sampled:        true,
		ElapsedSec:     100,
		AllocCPUs:      1,
		GPUs:           []slurm.GPUEntry{{Type: "h100", Count: 3}},
		GPUUtilPercent: 333, // accounted sum across 3 GPUs; slight oversampling
		GPUUtilKnown:   true,
	}
	eff := DeriveJobEfficiency(u, nil)

	if eff.GPUCount != 3 {
		t.Errorf("GPUCount = %d, want 3", eff.GPUCount)
	}
	if eff.GPUUtilPercent != 100 {
		t.Errorf("GPU util = %v, want clamped 100", eff.GPUUtilPercent)
	}
}

func TestDeriveJobEfficiencyUnsampled(t *testing.T) {
	u := slurm.JobUsage{Source: "sacct", ElapsedSec: 10, AllocCPUs: 2}
	eff := DeriveJobEfficiency(u, nil)
	if eff.Sampled || eff.CPUKnown || eff.MemKnown {
		t.Errorf("unsampled job derived metrics: %+v", eff)
	}
}
