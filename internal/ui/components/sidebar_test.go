package components

import (
	"strings"
	"testing"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

func styles() theme.Styles { return theme.BuildStyles(theme.Charm(), true) }

func TestSidebarRendersFreeAndGPUByType(t *testing.T) {
	nodes := []store.Node{
		{
			Name:      "gpu01",
			State:     "MIXED",
			CPUTot:    "64",
			CPUAlloc:  "16",
			RealMem:   "262144",
			AllocMem:  "65536",
			CfgTRES:   "cpu=64,mem=256G,gres/gpu:h200=8",
			AllocTRES: "cpu=16,gres/gpu:h200=2",
			Fields:    map[string]string{"NodeName": "gpu01"},
		},
	}
	stats := store.DeriveClusterStats(nodes, nil)

	s := NewSidebar(styles())
	s.SetStats(stats, true)
	view := s.View()

	// GPU type keys are upper-cased so the TRES and Gres-fallback paths share one
	// bucket, so the sidebar shows "H200" regardless of the TRES string's case.
	for _, want := range []string{"Cluster Load", "Nodes:", "CPUs:", "Memory:", "GPUs:", "H200", "2/8"} {
		if !strings.Contains(view, want) {
			t.Errorf("sidebar missing %q; view:\n%s", want, view)
		}
	}
}

func TestSidebarPendingQueueCompact(t *testing.T) {
	jobs := []store.AllUsersJob{
		{ID: "1", User: "a", Partition: "gpu", State: "PENDING", TRES: "cpu=4,mem=8G,gres/gpu:h200=2"},
	}
	stats := store.DeriveClusterStats(nil, jobs)
	s := NewSidebar(styles())
	s.SetStats(stats, true)
	view := s.View()

	for _, want := range []string{"Pending:", "gpu 1j", "4c", "2×H200"} {
		if !strings.Contains(view, want) {
			t.Errorf("sidebar missing %q; view:\n%s", want, view)
		}
	}
	// Compressed: the old nested "CPUs:"/"Memory:"/"GPUs:" sub-lines are gone.
	for _, gone := range []string{"    CPUs:", "    Memory:", "    GPUs:"} {
		if strings.Contains(view, gone) {
			t.Errorf("pending queue not compressed, found %q; view:\n%s", gone, view)
		}
	}
}

func TestSidebarRendersDrainingMIG(t *testing.T) {
	// A drained MIG node (like hpcl9101) shows its profiles on a separate draining
	// line with shortened labels, kept out of the schedulable totals.
	nodes := []store.Node{
		{
			Name:    "hpcl9101",
			State:   "IDLE+DRAIN",
			CPUTot:  "152",
			CfgTRES: "cpu=152,mem=1000000M,gres/gpu=22,gres/gpu:h100_pcie_1g.10gb=16,gres/gpu:h100_pcie_2g.20gb=6",
			Gres:    "gpu:h100_pcie_2g.20gb:6,gpu:h100_pcie_1g.10gb:16",
			Fields:  map[string]string{"NodeName": "hpcl9101"},
		},
	}
	stats := store.DeriveClusterStats(nodes, nil)
	s := NewSidebar(styles())
	s.SetStats(stats, true)
	view := s.View()

	for _, want := range []string{"GPUs:", "1g.10gb", "2g.20gb", "(drain)"} {
		if !strings.Contains(view, want) {
			t.Errorf("sidebar missing %q; view:\n%s", want, view)
		}
	}
}

func TestSidebarRendersPending(t *testing.T) {
	all := []store.AllUsersJob{
		{ID: "5000", User: "bob", State: "PENDING", Partition: "gpu", TRES: "cpu=8,mem=16G,gres/gpu:a100=2"},
	}
	nodes := []store.Node{
		{Name: "n1", State: "IDLE", CPUTot: "8", Fields: map[string]string{"NodeName": "n1"}},
	}
	stats := store.DeriveClusterStats(nodes, all)

	s := NewSidebar(styles())
	s.SetStats(stats, true)
	view := s.View()

	if !strings.Contains(view, "Pending:") {
		t.Errorf("sidebar missing pending queue; view:\n%s", view)
	}
	if !strings.Contains(view, "gpu 1j") {
		t.Errorf("sidebar missing per-partition pending; view:\n%s", view)
	}
}

func TestSidebarLoadingPlaceholder(t *testing.T) {
	s := NewSidebar(styles())
	if !strings.Contains(s.View(), "Loading cluster") {
		t.Errorf("unloaded sidebar should show placeholder; view:\n%s", s.View())
	}
}

func TestSidebarAutoHideThreshold(t *testing.T) {
	if ShouldShow(SidebarMinTermWidth - 1) {
		t.Errorf("sidebar should hide below %d", SidebarMinTermWidth)
	}
	if !ShouldShow(SidebarMinTermWidth) {
		t.Errorf("sidebar should show at %d", SidebarMinTermWidth)
	}
}
