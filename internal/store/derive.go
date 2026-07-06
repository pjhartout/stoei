package store

import (
	"sort"
	"strconv"
	"strings"

	"github.com/pjhartout/stoei/internal/slurm"
)

// PendingPartitionStats holds aggregated pending resources for one partition.
type PendingPartitionStats struct {
	JobsCount  int
	CPUs       int
	MemoryGB   float64
	GPUs       int
	GPUsByType map[string]int
}

// GPUTotalAlloc is the per-type GPU accounting stored in ClusterStats. Total and
// Allocated cover schedulable (online, non-draining) nodes; Unavail counts cards
// on draining or offline nodes — part of the hardware denominator but never free.
type GPUTotalAlloc struct {
	Total     int
	Allocated int
	Unavail   int
}

// ClusterStats is the derived cluster-wide resource summary. The percentage
// helper methods compute free-resource ratios from its totals.
type ClusterStats struct {
	TotalNodes        int
	FreeNodes         int
	AllocatedNodes    int
	TotalCPUs         int
	AllocatedCPUs     int
	TotalMemoryGB     float64
	AllocatedMemoryGB float64
	TotalGPUs         int
	AllocatedGPUs     int
	// UnavailGPUs counts GPUs on draining or offline nodes across all types. They
	// are excluded from TotalGPUs (not schedulable) but included in display
	// denominators so the hardware fleet size stays visible.
	UnavailGPUs   int
	GPUsByType    map[string]GPUTotalAlloc
	DrainingNodes int
	// OfflineNodes counts nodes that are unavailable for scheduling — down,
	// unreachable, in maintenance, or powered off. Their capacity is excluded from
	// every total so the denominators (free/total ratios) reflect online nodes only.
	OfflineNodes int

	PendingJobsCount   int
	PendingCPUs        int
	PendingMemoryGB    float64
	PendingGPUs        int
	PendingGPUsByType  map[string]int
	PendingByPartition map[string]PendingPartitionStats
}

// FreeNodesPct returns the percentage of free nodes.
func (s ClusterStats) FreeNodesPct() float64 {
	if s.TotalNodes == 0 {
		return 0
	}
	return float64(s.FreeNodes) / float64(s.TotalNodes) * 100.0
}

// FreeCPUsPct returns the percentage of free CPUs.
func (s ClusterStats) FreeCPUsPct() float64 {
	if s.TotalCPUs == 0 {
		return 0
	}
	return float64(s.TotalCPUs-s.AllocatedCPUs) / float64(s.TotalCPUs) * 100.0
}

// FreeMemoryPct returns the percentage of free memory.
func (s ClusterStats) FreeMemoryPct() float64 {
	if s.TotalMemoryGB == 0 {
		return 0
	}
	return (s.TotalMemoryGB - s.AllocatedMemoryGB) / s.TotalMemoryGB * 100.0
}

// FreeGPUsPct returns the percentage of free GPUs. The denominator includes
// unavailable (draining/offline) cards, so drained hardware reads as load, not as
// a shrinking fleet.
func (s ClusterStats) FreeGPUsPct() float64 {
	denom := s.TotalGPUs + s.UnavailGPUs
	if denom == 0 {
		return 0
	}
	return float64(s.TotalGPUs-s.AllocatedGPUs) / float64(denom) * 100.0
}

// GPUTypeFreePct returns the percentage of free GPUs for a specific type, over
// the full hardware denominator (schedulable plus unavailable cards).
func (s ClusterStats) GPUTypeFreePct(gpuType string) float64 {
	ta, ok := s.GPUsByType[gpuType]
	denom := ta.Total + ta.Unavail
	if !ok || denom == 0 {
		return 0
	}
	return float64(ta.Total-ta.Allocated) / float64(denom) * 100.0
}

// newClusterStats returns a ClusterStats with all maps initialised.
func newClusterStats() ClusterStats {
	return ClusterStats{
		GPUsByType:         map[string]GPUTotalAlloc{},
		PendingGPUsByType:  map[string]int{},
		PendingByPartition: map[string]PendingPartitionStats{},
	}
}

