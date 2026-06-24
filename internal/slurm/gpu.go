package slurm

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// gresGPUInTRES matches GPU entries inside a TRES string, e.g. "gres/gpu=8" or
// "gres/gpu:h200=8".
var gresGPUInTRES = regexp.MustCompile(`(?i)gres/gpu(?::([^=,]+))?=(\d+)`)

// gpuInGres matches GPU entries inside a Gres field, e.g. "gpu:4", "gpu:a100:4",
// or "gpu:h200:8(S:0-1)".
var gpuInGres = regexp.MustCompile(`(?i)gpu(?::([^:(),]+))?:(\d+)(?:\([^)]+\))?`)

// ParseGPUEntries parses GPU entries from a TRES string (CfgTRES, AllocTRES, or
// similar). The returned Type is "gpu" for generic entries or a specific model
// such as "h200". Case from the input is preserved.
func ParseGPUEntries(tres string) []GPUEntry {
	var entries []GPUEntry
	for _, m := range gresGPUInTRES.FindAllStringSubmatch(tres, -1) {
		typ := "gpu"
		if m[1] != "" {
			typ = m[1]
		}
		count, err := strconv.Atoi(m[2])
		if err != nil {
			continue
		}
		entries = append(entries, GPUEntry{Type: typ, Count: count})
	}
	return entries
}

// ParseGPUFromGres parses GPU entries from a Gres field string. It is the
// fallback used when TRES data is unavailable. Unlike ParseGPUEntries the Type is
// upper-cased. Strings without "gpu:" yield nil.
func ParseGPUFromGres(gres string) []GPUEntry {
	if !strings.Contains(strings.ToLower(gres), "gpu:") {
		return nil
	}
	var entries []GPUEntry
	for _, m := range gpuInGres.FindAllStringSubmatch(gres, -1) {
		typ := "gpu"
		if m[1] != "" {
			typ = m[1]
		}
		count, err := strconv.Atoi(m[2])
		if err != nil {
			continue
		}
		entries = append(entries, GPUEntry{Type: strings.ToUpper(typ), Count: count})
	}
	return entries
}

// HasSpecificGPUTypes reports whether any entry carries a specific GPU model
// (anything other than the generic "gpu").
func HasSpecificGPUTypes(entries []GPUEntry) bool {
	for _, e := range entries {
		if strings.ToLower(e.Type) != "gpu" {
			return true
		}
	}
	return false
}

// AggregateGPUCounts sums GPU entries into a map of upper-cased type to count.
// When skipGenericIfSpecific is true and specific models are present, generic
// "gpu" entries are dropped to avoid double-counting the same GPUs reported both
// generically and by model.
func AggregateGPUCounts(entries []GPUEntry, skipGenericIfSpecific bool) map[string]int {
	hasSpecific := HasSpecificGPUTypes(entries)
	result := make(map[string]int)
	for _, e := range entries {
		if skipGenericIfSpecific && hasSpecific && strings.ToLower(e.Type) == "gpu" {
			continue
		}
		result[strings.ToUpper(e.Type)] += e.Count
	}
	return result
}

// CalculateTotalGPUs returns the total GPU count across entries, applying the
// same generic/specific de-duplication as AggregateGPUCounts.
func CalculateTotalGPUs(entries []GPUEntry, skipGenericIfSpecific bool) int {
	total := 0
	for _, n := range AggregateGPUCounts(entries, skipGenericIfSpecific) {
		total += n
	}
	return total
}

// FormatGPUTypes renders aggregated GPU counts into a human-readable string such
// as "8x H200" or "4x A100, 2x V100". Types are sorted for deterministic output.
// An empty map yields the empty string.
func FormatGPUTypes(counts map[string]int) string {
	if len(counts) == 0 {
		return ""
	}
	types := make([]string, 0, len(counts))
	for t := range counts {
		types = append(types, t)
	}
	sort.Strings(types)
	parts := make([]string, len(types))
	for i, t := range types {
		parts[i] = strconv.Itoa(counts[t]) + "x " + ShortGPULabel(t)
	}
	return strings.Join(parts, ", ")
}

// migProfile matches an NVIDIA MIG profile such as "1g.10gb" embedded in a GRES
// type string like "h100_pcie_1g.10gb".
var migProfile = regexp.MustCompile(`(?i)\d+g\.\d+gb`)

// ShortGPULabel renders a GPU type for display. A MIG type is shortened to its
// bare profile ("H100_PCIE_1G.10GB" -> "1g.10gb"); any other type is returned
// unchanged.
func ShortGPULabel(typ string) string {
	if m := migProfile.FindString(typ); m != "" {
		return strings.ToLower(m)
	}
	return typ
}
