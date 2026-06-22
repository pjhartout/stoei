package slurm

import (
	"regexp"
	"strconv"
	"strings"
)

// tresCPU matches the CPU count in a TRES string; tresMem captures the memory's
// numeric value and a G/M/T unit.
var (
	tresCPU = regexp.MustCompile(`(?i)cpu=(\d+)`)
	tresMem = regexp.MustCompile(`(?i)mem=(\d+)([GMT])`)
)

// TRESResources is the CPU, memory, and GPU breakdown of a single TRES string.
type TRESResources struct {
	CPUs     int
	MemoryGB float64
	GPUs     []GPUEntry
}

// ParseTRESResources extracts CPU count, memory in GB, and GPU entries from a
// TRES string such as "cpu=32,mem=256G,node=4,gres/gpu:h200=8". It is the
// canonical TRES parser. Missing or unparseable fields default to zero values.
func ParseTRESResources(tres string) TRESResources {
	res := TRESResources{}
	if strings.TrimSpace(tres) == "" {
		return res
	}

	if m := tresCPU.FindStringSubmatch(tres); m != nil {
		if n, err := strconv.Atoi(m[1]); err == nil {
			res.CPUs = n
		}
	}

	if m := tresMem.FindStringSubmatch(tres); m != nil {
		if v, err := strconv.Atoi(m[1]); err == nil {
			switch strings.ToUpper(m[2]) {
			case "G":
				res.MemoryGB = float64(v)
			case "M":
				res.MemoryGB = float64(v) / 1024.0
			case "T":
				res.MemoryGB = float64(v) * 1024.0
			}
		}
	}

	res.GPUs = ParseGPUEntries(tres)
	return res
}

// ParseCPUCountFromTRES returns just the CPU count from a TRES string, or 0 if
// absent.
func ParseCPUCountFromTRES(tres string) int {
	if tres == "" {
		return 0
	}
	if m := tresCPU.FindStringSubmatch(tres); m != nil {
		if n, err := strconv.Atoi(m[1]); err == nil {
			return n
		}
	}
	return 0
}