// DeriveClusterStats computes cluster statistics from nodes and all-users jobs
// (for pending resources). It handles draining nodes, GPU accounting from
// CfgTRES/AllocTRES with a Gres fallback, and array-expanded pending aggregation.
func DeriveClusterStats(nodes []slurm.Node, allUsersJobs []slurm.AllUsersJob) ClusterStats {
	stats := newClusterStats()

	if len(nodes) == 0 {
		aggregatePending(allUsersJobs, &stats)
		return stats
	}

	for _, node := range nodes {
		state := strings.ToUpper(node.State)
		if nodeOffline(state) {
			// Offline nodes offer no schedulable capacity, so they are excluded from
			// every total — but their GPUs are recorded as unavailable so the card
			// denominators keep reflecting the hardware fleet.
			stats.OfflineNodes++
			addUnavailGPUs(node, nodeGPUModel(node), &stats)
			continue
		}
		isDraining := parseNodeState(state, &stats)
		parseNodeCPUs(node, &stats, !isDraining)
		parseNodeMemory(node, &stats, !isDraining)

		model := nodeGPUModel(node)

		if isDraining {
			addUnavailGPUs(node, model, &stats)
			continue
		}

		processGPUEntries(relabelGeneric(slurm.ParseGPUEntries(node.CfgTRES), model), &stats, false)
		processGPUEntries(relabelGeneric(slurm.ParseGPUEntries(node.AllocTRES), model), &stats, true)
		if node.CfgTRES == "" && node.AllocTRES == "" {
			parseGPUsFromGres(node, model, state, &stats)
		}
	}

	aggregatePending(allUsersJobs, &stats)

	return stats
}

// nodeOffline reports whether an (already upper-cased) node state is offline —
// unavailable for scheduling because the node is down, not responding, in
// maintenance, powered off, a future placeholder, or invalidly registered. Its
// capacity is excluded from the cluster totals so the denominators count online
// nodes only. A merely draining node is not offline: it still runs its existing
// jobs and is accounted separately. The trailing "*" is Slurm's not-responding
// marker.
func nodeOffline(state string) bool {
	for _, marker := range []string{"DOWN", "NOT_RESPONDING", "MAINT", "POWER", "FUTURE", "INVAL", "UNKNOWN"} {
		if strings.Contains(state, marker) {
			return true
		}
	}
	return strings.Contains(state, "*")
}

// parseNodeState updates node counts and returns whether the node is draining
// (and therefore excluded from totals).
func parseNodeState(state string, stats *ClusterStats) bool {
	if strings.Contains(state, "DRAIN") {
		stats.DrainingNodes++
		if strings.Contains(state, "ALLOCATED") || strings.Contains(state, "MIXED") {
			stats.AllocatedNodes++
		}
		return true
	}
	stats.TotalNodes++
	switch {
	case strings.Contains(state, "IDLE"):
		stats.FreeNodes++
	case strings.Contains(state, "ALLOCATED") || strings.Contains(state, "MIXED"):
		stats.AllocatedNodes++
	}
	return false
}

// parseNodeCPUs adds the node's CPU totals/allocation.
func parseNodeCPUs(node slurm.Node, stats *ClusterStats, includeTotal bool) {
	total, errT := strconv.Atoi(strings.TrimSpace(emptyToZero(node.CPUTot)))
	alloc, errA := strconv.Atoi(strings.TrimSpace(emptyToZero(node.CPUAlloc)))
	if errT != nil || errA != nil {
		return
	}
	if includeTotal {
		stats.TotalCPUs += total
	}
	stats.AllocatedCPUs += alloc
}

// parseNodeMemory adds the node's memory totals/allocation in GB.
func parseNodeMemory(node slurm.Node, stats *ClusterStats, includeTotal bool) {
	totalMB, errT := strconv.Atoi(strings.TrimSpace(emptyToZero(node.RealMem)))
	allocMB, errA := strconv.Atoi(strings.TrimSpace(emptyToZero(node.AllocMem)))
	if errT != nil || errA != nil {
		return
	}
	if includeTotal {
		stats.TotalMemoryGB += float64(totalMB) / memoryMBToGB
	}
	stats.AllocatedMemoryGB += float64(allocMB) / memoryMBToGB
}

// emptyToZero returns "0" for an empty/blank string so that integer parsing of
// a missing node field succeeds with a zero value.
func emptyToZero(s string) string {
	if strings.TrimSpace(s) == "" {
		return "0"
	}
	return s
}

