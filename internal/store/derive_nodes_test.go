package store

import (
	"testing"

	"github.com/pjhartout/stoei/internal/slurm"
)

func TestDeriveNodeDisplaysCPUMemGPU(t *testing.T) {
	nodes := []slurm.Node{
		{
			Name:      "gpu01",
			State:     "MIXED",
			CPUTot:    "64",
			CPUAlloc:  "16",
			RealMem:   "262144", // 256 GB
			AllocMem:  "131072", // 128 GB
			CfgTRES:   "cpu=64,mem=256G,gres/gpu:h200=8",
			AllocTRES: "cpu=16,gres/gpu:h200=2",
			Fields:    map[string]string{"Partitions": "gpu", "NodeName": "gpu01"},
		},
	}
	got := DeriveNodeDisplays(nodes)
	if len(got) != 1 {
		t.Fatalf("got %d displays; want 1", len(got))
	}
	d := got[0]

	if d.CPUsAlloc != 16 || d.CPUsTotal != 64 {
		t.Errorf("CPUs = %d/%d; want 16/64", d.CPUsAlloc, d.CPUsTotal)
	}
	if got := d.CPUUsagePct(); got != 25.0 {
		t.Errorf("CPU%% = %.1f; want 25.0", got)
	}
	if d.MemoryTotalGB != 256.0 || d.MemoryAllocGB != 128.0 {
		t.Errorf("Mem = %.1f/%.1f; want 128/256", d.MemoryAllocGB, d.MemoryTotalGB)
	}
	if got := d.MemoryUsagePct(); got != 50.0 {
		t.Errorf("Mem%% = %.1f; want 50.0", got)
	}
	if d.GPUsTotal != 8 || d.GPUsAlloc != 2 {
		t.Errorf("GPUs = %d/%d; want 2/8", d.GPUsAlloc, d.GPUsTotal)
	}
	if got := d.GPUUsagePct(); got != 25.0 {
		t.Errorf("GPU%% = %.1f; want 25.0", got)
	}
	if d.GPUTypes != "8x H200" {
		t.Errorf("GPUTypes = %q; want %q", d.GPUTypes, "8x H200")
	}
	if d.Partitions != "gpu" {
		t.Errorf("Partitions = %q; want gpu", d.Partitions)
	}
}

func TestDeriveNodeDisplaysStateBasedGPUAlloc(t *testing.T) {
	// No AllocTRES: an ALLOCATED node with GPUs is assumed fully allocated.
	nodes := []slurm.Node{
		{
			Name:    "gpu02",
			State:   "ALLOCATED",
			CfgTRES: "gres/gpu:a100=4",
			Fields:  map[string]string{"NodeName": "gpu02"},
		},
	}
	d := DeriveNodeDisplays(nodes)[0]
	if d.GPUsTotal != 4 || d.GPUsAlloc != 4 {
		t.Errorf("state-based GPU alloc = %d/%d; want 4/4", d.GPUsAlloc, d.GPUsTotal)
	}
}

func TestDeriveNodeDisplaysSkipsEmptyName(t *testing.T) {
	nodes := []slurm.Node{
		{Name: "", State: "IDLE"},
		{Name: "n1", State: "IDLE", Fields: map[string]string{"NodeName": "n1"}},
	}
	got := DeriveNodeDisplays(nodes)
	if len(got) != 1 || got[0].Name != "n1" {
		t.Errorf("got %+v; want only n1", got)
	}
}

func TestDeriveNodeDisplaysGPULessNodeHasNoTypes(t *testing.T) {
	nodes := []slurm.Node{
		{Name: "cpu01", State: "IDLE", CPUTot: "32", Fields: map[string]string{"NodeName": "cpu01"}},
	}
	d := DeriveNodeDisplays(nodes)[0]
	if d.GPUsTotal != 0 || d.GPUTypes != "" {
		t.Errorf("GPU-less node: total=%d types=%q; want 0/empty", d.GPUsTotal, d.GPUTypes)
	}
	if got := d.GPUUsagePct(); got != 0 {
		t.Errorf("GPU%% = %.1f; want 0", got)
	}
}

func TestJobsOnNodeMatchesExpandedNodeListAndParsesResources(t *testing.T) {
	jobs := []AllUsersJob{
		{ID: "10", Name: "a", User: "carol", Time: "2:00", NodeList: "gpu[01-02]", TRES: "cpu=16,mem=32G,gres/gpu:a100=4"},
		{ID: "9", Name: "b", User: "alice", Time: "1:00", NodeList: "gpu01", TRES: "cpu=8"},
		{ID: "11", Name: "c", User: "dave", Time: "3:00", NodeList: "cpu07", TRES: "cpu=4"},
	}
	got := JobsOnNode(jobs, "gpu01")
	if len(got) != 2 {
		t.Fatalf("got %d jobs on gpu01; want 2 (%+v)", len(got), got)
	}
	// Sorted by user then id: alice(9) before carol(10).
	if got[0].User != "alice" || got[1].User != "carol" {
		t.Errorf("order = %q,%q; want alice,carol", got[0].User, got[1].User)
	}
	if got[1].CPUs != 16 || got[1].GPUs != 4 {
		t.Errorf("carol resources = %d cpu / %d gpu; want 16/4", got[1].CPUs, got[1].GPUs)
	}
}

func TestJobsOnNodeEmptyForUnoccupiedNode(t *testing.T) {
	jobs := []AllUsersJob{{ID: "1", User: "x", NodeList: "gpu01", TRES: "cpu=1"}}
	if got := JobsOnNode(jobs, "gpu99"); len(got) != 0 {
		t.Errorf("got %d; want 0 for unoccupied node", len(got))
	}
	if got := JobsOnNode(jobs, ""); len(got) != 0 {
		t.Errorf("empty node name should match nothing, got %d", len(got))
	}
}
