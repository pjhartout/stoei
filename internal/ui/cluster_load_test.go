package ui

import (
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
)

// TestClusterLoadModalOpensScrollable asserts the L key opens the cluster-load
// statistics as a modal showing the full content, dismissed with esc.
func TestClusterLoadModalOpensScrollable(t *testing.T) {
	fc := &store.FakeClient{UsernameStr: "alice", NodesData: []store.Node{
		{Name: "n1", State: "IDLE", CPUTot: "8", Fields: map[string]string{"NodeName": "n1"}},
	}}
	a := newTestApp(t, fc)
	a.availChecked = true
	a.width, a.height = 100, 24
	a.fanoutSize()
	m, _ := a.Update(nodesMsg{nodes: fc.NodesData, gen: a.store.Gen(store.SectionNodes)})
	a = m.(App)

	a = updateApp(a, tea.KeyPressMsg{Code: 'L', Text: "L"})
	if len(a.modals) != 1 {
		t.Fatalf("L should open a modal; have %d", len(a.modals))
	}
	v := a.View().Content
	for _, want := range []string{"Cluster Load", "Nodes:", "CPUs:"} {
		if !strings.Contains(v, want) {
			t.Errorf("cluster-load modal missing %q", want)
		}
	}

	a = updateApp(a, tea.KeyPressMsg{Code: tea.KeyEscape})
	if len(a.modals) != 0 {
		t.Errorf("esc should close the modal; have %d", len(a.modals))
	}
}
