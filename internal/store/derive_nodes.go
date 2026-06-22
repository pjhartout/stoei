package store

import (
	"strconv"
	"strings"

	"github.com/pjhartout/stoei/internal/slurm"
)

// NodeDisplay is the per-node view-model rendered by the Nodes tab. It ports the
// NodeInfo dataclass in widgets/node_overview.py together with the parsing
// app._build_node_infos performs, so the tab renders plain values without
// touching the raw slurm.Node fields.
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
// CPUs. Ports NodeInfo.cpu_usage_pct.
func (n NodeDisplay) CPUUsagePct() float64 {
	if n.CPUsTotal == 0 {
		return 0
	}
	return float64(n.CPUsAlloc) / float64(n.CPUsTotal) * 100.0
}

// MemoryUsagePct returns the allocated-memory percentage, or 0 when the node has
// no memory. Ports NodeInfo.memory_usage_pct.
func (n NodeDisplay) MemoryUsagePct() float64 {
	if n.MemoryTotalGB == 0 {
		return 0
	}
	return n.MemoryAllocGB / n.MemoryTotalGB * 100.0
}

// GPUUsagePct returns the allocated-GPU percentage, or 0 when the node has no
// GPUs. Ports NodeInfo.gpu_usage_pct.
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
// estimate (ALLOCATED/MIXED imply all GPUs in use). Ports app._build_node_infos.
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
// fallback from app._build_node_infos.
func nodeGPUs(node slurm.Node, state string) (total, alloc int, types string) {
	var counts map[string]int

	switch {
	case node.CfgTRES != "":
		entries := slurm.ParseGPUEntries(node.CfgTRES)
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
		alloc = slurm.CalculateTotalGPUs(slurm.ParseGPUEntries(node.AllocTRES), true)
	case total > 0:
		up := strings.ToUpper(state)
		if strings.Contains(up, "ALLOCATED") || strings.Contains(up, "MIXED") {
			alloc = total
		}
	}
	return total, alloc, types
}

// atoiDefault parses an integer, returning 0 for empty or unparseable input,
// mirroring the Python int(node_data.get(key, "0") or "0") pattern.
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
