package tabs

import (
	"strings"
	"testing"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// seedNodes builds a Nodes tab over a store seeded with the given nodes.
func seedNodes(t *testing.T, nodes []store.Node) *Nodes {
	t.Helper()
	st := store.New()
	st.SetNodes(nodes, st.NextGen(store.SectionNodes), nil)
	n := NewNodes(st, theme.BuildStyles(theme.Charm(), true))
	n.SetSize(120, 30)
	return n
}

func TestNodesRendersCPUAndGPU(t *testing.T) {
	nodes := []store.Node{
		{
			Name:      "gpu01",
			State:     "MIXED",
			CPUTot:    "64",
			CPUAlloc:  "16",
			RealMem:   "262144",
			AllocMem:  "131072",
			CfgTRES:   "cpu=64,mem=256G,gres/gpu:h200=8",
			AllocTRES: "cpu=16,gres/gpu:h200=2",
			Fields:    map[string]string{"Partitions": "gpu", "NodeName": "gpu01"},
		},
	}
	n := seedNodes(t, nodes)
	view := n.View()

	for _, want := range []string{"gpu01", "16/64", "25.0%", "128.0/256.0 GB", "2/8", "8x H200", "gpu"} {
		if !strings.Contains(view, want) {
			t.Errorf("node view missing %q; view:\n%s", want, view)
		}
	}
}

func TestNodesGPULessShowsNA(t *testing.T) {
	nodes := []store.Node{
		{Name: "cpu01", State: "IDLE", CPUTot: "32", CPUAlloc: "0", Fields: map[string]string{"NodeName": "cpu01"}},
	}
	n := seedNodes(t, nodes)
	view := n.View()
	if !strings.Contains(view, "cpu01") {
		t.Fatalf("missing node row; view:\n%s", view)
	}
	if !strings.Contains(view, "N/A") {
		t.Errorf("GPU-less node should show N/A; view:\n%s", view)
	}
}

func TestNodesFilterByState(t *testing.T) {
	nodes := []store.Node{
		{Name: "n1", State: "IDLE", CPUTot: "8", Fields: map[string]string{"NodeName": "n1"}},
		{Name: "n2", State: "DOWN", CPUTot: "8", Fields: map[string]string{"NodeName": "n2"}},
	}
	n := seedNodes(t, nodes)
	n.tbl.filterState = parseFilterWith("state:idle", nodeColumns)
	n.tbl.rebuild()

	view := n.View()
	if !strings.Contains(view, "n1") {
		t.Errorf("idle node missing after filter; view:\n%s", view)
	}
	if strings.Contains(view, "n2") {
		t.Errorf("down node should be filtered out; view:\n%s", view)
	}
}
