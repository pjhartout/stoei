package store

import (
	"testing"

	"github.com/pjhartout/stoei/internal/slurm"
)

func TestDeriveClusterStats(t *testing.T) {
	nodes := []slurm.Node{
		{State: "IDLE", CPUTot: "10", CPUAlloc: "0", RealMem: "2048", AllocMem: "0", CfgTRES: "cpu=10,mem=2048M,gres/gpu:h200=4"},
		{State: "MIXED", CPUTot: "20", CPUAlloc: "8", RealMem: "4096", AllocMem: "1024", CfgTRES: "cpu=20,gres/gpu:a100=8", AllocTRES: "gres/gpu:a100=3"},
		{State: "DRAINING", CPUTot: "5", CPUAlloc: "2", RealMem: "1024", AllocMem: "512", CfgTRES: "cpu=5,gres/gpu:h200=2"},
	}
	allUsers := []slurm.AllUsersJob{
		{ID: "1001", User: "alice", Partition: "gpu", State: "PENDING", TRES: "cpu=4,mem=8G,gres/gpu:h200=2"},
		{ID: "1002_[0-3]", User: "bob", Partition: "cpu", State: "PD", TRES: "cpu=2,mem=4G"},
		{ID: "1003", User: "carol", Partition: "gpu", State: "RUNNING", NodeList: "node01", TRES: "cpu=8"},
	}
	s := DeriveClusterStats(nodes, allUsers)

	// Node counts: draining excluded from totals.
	if s.TotalNodes != 2 || s.FreeNodes != 1 || s.AllocatedNodes != 1 || s.DrainingNodes != 1 {
		t.Errorf("node counts = total %d free %d alloc %d drain %d; want 2 1 1 1",
			s.TotalNodes, s.FreeNodes, s.AllocatedNodes, s.DrainingNodes)
	}
	// CPUs: totals exclude draining (10+20=30); alloc includes draining (0+8+2=10).
	if s.TotalCPUs != 30 || s.AllocatedCPUs != 10 {
		t.Errorf("cpus = total %d alloc %d; want 30 10", s.TotalCPUs, s.AllocatedCPUs)
	}
	// Memory in GB: totals 2048/1024 + 4096/1024 = 6.0; alloc 0 + 1 + 0.5 = 1.5.
	if s.TotalMemoryGB != 6.0 || s.AllocatedMemoryGB != 1.5 {
		t.Errorf("mem = total %v alloc %v; want 6.0 1.5", s.TotalMemoryGB, s.AllocatedMemoryGB)
	}
	// GPUs: total 4 (h200) + 8 (a100) = 12; alloc 3 (a100). Draining excluded.
	if s.TotalGPUs != 12 || s.AllocatedGPUs != 3 {
		t.Errorf("gpus = total %d alloc %d; want 12 3", s.TotalGPUs, s.AllocatedGPUs)
	}
	if got := s.GPUsByType["H200"]; got.Total != 4 || got.Allocated != 0 {
		t.Errorf("H200 = %+v; want {4 0}", got)
	}
	if got := s.GPUsByType["A100"]; got.Total != 8 || got.Allocated != 3 {
		t.Errorf("A100 = %+v; want {8 3}", got)
	}

	// Pending: array 1002_[0-3] expands to 4; plus 1 plain = 5 jobs.
	if s.PendingJobsCount != 5 || s.PendingCPUs != 12 || s.PendingMemoryGB != 24.0 || s.PendingGPUs != 2 {
		t.Errorf("pending = jobs %d cpu %d mem %v gpu %d; want 5 12 24.0 2",
			s.PendingJobsCount, s.PendingCPUs, s.PendingMemoryGB, s.PendingGPUs)
	}
	if got := s.PendingGPUsByType["H200"]; got != 2 {
		t.Errorf("pending H200 = %d; want 2", got)
	}
	gpuPart := s.PendingByPartition["gpu"]
	if gpuPart.JobsCount != 1 || gpuPart.CPUs != 4 || gpuPart.MemoryGB != 8.0 || gpuPart.GPUs != 2 || gpuPart.GPUsByType["H200"] != 2 {
		t.Errorf("gpu partition = %+v; want jobs 1 cpu 4 mem 8 gpu 2 h200 2", gpuPart)
	}
	cpuPart := s.PendingByPartition["cpu"]
	if cpuPart.JobsCount != 4 || cpuPart.CPUs != 8 || cpuPart.MemoryGB != 16.0 || cpuPart.GPUs != 0 {
		t.Errorf("cpu partition = %+v; want jobs 4 cpu 8 mem 16 gpu 0", cpuPart)
	}
}