// nodeGPUModel returns the GPU model named in a node's Gres field, used to name
// generic ("gpu") TRES entries that carry a count but no model — a common Slurm
// config where CfgTRES reports "gres/gpu=4" while Gres carries "gpu:l40s:4". It
// returns "" when the Gres names no model or more than one (nothing to infer).
func nodeGPUModel(node slurm.Node) string {
	model := ""
	for _, e := range slurm.ParseGPUFromGres(node.Gres) {
		if strings.EqualFold(e.Type, "gpu") {
			continue
		}
		if model != "" && model != e.Type {
			return ""
		}
		model = e.Type // ParseGPUFromGres upper-cases the type
	}
	return model
}

// relabelGeneric rewrites generic "gpu" entries to model. It is a no-op when model
// is empty or the list already carries a specific model (in which case the generic
// entry is a duplicate that AggregateGPUCounts drops, not one to relabel).
func relabelGeneric(entries []slurm.GPUEntry, model string) []slurm.GPUEntry {
	if model == "" || slurm.HasSpecificGPUTypes(entries) {
		return entries
	}
	out := make([]slurm.GPUEntry, len(entries))
	for i, e := range entries {
		if strings.EqualFold(e.Type, "gpu") {
			e.Type = model
		}
		out[i] = e
	}
	return out
}

// processGPUEntries folds GPU entries into the per-type totals/allocations.
// AggregateGPUCounts upper-cases the type key and drops generic "gpu" entries when
// specific models are present, so a model reported via TRES ("h200") and via the
// Gres fallback ("H200") share one bucket, matching the node-view convention.
func processGPUEntries(entries []slurm.GPUEntry, stats *ClusterStats, isAllocated bool) {
	for typ, count := range slurm.AggregateGPUCounts(entries, true) {
		ta := stats.GPUsByType[typ]
		if isAllocated {
			ta.Allocated += count
			stats.AllocatedGPUs += count
		} else {
			ta.Total += count
			stats.TotalGPUs += count
		}
		stats.GPUsByType[typ] = ta
	}
}

// parseGPUsFromGres is the fallback GPU accounting from the Gres field used when
// TRES data is absent (non-draining nodes only). It estimates allocation from node
// state (an ALLOCATED or MIXED node is treated as having all its GPUs in use).
func parseGPUsFromGres(node slurm.Node, model, state string, stats *ClusterStats) {
	allocated := strings.Contains(state, "ALLOCATED") || strings.Contains(state, "MIXED")
	entries := relabelGeneric(slurm.ParseGPUFromGres(node.Gres), model)
	for typ, count := range slurm.AggregateGPUCounts(entries, true) {
		ta := stats.GPUsByType[typ]
		ta.Total += count
		stats.TotalGPUs += count
		if allocated {
			ta.Allocated += count
			stats.AllocatedGPUs += count
		}
		stats.GPUsByType[typ] = ta
	}
}

// addUnavailGPUs records a draining or offline node's configured GPUs by type as
// unavailable: part of the hardware denominator but never free. All of the
// node's cards count as unavailable, including any still running jobs on a
// draining node — either way they cannot accept new work. GPU types come from
// CfgTRES, falling back to the Gres field.
func addUnavailGPUs(node slurm.Node, model string, stats *ClusterStats) {
	counts := slurm.AggregateGPUCounts(relabelGeneric(slurm.ParseGPUEntries(node.CfgTRES), model), true)
	if len(counts) == 0 {
		counts = slurm.AggregateGPUCounts(relabelGeneric(slurm.ParseGPUFromGres(node.Gres), model), true)
	}
	for typ, count := range counts {
		ta := stats.GPUsByType[typ]
		ta.Unavail += count
		stats.GPUsByType[typ] = ta
		stats.UnavailGPUs += count
	}
}

