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

// GPUTotalAlloc is the (total, allocated) GPU count pair stored per GPU type in
// ClusterStats.
type GPUTotalAlloc struct {
	Total     int
	Allocated int
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
	GPUsByType        map[string]GPUTotalAlloc
	DrainingNodes     int

	PendingJobsCount   int
	PendingCPUs        int
	PendingMemoryGB    float64
	PendingGPUs        int
	PendingGPUsByType  map[string]int
	PendingByPartition map[string]PendingPartitionStats

	WaitStatsByPartition map[string]PartitionWaitStats
	WaitStatsHours       int
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

// FreeGPUsPct returns the percentage of free GPUs.
func (s ClusterStats) FreeGPUsPct() float64 {
	if s.TotalGPUs == 0 {
		return 0
	}
	return float64(s.TotalGPUs-s.AllocatedGPUs) / float64(s.TotalGPUs) * 100.0
}

// GPUTypeFreePct returns the percentage of free GPUs for a specific type.
func (s ClusterStats) GPUTypeFreePct(gpuType string) float64 {
	ta, ok := s.GPUsByType[gpuType]
	if !ok || ta.Total == 0 {
		return 0
	}
	return float64(ta.Total-ta.Allocated) / float64(ta.Total) * 100.0
}

// newClusterStats returns a ClusterStats with all maps initialised and the
// wait-stats window defaulting to 1 hour.
func newClusterStats() ClusterStats {
	return ClusterStats{
		GPUsByType:           map[string]GPUTotalAlloc{},
		PendingGPUsByType:    map[string]int{},
		PendingByPartition:   map[string]PendingPartitionStats{},
		WaitStatsByPartition: map[string]PartitionWaitStats{},
		WaitStatsHours:       1,
	}
}

// DeriveClusterStats computes cluster statistics from nodes, all-users jobs (for
// pending resources), and wait-time records. It handles draining nodes, GPU
// accounting from CfgTRES/AllocTRES with a Gres fallback, array-expanded pending
// aggregation, and per-partition wait-time stats.
func DeriveClusterStats(nodes []slurm.Node, allUsersJobs []slurm.AllUsersJob, waitTimeJobs []slurm.WaitTimeRecord) ClusterStats {
	stats := newClusterStats()

	if len(nodes) == 0 {
		aggregatePending(allUsersJobs, &stats)
		return stats
	}

	for _, node := range nodes {
		state := strings.ToUpper(node.State)
		isDraining := parseNodeState(state, &stats)
		parseNodeCPUs(node, &stats, !isDraining)
		parseNodeMemory(node, &stats, !isDraining)

		if !isDraining {
			processGPUEntries(slurm.ParseGPUEntries(node.CfgTRES), &stats, false)
			processGPUEntries(slurm.ParseGPUEntries(node.AllocTRES), &stats, true)
		}

		if node.CfgTRES == "" && node.AllocTRES == "" {
			parseGPUsFromGres(node, state, &stats, !isDraining)
		}
	}

	aggregatePending(allUsersJobs, &stats)

	if len(waitTimeJobs) > 0 {
		stats.WaitStatsByPartition = CalculatePartitionWaitStats(waitTimeJobs)
		stats.WaitStatsHours = 1
	}

	return stats
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

// processGPUEntries folds GPU entries into the per-type totals/allocations,
// skipping generic "gpu" entries when specific models are present.
func processGPUEntries(entries []slurm.GPUEntry, stats *ClusterStats, isAllocated bool) {
	hasSpecific := slurm.HasSpecificGPUTypes(entries)
	for _, e := range entries {
		if hasSpecific && strings.ToLower(e.Type) == "gpu" {
			continue
		}
		ta := stats.GPUsByType[e.Type]
		if isAllocated {
			ta.Allocated += e.Count
			stats.AllocatedGPUs += e.Count
		} else {
			ta.Total += e.Count
			stats.TotalGPUs += e.Count
		}
		stats.GPUsByType[e.Type] = ta
	}
}

// parseGPUsFromGres is the fallback GPU accounting from the Gres field used when
// TRES data is absent. It estimates allocation from node state (an ALLOCATED or
// MIXED node is treated as having all its GPUs in use).
func parseGPUsFromGres(node slurm.Node, state string, stats *ClusterStats, includeTotal bool) {
	entries := slurm.ParseGPUFromGres(node.Gres)
	for _, e := range entries {
		if includeTotal {
			ta := stats.GPUsByType[e.Type]
			ta.Total += e.Count
			stats.GPUsByType[e.Type] = ta
			stats.TotalGPUs += e.Count
		}
		if includeTotal && (strings.Contains(state, "ALLOCATED") || strings.Contains(state, "MIXED")) {
			ta := stats.GPUsByType[e.Type]
			ta.Allocated += e.Count
			stats.GPUsByType[e.Type] = ta
			stats.AllocatedGPUs += e.Count
		}
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
			pendingGPUs += scaled
			ps.GPUs += scaled
			pendingGPUsByType[e.Type] += scaled
			ps.GPUsByType[e.Type] += scaled
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
}

// userAccumulator collects per-user running-job data before conversion.
type userAccumulator struct {
	jobCount      int
	totalCPUs     int
	totalMemoryGB float64
	totalGPUs     int
	gpuTypes      map[string]int
	nodeNames     map[string]struct{}
	arrayBaseIDs  map[string]struct{}
	plainJobCount int
}

// AggregateUserStats aggregates all-users job rows into per-user statistics,
// folding each job's CPU/memory/GPU/node usage into its owner's totals and
// classifying it as an array task or a plain job.
func AggregateUserStats(jobs []slurm.AllUsersJob) []UserStats {
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
		processJobForUser(acc, job)
	}

	out := make([]UserStats, 0, len(byUser))
	for username, acc := range byUser {
		out = append(out, UserStats{
			Username:      username,
			JobCount:      acc.jobCount,
			TotalCPUs:     acc.totalCPUs,
			TotalMemoryGB: acc.totalMemoryGB,
			TotalGPUs:     acc.totalGPUs,
			TotalNodes:    len(acc.nodeNames),
			GPUTypes:      slurm.FormatGPUTypes(acc.gpuTypes),
			NodeNames:     joinSorted(acc.nodeNames),
			ArrayCount:    len(acc.arrayBaseIDs),
			PlainJobCount: acc.plainJobCount,
		})
	}
	return out
}

// processJobForUser folds a single job row into a user's accumulator.
func processJobForUser(acc *userAccumulator, job slurm.AllUsersJob) {
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

	for _, name := range slurm.ExpandNodeList(strings.TrimSpace(job.NodeList)) {
		acc.nodeNames[name] = struct{}{}
	}

	res := slurm.ParseTRESResources(strings.TrimSpace(job.TRES))
	if res.CPUs > 0 {
		acc.totalCPUs += res.CPUs
	} else {
		acc.totalCPUs += nodeCount
	}
	acc.totalMemoryGB += res.MemoryGB

	gpuCounts := slurm.AggregateGPUCounts(res.GPUs, true)
	for gpuType, count := range gpuCounts {
		acc.gpuTypes[gpuType] += count
	}
	acc.totalGPUs += slurm.CalculateTotalGPUs(res.GPUs, true)
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

// MyUsageSummary renders the Jobs-tab "My Usage" banner for the given username
// from the running-job user statistics. When the user has no running jobs it
// returns the "No running jobs" message.
func MyUsageSummary(users []UserStats, username string) string {
	var mine *UserStats
	for i := range users {
		if users[i].Username == username {
			mine = &users[i]
			break
		}
	}
	if mine == nil {
		return "My Usage: No running jobs"
	}

	parts := []string{
		strconv.Itoa(mine.TotalCPUs) + " CPUs",
		strconv.FormatFloat(mine.TotalMemoryGB, 'f', 1, 64) + " GB RAM",
	}
	if mine.TotalGPUs > 0 {
		gpuLabel := strconv.Itoa(mine.TotalGPUs) + " GPUs"
		if mine.GPUTypes != "" {
			gpuLabel += " (" + mine.GPUTypes + ")"
		}
		parts = append(parts, gpuLabel)
	}
	parts = append(parts, strconv.Itoa(mine.TotalNodes)+" Nodes")

	x, y, z := mine.JobCount, mine.ArrayCount, mine.PlainJobCount
	parts = append(parts, strconv.Itoa(x)+" "+plural(x, "task", "tasks")+
		" ("+strconv.Itoa(y)+" "+plural(y, "array", "arrays")+
		", "+strconv.Itoa(z)+" "+plural(z, "job", "jobs")+")")

	return "My Usage: " + strings.Join(parts, " | ")
}

// plural returns the singular form when n == 1, otherwise the plural form.
func plural(n int, singular, pluralForm string) string {
	if n == 1 {
		return singular
	}
	return pluralForm
}
