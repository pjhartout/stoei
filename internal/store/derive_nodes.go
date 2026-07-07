package store

import (
	"sort"
	"strconv"
	"strings"

	"github.com/pjhartout/stoei/internal/slurm"
)

// NodeDisplay is the per-node view-model rendered by the Nodes tab. It carries
// pre-parsed values so the tab renders plain numbers and strings without touching
// the raw slurm.Node fields.
type NodeDisplay struct {
	Name          string
	State         string
	CPUsAlloc     int
	CPUsTotal     int
	MemoryAllocGB float64
	MemoryTotalGB float64
	GPUsAlloc     int
	GPUsTotal     int
	GPUTypes      string
	Partitions    string
	Reason        string
}

// CPUUsagePct returns the allocated-CPU percentage, or 0 when the node has no
// CPUs.
func (n NodeDisplay) CPUUsagePct() float64 {
	if n.CPUsTotal == 0 {
		return 0
	}
	return float64(n.CPUsAlloc) / float64(n.CPUsTotal) * 100.0
}

// MemoryUsagePct returns the allocated-memory percentage, or 0 when the node has
// no memory.
func (n NodeDisplay) MemoryUsagePct() float64 {
	if n.MemoryTotalGB == 0 {
		return 0
	}
	return n.MemoryAllocGB / n.MemoryTotalGB * 100.0
}

// GPUUsagePct returns the allocated-GPU percentage, or 0 when the node has no
// GPUs.
func (n NodeDisplay) GPUUsagePct() float64 {
	if n.GPUsTotal == 0 {
		return 0
	}
	return float64(n.GPUsAlloc) / float64(n.GPUsTotal) * 100.0
}

// memoryMBToGB is the MB-to-GB divisor used throughout the node parsing.
const memoryMBToGB = 1024.0

// DeriveNodeDisplays converts raw scontrol nodes into per-node view-models. Nodes
// with an empty name are skipped. GPU totals come from CfgTRES (preferred) or the
// Gres fallback; allocated GPUs come from AllocTRES or, absent that, a state-based
// estimate (ALLOCATED/MIXED imply all GPUs in use).
func DeriveNodeDisplays(nodes []slurm.Node) []NodeDisplay {
	out := make([]NodeDisplay, 0, len(nodes))
	for _, node := range nodes {
		name := strings.TrimSpace(node.Name)
		if name == "" {
			continue
		}

		state := strings.TrimSpace(node.State)
		if state == "" {
			state = "UNKNOWN"
		}
		partitions := strings.TrimSpace(node.Fields["Partitions"])
		if partitions == "" {
			partitions = "N/A"
		}

		cpusTotal := atoiDefault(node.CPUTot)
		cpusAlloc := atoiDefault(node.CPUAlloc)
		memTotalGB := float64(atoiDefault(node.RealMem)) / memoryMBToGB
		memAllocGB := float64(atoiDefault(node.AllocMem)) / memoryMBToGB

		gpusTotal, gpusAlloc, gpuTypes := nodeGPUs(node, state)

		out = append(out, NodeDisplay{
			Name:          name,
			State:         state,
			CPUsAlloc:     cpusAlloc,
			CPUsTotal:     cpusTotal,
			MemoryAllocGB: memAllocGB,
			MemoryTotalGB: memTotalGB,
			GPUsAlloc:     gpusAlloc,
			GPUsTotal:     gpusTotal,
			GPUTypes:      gpuTypes,
			Partitions:    partitions,
			Reason:        strings.TrimSpace(node.Reason),
		})
	}
	return out
}

// nodeGPUs returns the (total, allocated, formatted-types) GPU view for a node,
// applying the CfgTRES→Gres total fallback and the AllocTRES→state-based alloc
// fallback.
func nodeGPUs(node slurm.Node, state string) (total, alloc int, types string) {
	model := nodeGPUModel(node)
	var counts map[string]int

	switch {
	case node.CfgTRES != "":
		entries := relabelGeneric(slurm.ParseGPUEntries(node.CfgTRES), model)
		counts = slurm.AggregateGPUCounts(entries, true)
		total = slurm.CalculateTotalGPUs(entries, true)
	case strings.Contains(strings.ToLower(node.Gres), "gpu:"):
		entries := slurm.ParseGPUFromGres(node.Gres)
		counts = slurm.AggregateGPUCounts(entries, true)
		total = slurm.CalculateTotalGPUs(entries, true)
	}
	types = slurm.FormatGPUTypes(counts)

	switch {
	case node.AllocTRES != "":
		alloc = slurm.CalculateTotalGPUs(relabelGeneric(slurm.ParseGPUEntries(node.AllocTRES), model), true)
	case total > 0:
		up := strings.ToUpper(state)
		if strings.Contains(up, "ALLOCATED") || strings.Contains(up, "MIXED") {
			alloc = total
		}
	}
	return total, alloc, types
}

// atoiDefault parses an integer, returning 0 for empty or unparseable input.
func atoiDefault(s string) int {
	n, err := strconv.Atoi(strings.TrimSpace(s))
	if err != nil {
		return 0
	}
	return n
}

// NodeDisplays returns the per-node view-models derived from the current nodes.
func (s *Store) NodeDisplays() []NodeDisplay {
	return DeriveNodeDisplays(s.Nodes)
}

// NodeJob is one job occupying a node, with its user and parsed resource use, for
// the "Jobs on Node" section of the node-detail modal.
type NodeJob struct {
	ID   string
	Name string
	User string
	Time string
	CPUs int
	GPUs int
}

// JobsOnNode returns the jobs whose allocated NodeList includes node, sorted by
// user then job id. CPUs and GPUs come from each job's TRES and are whole-job
// totals, so a multi-node job's counts are its full allocation, not the share on
// this node. ponytail: per-node split needs per-node TRES that squeue doesn't
// give us; whole-job totals if a job spans nodes.
func JobsOnNode(jobs []AllUsersJob, node string) []NodeJob {
	node = strings.TrimSpace(node)
	var out []NodeJob
	for _, j := range jobs {
		if !nodeListContains(j.NodeList, node) {
			continue
		}
		res := slurm.ParseTRESResources(strings.TrimSpace(j.TRES))
		out = append(out, NodeJob{
			ID:   strings.TrimSpace(j.ID),
			Name: strings.TrimSpace(j.Name),
			User: strings.TrimSpace(j.User),
			Time: strings.TrimSpace(j.Time),
			CPUs: res.CPUs,
			GPUs: slurm.CalculateTotalGPUs(res.GPUs, true),
		})
	}
	sort.SliceStable(out, func(i, k int) bool {
		if out[i].User != out[k].User {
			return out[i].User < out[k].User
		}
		return out[i].ID < out[k].ID
	})
	return out
}

// nodeListContains reports whether node appears in the expanded nodelist.
func nodeListContains(nodelist, node string) bool {
	if node == "" {
		return false
	}
	for _, name := range slurm.ExpandNodeList(strings.TrimSpace(nodelist)) {
		if name == node {
			return true
		}
	}
	return false
}