// aggregatePending computes pending-job resources, expanding array jobs so that a
// pending array's resources count once per task.
func aggregatePending(allUsersJobs []slurm.AllUsersJob, stats *ClusterStats) {
	pendingCPUs := 0
	pendingMemoryGB := 0.0
	pendingGPUs := 0
	pendingJobsCount := 0
	pendingGPUsByType := map[string]int{}
	pendingByPartition := map[string]PendingPartitionStats{}

	for _, job := range allUsersJobs {
		state := strings.ToUpper(strings.TrimSpace(job.State))
		if state != "PENDING" && state != "PD" {
			continue
		}

		jobID := strings.TrimSpace(job.ID)
		arraySize := slurm.ParseArraySize(jobID)
		pendingJobsCount += arraySize

		partitionKey := strings.TrimSpace(job.Partition)
		if partitionKey == "" {
			partitionKey = "unknown"
		}
		ps, ok := pendingByPartition[partitionKey]
		if !ok {
			ps = PendingPartitionStats{GPUsByType: map[string]int{}}
		}
		ps.JobsCount += arraySize

		if strings.TrimSpace(job.TRES) == "" {
			pendingByPartition[partitionKey] = ps
			continue
		}

		res := slurm.ParseTRESResources(job.TRES)
		pendingCPUs += res.CPUs * arraySize
		pendingMemoryGB += res.MemoryGB * float64(arraySize)
		ps.CPUs += res.CPUs * arraySize
		ps.MemoryGB += res.MemoryGB * float64(arraySize)

		for _, e := range res.GPUs {
			scaled := e.Count * arraySize
			typ := strings.ToUpper(e.Type)
			pendingGPUs += scaled
			ps.GPUs += scaled
			pendingGPUsByType[typ] += scaled
			ps.GPUsByType[typ] += scaled
		}

		pendingByPartition[partitionKey] = ps
	}

	stats.PendingJobsCount = pendingJobsCount
	stats.PendingCPUs = pendingCPUs
	stats.PendingMemoryGB = pendingMemoryGB
	stats.PendingGPUs = pendingGPUs
	stats.PendingGPUsByType = pendingGPUsByType
	stats.PendingByPartition = pendingByPartition
}

// UserStats is per-user running-job resource usage.
type UserStats struct {
	Username      string
	JobCount      int
	TotalCPUs     int
	TotalMemoryGB float64
	TotalGPUs     int
	TotalNodes    int
	GPUTypes      string
	NodeNames     string
	ArrayCount    int
	PlainJobCount int
	// GenericGPUJobs counts job rows whose GPU request named no model
	// (bare "gres/gpu=N"). Their counts are attributed to the hardware they
	// landed on when the job's nodes carry a single GPU model.
	GenericGPUJobs int
}

// NodeGPUModels maps node name → its single GPU model (upper-cased), used to
// attribute generic GPU requests to the hardware they landed on. Nodes without
// GPUs or with more than one model (e.g. mixed MIG profiles) are omitted.
func NodeGPUModels(nodes []slurm.Node) map[string]string {
	m := make(map[string]string, len(nodes))
	for _, n := range nodes {
		name := strings.TrimSpace(n.Name)
		if name == "" {
			continue
		}
		if model := nodeGPUModel(n); model != "" {
			m[name] = model
		}
	}
	return m
}

// userAccumulator collects per-user running-job data before conversion.
type userAccumulator struct {
	jobCount       int
	totalCPUs      int
	totalMemoryGB  float64
	totalGPUs      int
	gpuTypes       map[string]int
	nodeNames      map[string]struct{}
	arrayBaseIDs   map[string]struct{}
	plainJobCount  int
	genericGPUJobs int
}

// AggregateUserStats aggregates all-users job rows into per-user statistics,
// folding each job's CPU/memory/GPU/node usage into its owner's totals and
// classifying it as an array task or a plain job. gpuModelByNode (see
// NodeGPUModels) attributes typeless GPU requests to the hardware they run on;
// nil disables the resolution and such requests stay in the generic bucket.
func AggregateUserStats(jobs []slurm.AllUsersJob, gpuModelByNode map[string]string) []UserStats {
	byUser := map[string]*userAccumulator{}

	for _, job := range jobs {
		username := strings.TrimSpace(job.User)
		if username == "" {
			continue
		}
		acc := byUser[username]
		if acc == nil {
			acc = &userAccumulator{
				gpuTypes:     map[string]int{},
				nodeNames:    map[string]struct{}{},
				arrayBaseIDs: map[string]struct{}{},
			}
			byUser[username] = acc
		}
		processJobForUser(acc, job, gpuModelByNode)
	}

	out := make([]UserStats, 0, len(byUser))
	for username, acc := range byUser {
		out = append(out, UserStats{
			Username:       username,
			JobCount:       acc.jobCount,
			TotalCPUs:      acc.totalCPUs,
			TotalMemoryGB:  acc.totalMemoryGB,
			TotalGPUs:      acc.totalGPUs,
			TotalNodes:     len(acc.nodeNames),
			GPUTypes:       slurm.FormatGPUTypes(acc.gpuTypes),
			NodeNames:      joinSorted(acc.nodeNames),
			ArrayCount:     len(acc.arrayBaseIDs),
			PlainJobCount:  acc.plainJobCount,
			GenericGPUJobs: acc.genericGPUJobs,
		})
	}
	return out
}