func TestDeriveClusterStatsNoNodes(t *testing.T) {
	// With no nodes, pending resources are still computed.
	allUsers := []slurm.AllUsersJob{
		{ID: "9_[0-9]", User: "x", Partition: "p", State: "PENDING", TRES: "cpu=1,mem=1G"},
	}
	s := DeriveClusterStats(nil, allUsers)
	if s.TotalNodes != 0 {
		t.Errorf("total nodes = %d; want 0", s.TotalNodes)
	}
	if s.PendingJobsCount != 10 || s.PendingCPUs != 10 {
		t.Errorf("pending = jobs %d cpu %d; want 10 10", s.PendingJobsCount, s.PendingCPUs)
	}
}

func TestDeriveClusterStatsGresFallback(t *testing.T) {
	// No TRES -> fall back to Gres; MIXED state estimates full allocation.
	nodes := []slurm.Node{
		{State: "MIXED", CPUTot: "8", CPUAlloc: "8", RealMem: "1024", AllocMem: "1024", Gres: "gpu:a100:4"},
	}
	s := DeriveClusterStats(nodes, nil)
	if s.TotalGPUs != 4 || s.AllocatedGPUs != 4 {
		t.Errorf("gres fallback gpus = total %d alloc %d; want 4 4", s.TotalGPUs, s.AllocatedGPUs)
	}
	if got := s.GPUsByType["A100"]; got.Total != 4 || got.Allocated != 4 {
		t.Errorf("A100 = %+v; want {4 4}", got)
	}
}

func TestDeriveClusterStatsNamesGenericTRESFromGres(t *testing.T) {
	// Real-world config: CfgTRES/AllocTRES report GPUs generically ("gres/gpu=4")
	// while the model lives only in the Gres field ("gpu:l40s:4"). The model must
	// be lifted from Gres so the overview shows L40S rather than a generic bucket.
	nodes := []slurm.Node{
		{State: "MIXED", CPUTot: "256", CPUAlloc: "32", RealMem: "760000", AllocMem: "192000",
			Gres: "gpu:l40s:4(S:0)", CfgTRES: "cpu=256,mem=760000M,gres/gpu=4", AllocTRES: "cpu=32,mem=192G,gres/gpu=4"},
	}
	s := DeriveClusterStats(nodes, nil)
	if got := s.GPUsByType["L40S"]; got.Total != 4 || got.Allocated != 4 {
		t.Errorf("L40S = %+v; want {4 4}", got)
	}
	if _, ok := s.GPUsByType["GPU"]; ok {
		t.Errorf("generic bucket present; want it folded into L40S: %v", s.GPUsByType)
	}
}

func TestDeriveClusterStatsParsesAllocTRESEndToEnd(t *testing.T) {
	// Regression: a MIXED GPU node must report its real partial allocation rather
	// than being rounded up to fully allocated. This drives the full production
	// path (raw scontrol text -> ParseNodes -> DeriveClusterStats); the parser has
	// to capture CfgTRES/AllocTRES even though their values embed "=", otherwise
	// the store falls back to a state heuristic that counts every MIXED/ALLOCATED
	// node's GPUs as wholly in use.
	raw := "NodeName=hpcl9104 State=MIXED CPUTot=64 CPUAlloc=48 RealMemory=512000 AllocMem=384000\n" +
		"   Gres=gpu:h100:4\n" +
		"   CfgTRES=cpu=64,mem=512000M,billing=64,gres/gpu=4,gres/gpu:h100=4\n" +
		"   AllocTRES=cpu=48,mem=384000M,gres/gpu=3,gres/gpu:h100=3\n"
	s := DeriveClusterStats(slurm.ParseNodes(raw), nil)
	if got := s.GPUsByType["H100"]; got.Total != 4 || got.Allocated != 3 {
		t.Errorf("H100 = %+v; want {4 3} (1 GPU still free on a MIXED node)", got)
	}
	if s.TotalGPUs != 4 || s.AllocatedGPUs != 3 {
		t.Errorf("gpus = total %d alloc %d; want 4 3", s.TotalGPUs, s.AllocatedGPUs)
	}
}

