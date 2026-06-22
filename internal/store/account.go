package store

import (
	"strings"

	"github.com/pjhartout/stoei/internal/slurm"
)

// AccountResourceUsage is the aggregate "Current Resource Usage" of an account's
// running jobs: summed CPUs/memory/GPUs and the count of unique nodes.
type AccountResourceUsage struct {
	TotalCPUs     int
	TotalMemoryGB float64
	TotalGPUs     int
	UniqueNodes   int
}

// AggregateAccountResources sums the CPU, memory, and GPU resources of the given
// running jobs and counts the unique expanded node names. CPUs and memory come
// from parsing each job's TRES (no node-count fallback), GPUs from the total GPU
// count (skipping generic entries when a specific model is present), and unique
// nodes from expanding each job's NodeList.
func AggregateAccountResources(jobs []AllUsersJob) AccountResourceUsage {
	var usage AccountResourceUsage
	unique := map[string]struct{}{}
	for _, job := range jobs {
		res := slurm.ParseTRESResources(strings.TrimSpace(job.TRES))
		usage.TotalCPUs += res.CPUs
		usage.TotalMemoryGB += res.MemoryGB
		usage.TotalGPUs += slurm.CalculateTotalGPUs(res.GPUs, true)
		for _, name := range slurm.ExpandNodeList(strings.TrimSpace(job.NodeList)) {
			unique[name] = struct{}{}
		}
	}
	usage.UniqueNodes = len(unique)
	return usage
}
