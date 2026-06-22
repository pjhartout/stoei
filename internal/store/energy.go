package store

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/pjhartout/stoei/internal/slurm"
)

// tdpValuesJSON is the embedded copy of stoei/data/tdp_values.json. Keeping a
// copy in the package keeps the binary self-contained and the derive logic pure.
//
//go:embed tdp_values.json
var tdpValuesJSON []byte

// Fallback TDP values, used if the embedded JSON cannot be parsed. They mirror
// energy._FALLBACK_DEFAULT_GPU_TDP and _FALLBACK_CPU_TDP_PER_CORE.
const (
	fallbackDefaultGPUTDP = 300
	fallbackCPUTDPPerCore = 10
)

// secondsPerHour is the conversion factor used by the energy calculations.
const secondsPerHour = 3600.0

// Energy unit thresholds in Watt-hours, matching energy.ENERGY_*_THRESHOLD.
const (
	energyGWhThreshold = 1_000_000_000.0
	energyMWhThreshold = 1_000_000.0
	energyKWhThreshold = 1000.0
)

// tdpTable holds the parsed TDP lookup data. It is computed once at package init
// from the embedded JSON.
type tdpTable struct {
	gpu          map[string]int // upper-cased GPU model -> TDP in Watts
	defaultGPU   int
	cpuPerCore   int
	sortedModels []string // keys of gpu, sorted, for deterministic partial matching
}

// tdp is the package-level parsed TDP table. It is read-only after init.
var tdp = loadTDP()

// loadTDP parses the embedded tdp_values.json into a tdpTable, falling back to
// the constant defaults on any error. It ports energy._load_tdp_values.
func loadTDP() tdpTable {
	t := tdpTable{
		gpu:        map[string]int{},
		defaultGPU: fallbackDefaultGPUTDP,
		cpuPerCore: fallbackCPUTDPPerCore,
	}

	var raw map[string]json.RawMessage
	if err := json.Unmarshal(tdpValuesJSON, &raw); err != nil {
		return t.finalize()
	}

	if gpuRaw, ok := raw["gpu"]; ok {
		var gpuData map[string]json.RawMessage
		if err := json.Unmarshal(gpuRaw, &gpuData); err == nil {
			parseGPUSection(gpuData, &t)
		}
	}

	if cpuRaw, ok := raw["cpu"]; ok {
		var cpuData map[string]json.RawMessage
		if err := json.Unmarshal(cpuRaw, &cpuData); err == nil {
			if v, ok := intValue(cpuData["_default_per_core"]); ok {
				t.cpuPerCore = v
			}
		}
	}

	return t.finalize()
}

// parseGPUSection flattens the (possibly nested) GPU section into t.gpu and reads
// the _default value, matching the Python loader's handling of category dicts and
// direct model->TDP entries.
func parseGPUSection(gpuData map[string]json.RawMessage, t *tdpTable) {
	if v, ok := intValue(gpuData["_default"]); ok {
		t.defaultGPU = v
	}
	for key, val := range gpuData {
		if strings.HasPrefix(key, "_") {
			continue
		}
		// Direct model -> TDP mapping.
		if v, ok := intValue(val); ok {
			t.gpu[strings.ToUpper(key)] = v
			continue
		}
		// Category dict of model -> TDP.
		var category map[string]json.RawMessage
		if err := json.Unmarshal(val, &category); err != nil {
			continue
		}
		for model, tdpRaw := range category {
			if v, ok := intValue(tdpRaw); ok {
				t.gpu[strings.ToUpper(model)] = v
			}
		}
	}
}

// finalize computes the sorted model list for deterministic partial matching.
func (t tdpTable) finalize() tdpTable {
	t.sortedModels = make([]string, 0, len(t.gpu))
	for k := range t.gpu {
		t.sortedModels = append(t.sortedModels, k)
	}
	sort.Strings(t.sortedModels)
	return t
}

// intValue reports the integer value of a JSON number that is an exact integer.
// Floats and non-numbers return ok=false, matching the Python loader's
// isinstance(value, int) check (Python bools would also pass isinstance int, but
// the data never contains bools).
func intValue(raw json.RawMessage) (int, bool) {
	if len(raw) == 0 {
		return 0, false
	}
	s := strings.TrimSpace(string(raw))
	n, err := strconv.Atoi(s)
	if err != nil {
		return 0, false
	}
	return n, true
}

// GetGPUTDP returns the TDP in Watts for a GPU type, matching energy.get_gpu_tdp:
// exact (case-insensitive) match, then prefix-stripped match, then a partial
// substring match, then the default. The partial match scans models in sorted
// order for determinism.
func GetGPUTDP(gpuType string) int {
	if gpuType == "" {
		return tdp.defaultGPU
	}
	normalized := strings.ToUpper(strings.TrimSpace(gpuType))

	if v, ok := tdp.gpu[normalized]; ok {
		return v
	}

	for _, prefix := range []string{"NVIDIA_", "NVIDIA-", "AMD_", "AMD-", "INTEL_", "INTEL-"} {
		if strings.HasPrefix(normalized, prefix) {
			stripped := normalized[len(prefix):]
			if v, ok := tdp.gpu[stripped]; ok {
				return v
			}
		}
	}

	for _, model := range tdp.sortedModels {
		if strings.Contains(normalized, model) || strings.Contains(model, normalized) {
			return tdp.gpu[model]
		}
	}

	return tdp.defaultGPU
}

