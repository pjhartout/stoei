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
	// A draining GPU node's capacity is recorded as unavailable — kept out of the
	// schedulable totals but part of the per-type denominators; MIG profiles are
	// bucketed by type. Mirrors the real IDLE+DRAIN MIG node hpcl9101.
	nodes := []slurm.Node{
		{State: "IDLE+DRAIN", CPUTot: "152",
			CfgTRES: "cpu=152,mem=1000000M,gres/gpu=22,gres/gpu:h100_pcie_1g.10gb=16,gres/gpu:h100_pcie_2g.20gb=6",
			Gres:    "gpu:h100_pcie_2g.20gb:6,gpu:h100_pcie_1g.10gb:16"},
	}
	s := DeriveClusterStats(nodes, nil)
	if s.TotalGPUs != 0 || s.AllocatedGPUs != 0 {
		t.Errorf("draining node leaked into schedulable totals: total %d alloc %d",
			s.TotalGPUs, s.AllocatedGPUs)
	}
	if s.DrainingNodes != 1 {
		t.Errorf("DrainingNodes = %d; want 1", s.DrainingNodes)
	}
	if got := s.GPUsByType["H100_PCIE_1G.10GB"]; got != (GPUTotalAlloc{Unavail: 16}) {
		t.Errorf("1g.10gb = %+v; want {Unavail:16}", got)
	}
	if got := s.GPUsByType["H100_PCIE_2G.20GB"]; got != (GPUTotalAlloc{Unavail: 6}) {
		t.Errorf("2g.20gb = %+v; want {Unavail:6}", got)
	}
	if s.UnavailGPUs != 22 {
		t.Errorf("UnavailGPUs = %d; want 22", s.UnavailGPUs)
	}
}

// TestDeriveClusterStatsExcludesOfflineNodes asserts that offline nodes are kept
// out of the totals (the denominators): only online nodes count. A DOWN node
// without a DRAIN flag would otherwise inflate every total, and a
// DOWN+DRAIN+NOT_RESPONDING node (the real hpcl94 shape) is offline, not draining.
func TestDeriveClusterStatsExcludesOfflineNodes(t *testing.T) {
	nodes := []slurm.Node{
		{State: "IDLE", CPUTot: "10", CPUAlloc: "0", RealMem: "2048", AllocMem: "0", CfgTRES: "cpu=10,gres/gpu:h200=4"},
		{State: "DOWN", CPUTot: "20", CPUAlloc: "0", RealMem: "4096", AllocMem: "0", CfgTRES: "cpu=20,gres/gpu:a100=8"},
		{State: "DOWN+DRAIN+NOT_RESPONDING", CPUTot: "40", CPUAlloc: "0", RealMem: "8192", AllocMem: "0", CfgTRES: "cpu=40,gres/gpu:h100=2"},
	}
	s := DeriveClusterStats(nodes, nil)

	if s.OfflineNodes != 2 {
		t.Errorf("OfflineNodes = %d; want 2", s.OfflineNodes)
	}
	if s.TotalNodes != 1 || s.FreeNodes != 1 {
		t.Errorf("nodes = total %d free %d; want total 1 free 1 (offline excluded)", s.TotalNodes, s.FreeNodes)
	}
	if s.DrainingNodes != 0 {
		t.Errorf("DrainingNodes = %d; want 0 (a down+drain node is offline, not draining)", s.DrainingNodes)
	}
	if s.TotalCPUs != 10 || s.TotalMemoryGB != 2.0 || s.TotalGPUs != 4 {
		t.Errorf("totals = cpu %d mem %v gpu %d; want 10 2.0 4 (online node only)",
			s.TotalCPUs, s.TotalMemoryGB, s.TotalGPUs)
	}
	// Offline-node GPUs stay out of the schedulable totals but are recorded as
	// unavailable so the per-type denominators reflect the hardware fleet.
	if got := s.GPUsByType["A100"]; got != (GPUTotalAlloc{Unavail: 8}) {
		t.Errorf("A100 = %+v; want {Unavail:8}", got)
	}
	if got := s.GPUsByType["H100"]; got != (GPUTotalAlloc{Unavail: 2}) {
		t.Errorf("H100 = %+v; want {Unavail:2}", got)
	}
	if s.UnavailGPUs != 10 {
		t.Errorf("UnavailGPUs = %d; want 10", s.UnavailGPUs)
	}
	if got := s.GPUTypeFreePct("H200"); got != 100.0 {
		t.Errorf("H200 free pct = %v; want 100 (4/4 free, none unavailable)", got)
	}
	if got := s.GPUTypeFreePct("A100"); got != 0.0 {
		t.Errorf("A100 free pct = %v; want 0 (all 8 unavailable)", got)
	}
}