// processJobForUser folds a single job row into a user's accumulator.
func processJobForUser(acc *userAccumulator, job slurm.AllUsersJob, gpuModelByNode map[string]string) {
	acc.jobCount++

	jobID := strings.TrimSpace(job.ID)
	switch {
	case strings.Contains(jobID, "_["):
		// Pending array leaking into running counts; ignore for classification.
	case strings.Contains(jobID, "_"):
		acc.arrayBaseIDs[strings.SplitN(jobID, "_", 2)[0]] = struct{}{}
	default:
		acc.plainJobCount++
	}

	nodeCount := parseNodeCount(strings.TrimSpace(job.NumNodes))

	jobNodes := slurm.ExpandNodeList(strings.TrimSpace(job.NodeList))
	for _, name := range jobNodes {
		acc.nodeNames[name] = struct{}{}
	}

	res := slurm.ParseTRESResources(strings.TrimSpace(job.TRES))
	if res.CPUs > 0 {
		acc.totalCPUs += res.CPUs
	} else {
		acc.totalCPUs += nodeCount
	}
	acc.totalMemoryGB += res.MemoryGB

	// A job's TRES commonly lists the same GPUs both generically ("gres/gpu=3")
	// and by model; AggregateGPUCounts drops the generic duplicate. A job is only
	// a *generic request* when no typed entry exists at all — then its count is
	// attributed to the single GPU model of the nodes it runs on, or kept in the
	// generic bucket when that is unknown or mixed.
	gpuCounts := slurm.AggregateGPUCounts(res.GPUs, true)
	if generic, ok := gpuCounts["GPU"]; ok {
		acc.genericGPUJobs++
		if model := singleNodeModel(jobNodes, gpuModelByNode); model != "" {
			delete(gpuCounts, "GPU")
			gpuCounts[model] += generic
		}
	}
	for gpuType, count := range gpuCounts {
		acc.gpuTypes[gpuType] += count
		acc.totalGPUs += count
	}
}

// singleNodeModel returns the GPU model shared by every node in nodes, or ""
// when nodes is empty, any node is unknown, or the models differ.
func singleNodeModel(nodes []string, gpuModelByNode map[string]string) string {
	model := ""
	for _, name := range nodes {
		m := gpuModelByNode[name]
		if m == "" || (model != "" && m != model) {
			return ""
		}
		model = m
	}
	return model
}

// parseNodeCount parses a node count that may be a single number ("4") or a
// range ("4-8", meaning 5 nodes).
func parseNodeCount(nodesStr string) int {
	if strings.Contains(nodesStr, "-") {
		parts := strings.Split(nodesStr, "-")
		if len(parts) == 2 {
			start, err1 := strconv.Atoi(parts[0])
			end, err2 := strconv.Atoi(parts[1])
			if err1 == nil && err2 == nil {
				return end - start + 1
			}
			return 0
		}
	}
	n, err := strconv.Atoi(nodesStr)
	if err != nil {
		return 0
	}
	return n
}

// joinSorted returns the set's keys joined by commas in sorted order.
func joinSorted(set map[string]struct{}) string {
	keys := make([]string, 0, len(set))
	for k := range set {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return strings.Join(keys, ",")
}

// FindUserStats returns the stats entry for username, or ok=false when the user
// has no running jobs. The Jobs tab banner renders from it.
func FindUserStats(users []UserStats, username string) (UserStats, bool) {
	for _, u := range users {
		if u.Username == username {
			return u, true
		}
	}
	return UserStats{}, false
}