// CPUTDPPerCore returns the per-core CPU TDP in Watts. Ports
// energy.get_cpu_tdp_per_core.
func CPUTDPPerCore() int { return tdp.cpuPerCore }

// CalculateJobEnergyWh estimates a job's energy use in Watt-hours assuming 100%
// utilization for the whole duration. Ports energy.calculate_job_energy_wh.
func CalculateJobEnergyWh(gpuCount int, gpuType string, cpuCount int, durationSeconds float64) float64 {
	if durationSeconds <= 0 {
		return 0
	}
	durationHours := durationSeconds / secondsPerHour

	gpuTDP := 0
	if gpuCount > 0 {
		gpuTDP = GetGPUTDP(gpuType)
	}
	gpuEnergy := float64(gpuCount) * float64(gpuTDP) * durationHours
	cpuEnergy := float64(cpuCount) * float64(CPUTDPPerCore()) * durationHours
	return gpuEnergy + cpuEnergy
}

// FormatEnergy renders a Watt-hour value with auto-scaling units, matching
// energy.format_energy exactly (Wh / kWh / MWh / GWh, with the same precision per
// tier and the "0 Wh" clamp for negatives).
func FormatEnergy(wh float64) string {
	if wh < 0 {
		return "0 Wh"
	}
	switch {
	case wh >= energyGWhThreshold:
		return fmt.Sprintf("%.2f GWh", wh/energyGWhThreshold)
	case wh >= energyMWhThreshold:
		return fmt.Sprintf("%.2f MWh", wh/energyMWhThreshold)
	case wh >= energyKWhThreshold:
		return fmt.Sprintf("%.1f kWh", wh/energyKWhThreshold)
	case wh >= 1:
		return fmt.Sprintf("%.0f Wh", wh)
	default:
		return fmt.Sprintf("%.2f Wh", wh)
	}
}

// UserEnergyStats is per-user energy usage over a historical period. Ports the
// usage_stats.UserEnergyStats dataclass.
type UserEnergyStats struct {
	Username      string
	TotalEnergyWh float64
	JobCount      int
	GPUHours      float64
	CPUHours      float64
}

// AggregateEnergyStats aggregates energy-history records into per-user energy
// statistics, sorted by total energy descending (ties broken by username for
// determinism). Ports UserOverviewTab.aggregate_energy_stats.
//
// For each record: parse elapsed -> seconds (skip if <= 0); CPU count from NCPUS
// with a TRES fallback; total GPUs from TRES (skipping generic "gpu" when a
// specific model is present) and the primary GPU model for the TDP lookup; then
// CalculateJobEnergyWh accumulated per user along with GPU/CPU hours.
func AggregateEnergyStats(records []slurm.EnergyRecord) []UserEnergyStats {
	type acc struct {
		totalWh  float64
		jobCount int
		gpuHours float64
		cpuHours float64
	}
	byUser := map[string]*acc{}

	for _, r := range records {
		username := strings.TrimSpace(r.User)
		if username == "" {
			continue
		}

		durationSeconds := slurm.ParseElapsedToSeconds(r.Elapsed)
		if durationSeconds <= 0 {
			continue
		}
		durationHours := durationSeconds / secondsPerHour

		cpuCount := 0
		if s := strings.TrimSpace(r.NCPUS); s != "" {
			if n, err := strconv.Atoi(s); err == nil {
				cpuCount = n
			}
		}
		tresStr := strings.TrimSpace(r.AllocTRES)
		if cpuCount == 0 && tresStr != "" {
			cpuCount = slurm.ParseCPUCountFromTRES(tresStr)
		}

		entries := slurm.ParseGPUEntries(tresStr)
		gpuCount := 0
		primaryGPUType := "gpu"
		hasSpecific := slurm.HasSpecificGPUTypes(entries)
		for _, e := range entries {
			if hasSpecific && strings.ToLower(e.Type) == "gpu" {
				continue
			}
			gpuCount += e.Count
			if strings.ToLower(e.Type) != "gpu" {
				primaryGPUType = e.Type
			}
		}

		energyWh := CalculateJobEnergyWh(gpuCount, primaryGPUType, cpuCount, durationSeconds)

		a := byUser[username]
		if a == nil {
			a = &acc{}
			byUser[username] = a
		}
		a.totalWh += energyWh
		a.jobCount++
		a.gpuHours += float64(gpuCount) * durationHours
		a.cpuHours += float64(cpuCount) * durationHours
	}

	out := make([]UserEnergyStats, 0, len(byUser))
	for username, a := range byUser {
		out = append(out, UserEnergyStats{
			Username:      username,
			TotalEnergyWh: a.totalWh,
			JobCount:      a.jobCount,
			GPUHours:      a.gpuHours,
			CPUHours:      a.cpuHours,
		})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].TotalEnergyWh != out[j].TotalEnergyWh {
			return out[i].TotalEnergyWh > out[j].TotalEnergyWh
		}
		return out[i].Username < out[j].Username
	})
	return out
}
