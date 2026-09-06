package slurm

import (
	"context"
	"strings"
	"testing"
)

func TestParseSacctUsageCPUJob(t *testing.T) {
	u := ParseSacctUsage("5834914", loadFixture(t, "sacct_usage_cpu.txt"))

	if u.Source != "sacct" {
		t.Errorf("Source = %q, want sacct", u.Source)
	}
	if !u.Sampled {
		t.Error("Sampled = false, want true")
	}
	if u.ElapsedSec != 171 {
		t.Errorf("ElapsedSec = %v, want 171", u.ElapsedSec)
	}
	if u.AllocCPUs != 4 {
		t.Errorf("AllocCPUs = %d, want 4", u.AllocCPUs)
	}
	// TotalCPU "02:51.306" is MM:SS.fraction.
	if u.CPUTimeSec < 171.3 || u.CPUTimeSec > 171.4 {
		t.Errorf("CPUTimeSec = %v, want ~171.306", u.CPUTimeSec)
	}
	if want := int64(2502) * 1024; u.MaxRSSBytes != want {
		t.Errorf("MaxRSSBytes = %d, want %d", u.MaxRSSBytes, want)
	}
	if u.DiskReadBytes != 32225772153 {
		t.Errorf("DiskReadBytes = %d, want 32225772153", u.DiskReadBytes)
	}
	if u.DiskWriteBytes != 1572864182 {
		t.Errorf("DiskWriteBytes = %d, want 1572864182", u.DiskWriteBytes)
	}
	if len(u.GPUs) != 0 || u.GPUUtilKnown || u.GPUMemKnown {
		t.Errorf("CPU job reports GPU data: %+v", u)
	}
}

func TestParseSacctUsageGPUJobAggregatesSteps(t *testing.T) {
	u := ParseSacctUsage("5184910_0", loadFixture(t, "sacct_usage_gpu.txt"))

	// TotalCPU "3-00:07:34" = 3 days + 454s.
	if want := float64(3*86400 + 454); u.CPUTimeSec != want {
		t.Errorf("CPUTimeSec = %v, want %v", u.CPUTimeSec, want)
	}
	if u.AllocCPUs != 32 {
		t.Errorf("AllocCPUs = %d, want 32", u.AllocCPUs)
	}
	if got := CalculateTotalGPUs(u.GPUs, true); got != 1 {
		t.Errorf("total GPUs = %d, want 1", got)
	}
	// Peak RSS is the max across steps (the batch step), not a later
	// small srun step.
	if want := int64(53418351) * 1024; u.MaxRSSBytes != want {
		t.Errorf("MaxRSSBytes = %d, want %d", u.MaxRSSBytes, want)
	}
	// Cumulative IO sums across the batch and the four srun steps.
	if u.DiskReadBytes != 14756614381 {
		t.Errorf("DiskReadBytes = %d, want 14756614381", u.DiskReadBytes)
	}
	if want := int64(22090669336 + 4); u.DiskWriteBytes != want {
		t.Errorf("DiskWriteBytes = %d, want %d", u.DiskWriteBytes, want)
	}
	if !u.GPUUtilKnown || u.GPUUtilPercent != 43 {
		t.Errorf("GPU util = %v (known=%v), want 43", u.GPUUtilPercent, u.GPUUtilKnown)
	}
	if want := int64(14382) << 20; !u.GPUMemKnown || u.GPUMemBytes != want {
		t.Errorf("GPU mem = %d (known=%v), want %d", u.GPUMemBytes, u.GPUMemKnown, want)
	}
}

func TestParseSacctUsageExternStepExcluded(t *testing.T) {
	// The extern step's rows must not mark the job sampled or contribute
	// usage; a job whose only rows are extern reads as unsampled.
	raw := "77|10|2|00:00:00|cpu=2,mem=1G,node=1|||||\n" +
		"77.extern|10|2|00:00:00|cpu=2,mem=1G,node=1|999999K|energy=0|energy=0|energy=0|energy=0\n"
	u := ParseSacctUsage("77", raw)
	if u.Sampled {
		t.Error("Sampled = true from extern-only rows")
	}
	if u.MaxRSSBytes != 0 {
		t.Errorf("MaxRSSBytes = %d from extern step, want 0", u.MaxRSSBytes)
	}
}

