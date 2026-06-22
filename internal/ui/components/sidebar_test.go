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
	stats := store.DeriveClusterStats(nodes, nil, nil)

	s := NewSidebar(styles())
	s.SetStats(stats, true)
	view := s.View()

	// The sidebar renders GPU types verbatim from CfgTRES (matching the Python
	// cluster_stats keys), so the lowercase "h200" from the TRES string is kept.
	for _, want := range []string{"Cluster Load", "Nodes:", "CPUs:", "Memory:", "GPUs:", "h200", "2/8"} {
		if !strings.Contains(view, want) {
			t.Errorf("sidebar missing %q; view:\n%s", want, view)
		}
	}
}

func TestSidebarRendersPendingAndWaitTime(t *testing.T) {
	all := []store.AllUsersJob{
		{ID: "5000", User: "bob", State: "PENDING", Partition: "gpu", TRES: "cpu=8,mem=16G,gres/gpu:a100=2"},
	}
	wait := []store.WaitTimeRecord{
		{JobID: "1", Partition: "gpu", State: "RUNNING", Submit: "2024-01-01T00:00:00", Start: "2024-01-01T00:05:00"},
	}
	nodes := []store.Node{
		{Name: "n1", State: "IDLE", CPUTot: "8", Fields: map[string]string{"NodeName": "n1"}},
	}
	stats := store.DeriveClusterStats(nodes, all, wait)

	s := NewSidebar(styles())
	s.SetStats(stats, true)
	view := s.View()

	if !strings.Contains(view, "Pending Queue") {
		t.Errorf("sidebar missing pending queue; view:\n%s", view)
	}
	if !strings.Contains(view, "gpu: 1 jobs") {
		t.Errorf("sidebar missing per-partition pending; view:\n%s", view)
	}
	if !strings.Contains(view, "Wait Times") {
		t.Errorf("sidebar missing wait times; view:\n%s", view)
	}
	// 5 minutes wait → "5m" mean/median.
	if !strings.Contains(view, "5m") {
		t.Errorf("sidebar missing wait-time value; view:\n%s", view)
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