func TestAggregateUserStats(t *testing.T) {
	jobs := []slurm.AllUsersJob{
		{ID: "100", User: "alice", Partition: "gpu", State: "RUNNING", NumNodes: "1", NodeList: "node01", TRES: "cpu=8,mem=16G,gres/gpu:h200=2"},
		{ID: "101_3", User: "alice", Partition: "gpu", State: "RUNNING", NumNodes: "1", NodeList: "node02", TRES: "cpu=4"},
		{ID: "102_5", User: "alice", Partition: "gpu", State: "RUNNING", NumNodes: "1", NodeList: "node02", TRES: "cpu=4"},
		{ID: "200", User: "bob", Partition: "cpu", State: "RUNNING", NumNodes: "2", NodeList: "node[03-04]", TRES: "cpu=16"},
	}
	got := AggregateUserStats(jobs, nil)
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

func TestAggregateUserStatsResolvesGenericGPUs(t *testing.T) {
	nodes := []slurm.Node{
		{Name: "gpu01", Gres: "gpu:h100:4"},
		{Name: "gpu02", Gres: "gpu:h100:4"},
		{Name: "gpu03", Gres: "gpu:l40s:4"},
	}
	models := NodeGPUModels(nodes)

	jobs := []slurm.AllUsersJob{
		// Generic request on single-model nodes: attributed to H100.
		{ID: "1", User: "a", State: "RUNNING", NumNodes: "2", NodeList: "gpu[01-02]", TRES: "cpu=8,gres/gpu=8"},
		// Generic request across mixed models: stays in the generic bucket.
		{ID: "2", User: "a", State: "RUNNING", NumNodes: "2", NodeList: "gpu[02-03]", TRES: "cpu=8,gres/gpu=2"},
		// Typed request listing the generic duplicate: not a generic request.
		{ID: "3", User: "a", State: "RUNNING", NumNodes: "1", NodeList: "gpu03", TRES: "cpu=4,gres/gpu=1,gres/gpu:l40s=1"},
	}
	got := AggregateUserStats(jobs, models)
	if len(got) != 1 {
		t.Fatalf("users = %d; want 1", len(got))
	}
	a := got[0]
	if a.GenericGPUJobs != 2 {
		t.Errorf("GenericGPUJobs = %d; want 2", a.GenericGPUJobs)
	}
	if a.TotalGPUs != 11 {
		t.Errorf("TotalGPUs = %d; want 11", a.TotalGPUs)
	}
	if a.GPUTypes != "8x H100, 1x L40S, 2x gpu" && a.GPUTypes != "2x GPU, 8x H100, 1x L40S" {
		t.Errorf("GPUTypes = %q; want H100 resolved, L40S typed, 2 generic", a.GPUTypes)
	}
}

func TestFindUserStats(t *testing.T) {
	users := []UserStats{{Username: "alice", TotalCPUs: 16}}
	if got, ok := FindUserStats(users, "alice"); !ok || got.TotalCPUs != 16 {
		t.Errorf("FindUserStats(alice) = %+v ok=%v", got, ok)
	}
	if _, ok := FindUserStats(users, "nobody"); ok {
		t.Errorf("FindUserStats(nobody) should be ok=false")
	}
}