func TestParseSacctUsageDropsForeignArrayRows(t *testing.T) {
	// Querying an array base id lists every task; blending tasks would
	// produce a meaningless aggregate, so such rows are dropped.
	raw := "123_0|10|2|00:05:00|cpu=2,mem=1G,node=1|||||\n" +
		"123_0.batch|10|2|00:05:00|cpu=2,mem=1G,node=1|100K|cpu=00:05:00,fs/disk=5|cpu=00:05:00|cpu=00:05:00|fs/disk=6\n"
	u := ParseSacctUsage("123", raw)
	if u.Sampled || u.CPUTimeSec != 0 || u.MaxRSSBytes != 0 {
		t.Errorf("array task rows leaked into aggregate: %+v", u)
	}
}

func TestParseSstatUsageLiveJob(t *testing.T) {
	u := ParseSstatUsage("5834914", loadFixture(t, "sstat_usage.txt"))

	if u.Source != "sstat" {
		t.Errorf("Source = %q, want sstat", u.Source)
	}
	if !u.Sampled {
		t.Error("Sampled = false, want true")
	}
	// CPU time comes from TRESUsageInTot cpu=00:01:11; the extern step's
	// garbage RSS must be excluded.
	if u.CPUTimeSec != 71 {
		t.Errorf("CPUTimeSec = %v, want 71", u.CPUTimeSec)
	}
	if want := int64(2502) * 1024; u.MaxRSSBytes != want {
		t.Errorf("MaxRSSBytes = %d, want %d", u.MaxRSSBytes, want)
	}
	if u.DiskReadBytes != 16176988793 {
		t.Errorf("DiskReadBytes = %d, want 16176988793", u.DiskReadBytes)
	}
	if u.DiskWriteBytes != 1572864182 {
		t.Errorf("DiskWriteBytes = %d, want 1572864182", u.DiskWriteBytes)
	}
	// The sstat path cannot know the allocation.
	if u.ElapsedSec != 0 || u.AllocCPUs != 0 || len(u.GPUs) != 0 {
		t.Errorf("sstat path invented allocation data: %+v", u)
	}
}

func TestParseUsageEmptyOutput(t *testing.T) {
	for _, u := range []JobUsage{
		ParseSacctUsage("1", ""),
		ParseSstatUsage("1", ""),
	} {
		if u.Sampled {
			t.Errorf("%s: Sampled = true for empty output", u.Source)
		}
	}
}

func TestParseSizeBytes(t *testing.T) {
	cases := []struct {
		in   string
		want int64
	}{
		{"", 0},
		{"0", 0},
		{"garbage", 0},
		{"-5K", 0},
		{"1234", 1234},
		{"2502K", 2502 * 1024},
		{"12050M", 12050 << 20},
		{"20112.84M", 21089841315},
		{"1.5G", int64(1.5 * (1 << 30))},
		{"2T", 2 << 40},
	}
	for _, c := range cases {
		if got := parseSizeBytes(c.in); got != c.want {
			t.Errorf("parseSizeBytes(%q) = %d, want %d", c.in, got, c.want)
		}
	}
}

func TestClientJobUsageCommands(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{
		"sacct": loadFixture(t, "sacct_usage_cpu.txt"),
		"sstat": loadFixture(t, "sstat_usage.txt"),
	}}
	c := NewClient(r, WithUsername("alice"))

	if _, err := c.JobUsage(context.Background(), "5834914", false); err != nil {
		t.Fatal(err)
	}
	call := lastCall(r)
	if call.Name != "sacct" || !argsContain(call, "--allusers") || !argsContain(call, "-j") || !argsContain(call, "5834914") || !argsContain(call, sacctUsageFormat) {
		t.Errorf("finished-job usage argv: %s %v", call.Name, call.Args)
	}

	if _, err := c.JobUsage(context.Background(), "5834914", true); err != nil {
		t.Fatal(err)
	}
	call = lastCall(r)
	if call.Name != "sstat" || !argsContain(call, "-a") || !argsContain(call, sstatUsageFormat) {
		t.Errorf("running-job usage argv: %s %v", call.Name, call.Args)
	}

	if _, err := c.JobUsage(context.Background(), "rm -rf", false); err == nil ||
		!strings.Contains(err.Error(), "job") {
		t.Errorf("unsafe job id not rejected: %v", err)
	}
}
