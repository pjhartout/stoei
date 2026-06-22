package store

import (
	"bytes"
	_ "embed"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/pjhartout/stoei/internal/slurm"
)

// tdpValuesJSON is the embedded copy of the TDP lookup table. Keeping a copy in
// the package keeps the binary self-contained and the derive logic pure.
//
//go:embed tdp_values.json
var tdpValuesJSON []byte

// Fallback TDP values, used if the embedded JSON cannot be parsed.
const (
	fallbackDefaultGPUTDP = 300
	fallbackCPUTDPPerCore = 10
)

// secondsPerHour is the conversion factor used by the energy calculations.
const secondsPerHour = 3600.0

// Energy unit thresholds in Watt-hours, at or above which FormatEnergy scales the
// value into GWh / MWh / kWh respectively.
const (
	energyGWhThreshold = 1_000_000_000.0
	energyMWhThreshold = 1_000_000.0
	energyKWhThreshold = 1000.0
)

// tdpTable holds the parsed TDP lookup data. It is computed once at package init
// from the embedded JSON.
type tdpTable struct {
	gpu           map[string]int // upper-cased GPU model -> TDP in Watts
	defaultGPU    int
	cpuPerCore    int
	orderedModels []string // gpu keys in JSON declaration order, for partial matching
}

// tdp is the package-level parsed TDP table. It is read-only after init.
var tdp = loadTDP()

// loadTDP parses the embedded tdp_values.json into a tdpTable, falling back to
// the constant defaults on any error.
func loadTDP() tdpTable {
	t := tdpTable{
		gpu:        map[string]int{},
		defaultGPU: fallbackDefaultGPUTDP,
		cpuPerCore: fallbackCPUTDPPerCore,
	}

	for _, top := range orderedObject(tdpValuesJSON) {
		switch top.key {
		case "gpu":
			parseGPUSection(top.val, &t)
		case "cpu":
			for _, e := range orderedObject(top.val) {
				if e.key == "_default_per_core" {
					if v, ok := intValue(e.val); ok {
						t.cpuPerCore = v
					}
				}
			}
		}
	}

	return t
}

// orderedKV is one key/value pair preserving JSON declaration order.
type orderedKV struct {
	key string
	val json.RawMessage
}

// orderedObject decodes a JSON object preserving the declaration order of its
// keys (a map would randomize them). It returns nil for non-objects or on error.
func orderedObject(data []byte) []orderedKV {
	dec := json.NewDecoder(bytes.NewReader(data))
	tok, err := dec.Token()
	if err != nil {
		return nil
	}
	if d, ok := tok.(json.Delim); !ok || d != '{' {
		return nil
	}
	var out []orderedKV
	for dec.More() {
		keyTok, err := dec.Token()
		if err != nil {
			return nil
		}
		key, _ := keyTok.(string)
		var raw json.RawMessage
		if err := dec.Decode(&raw); err != nil {
			return nil
		}
		out = append(out, orderedKV{key: key, val: raw})
	}
	return out
}

// parseGPUSection flattens the (possibly nested) GPU section into t.gpu and reads
// the _default value, preserving JSON declaration order in t.orderedModels so the
// partial-substring scan in GetGPUTDP tries a more specific model before a shorter
// substring (e.g. A100 before A10).
func parseGPUSection(gpuRaw json.RawMessage, t *tdpTable) {
	for _, e := range orderedObject(gpuRaw) {
		if e.key == "_default" {
			if v, ok := intValue(e.val); ok {
				t.defaultGPU = v
			}
			continue
		}
		if strings.HasPrefix(e.key, "_") {
			continue
		}
		// Direct model -> TDP mapping.
		if v, ok := intValue(e.val); ok {
			t.addModel(e.key, v)
			continue
		}
		// Category dict of model -> TDP, in declaration order.
		for _, m := range orderedObject(e.val) {
			if v, ok := intValue(m.val); ok {
				t.addModel(m.key, v)
			}
		}
	}
}

// addModel records a model->TDP entry, appending the upper-cased key to
// orderedModels the first time it is seen so the partial scan honors JSON order.
func (t *tdpTable) addModel(model string, tdpW int) {
	key := strings.ToUpper(model)
	if _, exists := t.gpu[key]; !exists {
		t.orderedModels = append(t.orderedModels, key)
	}
	t.gpu[key] = tdpW
}

// intValue reports the integer value of a JSON number that is an exact integer.
// Floats and non-numbers return ok=false, so only whole-Watt TDP entries are
// accepted.
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

// GetGPUTDP returns the TDP in Watts for a GPU type, resolved in order: exact
// (case-insensitive) match, then vendor-prefix-stripped match, then a partial
// substring match, then the default. The partial match scans models in JSON
// declaration order, so a more specific model like A100 is tried before a shorter
// substring like A10.
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

	for _, model := range tdp.orderedModels {
		if strings.Contains(normalized, model) || strings.Contains(model, normalized) {
			return tdp.gpu[model]
		}
	}

	return tdp.defaultGPU
}

// CPUTDPPerCore returns the per-core CPU TDP in Watts.
func CPUTDPPerCore() int { return tdp.cpuPerCore }

// CalculateJobEnergyWh estimates a job's energy use in Watt-hours assuming 100%
// utilization for the whole duration. A non-positive duration yields 0.
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

// FormatEnergy renders a Watt-hour value with auto-scaling units (Wh / kWh / MWh /
// GWh). Each tier has its own precision (two decimals for GWh and MWh, one for
// kWh, none for whole Wh and two for sub-Wh values), and negatives clamp to
// "0 Wh".
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

// UserEnergyStats is per-user energy usage over a historical period.
type UserEnergyStats struct {
	Username      string
	TotalEnergyWh float64
	JobCount      int
	GPUHours      float64
	CPUHours      float64
}

// AggregateEnergyStats aggregates energy-history records into per-user energy
// statistics, sorted by total energy descending (ties broken by username for
// determinism).
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
