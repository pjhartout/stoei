package slurm

import (
	"reflect"
	"testing"
)

func TestExpandNodeList(t *testing.T) {
	tests := []struct {
		name string
		in   string
		want []string
	}{
		{"plain", "node01", []string{"node01"}},
		// the headline edge case: a bracket range expands to each host.
		{"range", "node[02-03]", []string{"node02", "node03"}},
		{"range four", "node[01-04]", []string{"node01", "node02", "node03", "node04"}},
		{"bracket comma list", "node[01,03,05]", []string{"node01", "node03", "node05"}},
		{"mixed range and list", "node[01-03,07]", []string{"node01", "node02", "node03", "node07"}},
		{"plain comma", "node01,node02", []string{"node01", "node02"}},
		{"plain plus bracket", "node01,node[03-05]", []string{"node01", "node03", "node04", "node05"}},
		{"multiple groups", "gpu[01-02],cpu[01-02]", []string{"cpu01", "cpu02", "gpu01", "gpu02"}},
		{"zero padded", "node[001-003]", []string{"node001", "node002", "node003"}},
		{"single element", "node[05-05]", []string{"node05"}},
		{"unpadded", "node[8-10]", []string{"node10", "node8", "node9"}},
		{"empty", "", nil},
		{"whitespace only", "   ", nil},
		// pending-state placeholders expand to nothing.
		{"pending none", "(None)", nil},
		{"pending resources", "(Resources)", nil},
		{"pending priority", "(Priority)", nil},
		{"pending arbitrary paren", "(AssocMaxJobsLimit)", nil},
		{"truncated bracket", "node[01-", nil},
		{"overlapping dedup", "node[01-03],node[02-04]", []string{"node01", "node02", "node03", "node04"}},
		{"real cluster nodelist", "gpu-node-[11-13,15]", []string{"gpu-node-11", "gpu-node-12", "gpu-node-13", "gpu-node-15"}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ExpandNodeList(tt.in); !reflect.DeepEqual(got, tt.want) {
				t.Errorf("ExpandNodeList(%q) = %v, want %v", tt.in, got, tt.want)
			}
		})
	}
}

func TestCountNodes(t *testing.T) {
	tests := []struct {
		in   string
		want int
	}{
		{"gpu-node-[11-13,15]", 4},
		{"(None)", 0},
		{"node01,node[03-05]", 4},
		{"", 0},
	}
	for _, tt := range tests {
		if got := CountNodes(tt.in); got != tt.want {
			t.Errorf("CountNodes(%q) = %d, want %d", tt.in, got, tt.want)
		}
	}
}
