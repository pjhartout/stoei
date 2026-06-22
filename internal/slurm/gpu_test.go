package slurm

import (
	"reflect"
	"testing"
)

func TestParseGPUEntries(t *testing.T) {
	tests := []struct {
		name string
		in   string
		want []GPUEntry
	}{
		{"empty", "", nil},
		{"no gpus", "cpu=32,mem=256G,node=4", nil},
		{"generic", "cpu=32,mem=256G,gres/gpu=8", []GPUEntry{{"gpu", 8}}},
		{"typed", "cpu=32,mem=256G,gres/gpu:h200=8", []GPUEntry{{"h200", 8}}},
		{"multiple types", "gres/gpu:a100=4,gres/gpu:v100=2", []GPUEntry{{"a100", 4}, {"v100", 2}}},
		// generic AND typed both appear: parse keeps both; de-dup happens in aggregate.
		{"generic and typed", "gres/gpu=8,gres/gpu:h200=8", []GPUEntry{{"gpu", 8}, {"h200", 8}}},
		{"case insensitive keeps case", "GRES/GPU:H200=4", []GPUEntry{{"H200", 4}}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ParseGPUEntries(tt.in); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ParseGPUEntries(%q) = %v, want %v", tt.in, got, tt.want)
			}
		})
	}
}

func TestParseGPUFromGres(t *testing.T) {
	tests := []struct {
		name string
		in   string
		want []GPUEntry
	}{
		{"empty", "", nil},
		{"no gpu", "scratch:1T", nil},
		{"simple count", "gpu:4", []GPUEntry{{"GPU", 4}}},
		{"typed", "gpu:a100:4", []GPUEntry{{"A100", 4}}},
		{"socket info stripped", "gpu:h200:8(S:0-1)", []GPUEntry{{"H200", 8}}},
		{"multiple", "gpu:a100:4,gpu:v100:2", []GPUEntry{{"A100", 4}, {"V100", 2}}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ParseGPUFromGres(tt.in); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ParseGPUFromGres(%q) = %v, want %v", tt.in, got, tt.want)
			}
		})
	}
}

func TestHasSpecificGPUTypes(t *testing.T) {
	tests := []struct {
		name string
		in   []GPUEntry
		want bool
	}{
		{"empty", nil, false},
		{"only generic", []GPUEntry{{"gpu", 8}}, false},
		{"only specific", []GPUEntry{{"h200", 8}}, true},
		{"mixed", []GPUEntry{{"gpu", 8}, {"h200", 8}}, true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := HasSpecificGPUTypes(tt.in); got != tt.want {
				t.Errorf("HasSpecificGPUTypes(%v) = %v, want %v", tt.in, got, tt.want)
			}
		})
	}
}

func TestAggregateGPUCounts(t *testing.T) {
	tests := []struct {
		name string
		in   []GPUEntry
		skip bool
		want map[string]int
	}{
		{"empty", nil, true, map[string]int{}},
		{"single", []GPUEntry{{"h200", 8}}, true, map[string]int{"H200": 8}},
		{"same type summed", []GPUEntry{{"h200", 4}, {"h200", 4}}, true, map[string]int{"H200": 8}},
		// the costly double-count case: generic dropped when a specific model exists.
		{"skip generic when specific", []GPUEntry{{"gpu", 8}, {"h200", 8}}, true, map[string]int{"H200": 8}},
		{"keep generic when alone", []GPUEntry{{"gpu", 8}}, true, map[string]int{"GPU": 8}},
		{"no skip when disabled", []GPUEntry{{"gpu", 8}, {"h200", 8}}, false, map[string]int{"GPU": 8, "H200": 8}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := AggregateGPUCounts(tt.in, tt.skip); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("AggregateGPUCounts(%v, %v) = %v, want %v", tt.in, tt.skip, got, tt.want)
			}
		})
	}
}

func TestCalculateTotalGPUs(t *testing.T) {
	tests := []struct {
		name string
		in   []GPUEntry
		want int
	}{
		{"empty", nil, 0},
		{"single", []GPUEntry{{"h200", 8}}, 8},
		{"multiple", []GPUEntry{{"a100", 4}, {"v100", 2}}, 6},
		// generic must not be double-counted against the specific entry.
		{"no double count", []GPUEntry{{"gpu", 8}, {"h200", 8}}, 8},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := CalculateTotalGPUs(tt.in, true); got != tt.want {
				t.Errorf("CalculateTotalGPUs(%v) = %d, want %d", tt.in, got, tt.want)
			}
		})
	}
}

func TestFormatGPUTypes(t *testing.T) {
	tests := []struct {
		name string
		in   map[string]int
		want string
	}{
		{"empty", map[string]int{}, ""},
		{"single", map[string]int{"H200": 8}, "8x H200"},
		{"sorted", map[string]int{"V100": 2, "A100": 4}, "4x A100, 2x V100"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := FormatGPUTypes(tt.in); got != tt.want {
				t.Errorf("FormatGPUTypes(%v) = %q, want %q", tt.in, got, tt.want)
			}
		})
	}
}

func TestParseTRESResources(t *testing.T) {
	tests := []struct {
		name    string
		in      string
		cpus    int
		mem     float64
		gpuTotl int
	}{
		{"full gpu", "cpu=32,mem=256G,node=4,gres/gpu=16", 32, 256, 16},
		{"typed gpu", "cpu=4,mem=16G,gres/gpu:h200=2", 4, 16, 2},
		{"mem megabytes", "mem=512M", 0, 512.0 / 1024.0, 0},
		{"mem terabytes", "mem=2T", 0, 2048, 0},
		{"empty", "", 0, 0, 0},
		// generic + specific in one TRES string: total must not double-count.
		{"no double count", "cpu=768,mem=8000G,gres/gpu=32,gres/gpu:h200=4", 768, 8000, 4},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := ParseTRESResources(tt.in)
			if r.CPUs != tt.cpus {
				t.Errorf("CPUs = %d, want %d", r.CPUs, tt.cpus)
			}
			if r.MemoryGB != tt.mem {
				t.Errorf("MemoryGB = %v, want %v", r.MemoryGB, tt.mem)
			}
			if got := CalculateTotalGPUs(r.GPUs, true); got != tt.gpuTotl {
				t.Errorf("total GPUs = %d, want %d", got, tt.gpuTotl)
			}
		})
	}
}

func TestParseCPUCountFromTRES(t *testing.T) {
	tests := []struct {
		in   string
		want int
	}{
		{"cpu=32,mem=256G", 32},
		{"mem=256G", 0},
		{"", 0},
	}
	for _, tt := range tests {
		if got := ParseCPUCountFromTRES(tt.in); got != tt.want {
			t.Errorf("ParseCPUCountFromTRES(%q) = %d, want %d", tt.in, got, tt.want)
		}
	}
}