func TestDeriveClusterStatsDrainingGPUs(t *testing.T) {
	// A draining GPU node's capacity is reported separately (DrainingGPUsByType) and
	// kept out of the schedulable totals; MIG profiles are bucketed by type. Mirrors
	// the real IDLE+DRAIN MIG node hpcl9101.
	nodes := []slurm.Node{
		{State: "IDLE+DRAIN", CPUTot: "152",
			CfgTRES: "cpu=152,mem=1000000M,gres/gpu=22,gres/gpu:h100_pcie_1g.10gb=16,gres/gpu:h100_pcie_2g.20gb=6",
			Gres:    "gpu:h100_pcie_2g.20gb:6,gpu:h100_pcie_1g.10gb:16"},
	}
	s := DeriveClusterStats(nodes, nil)
	if s.TotalGPUs != 0 || s.AllocatedGPUs != 0 || len(s.GPUsByType) != 0 {
		t.Errorf("draining node leaked into schedulable totals: total %d alloc %d byType %v",
			s.TotalGPUs, s.AllocatedGPUs, s.GPUsByType)
	}
	if s.DrainingNodes != 1 {
		t.Errorf("DrainingNodes = %d; want 1", s.DrainingNodes)
	}
	if s.DrainingGPUsByType["H100_PCIE_1G.10GB"] != 16 || s.DrainingGPUsByType["H100_PCIE_2G.20GB"] != 6 {
		t.Errorf("DrainingGPUsByType = %v; want H100_PCIE_1G.10GB:16 H100_PCIE_2G.20GB:6", s.DrainingGPUsByType)
	}
}

func TestAggregateUserStats(t *testing.T) {
	jobs := []slurm.AllUsersJob{
		{ID: "100", User: "alice", Partition: "gpu", State: "RUNNING", NumNodes: "1", NodeList: "node01", TRES: "cpu=8,mem=16G,gres/gpu:h200=2"},
		{ID: "101_3", User: "alice", Partition: "gpu", State: "RUNNING", NumNodes: "1", NodeList: "node02", TRES: "cpu=4"},
		{ID: "102_5", User: "alice", Partition: "gpu", State: "RUNNING", NumNodes: "1", NodeList: "node02", TRES: "cpu=4"},
		{ID: "200", User: "bob", Partition: "cpu", State: "RUNNING", NumNodes: "2", NodeList: "node[03-04]", TRES: "cpu=16"},
	}
	got := AggregateUserStats(jobs)
	byUser := map[string]UserStats{}
	for _, u := range got {
		byUser[u.Username] = u
	}

	alice := byUser["alice"]
	if alice.JobCount != 3 || alice.TotalCPUs != 16 || alice.TotalMemoryGB != 16.0 || alice.TotalGPUs != 2 ||
		alice.TotalNodes != 2 || alice.GPUTypes != "2x H200" || alice.NodeNames != "node01,node02" ||
		alice.ArrayCount != 2 || alice.PlainJobCount != 1 {
		t.Errorf("alice = %+v", alice)
	}

	bob := byUser["bob"]
	if bob.JobCount != 1 || bob.TotalCPUs != 16 || bob.TotalGPUs != 0 || bob.TotalNodes != 2 ||
		bob.GPUTypes != "" || bob.NodeNames != "node03,node04" || bob.ArrayCount != 0 || bob.PlainJobCount != 1 {
		t.Errorf("bob = %+v", bob)
	}
}

func TestMyUsageSummary(t *testing.T) {
	users := []UserStats{
		{Username: "alice", JobCount: 3, TotalCPUs: 16, TotalMemoryGB: 16.0, TotalGPUs: 2, TotalNodes: 2, GPUTypes: "2x H200", ArrayCount: 2, PlainJobCount: 1},
	}
	got := MyUsageSummary(users, "alice")
	want := "My Usage: 16 CPUs | 16.0 GB RAM | 2 GPUs (2x H200) | 2 Nodes | 3 tasks (2 arrays, 1 job)"
	if got != want {
		t.Errorf("MyUsageSummary =\n %q\nwant\n %q", got, want)
	}

	if got := MyUsageSummary(users, "nobody"); got != "My Usage: No running jobs" {
		t.Errorf("missing user = %q; want %q", got, "My Usage: No running jobs")
	}
}

func TestMyUsageSummaryNoGPUSingularForms(t *testing.T) {
	users := []UserStats{
		{Username: "u", JobCount: 1, TotalCPUs: 1, TotalMemoryGB: 0.5, TotalGPUs: 0, TotalNodes: 1, ArrayCount: 1, PlainJobCount: 1},
	}
	got := MyUsageSummary(users, "u")
	want := "My Usage: 1 CPUs | 0.5 GB RAM | 1 Nodes | 1 task (1 array, 1 job)"
	if got != want {
		t.Errorf("singular forms = %q; want %q", got, want)
	}
}
