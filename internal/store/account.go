package store

import (
	"strings"

	"github.com/pjhartout/stoei/internal/slurm"
)

// AccountResourceUsage is the aggregate "Current Resource Usage" of an account's
// running jobs: summed CPUs/memory/GPUs and the count of unique nodes. Ports the
// aggregate block in formatters.format_account_info (formatters.py 888-916).
type AccountResourceUsage struct {
	TotalCPUs     int
	TotalMemoryGB float64
	TotalGPUs     int
	UniqueNodes   int
}

// AggregateAccountResources sums the CPU, memory, and GPU resources of the given
// running jobs and counts the unique expanded node names. It mirrors the Python
// block exactly: CPUs/memory come from parse_tres_resources on the job's TRES
// (no node-count fallback), GPUs from calculate_total_gpus (skipping generic
// entries when a specific model is present), and unique nodes from
// expand_nodelist over the job's NodeList. Ports formatters.py 893-916.
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
