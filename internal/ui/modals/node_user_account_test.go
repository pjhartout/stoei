package modals

import (
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
)

// TestNodeDetailFetchesAndRenders asserts the node-detail modal fetches via Cmd
// and renders the scontrol fields.
func TestNodeDetailFetchesAndRenders(t *testing.T) {
	fc := &store.FakeClient{
		NodeDetailData: store.JobDetail{
			Source: "scontrol",
			Fields: map[string]string{"NodeName": "node01", "State": "IDLE", "CPUTot": "64"},
		},
	}
	n := NewNodeDetail(fc, testStyles(), "node01")
	n.SetSize(80, 24)

	cmd := n.Init()
	if cmd == nil {
		t.Fatal("Init must issue a fetch Cmd")
	}
	n.Update(firstMsg(cmd))
	if fc.LastNodeDetailName != "node01" {
		t.Errorf("NodeDetail called with %q; want node01", fc.LastNodeDetailName)
	}
	if !strings.Contains(n.View(), "node01") || !strings.Contains(n.View(), "IDLE") {
		t.Errorf("node detail did not render fields, got:\n%s", n.View())
	}
}

// TestUserDetailRendersFromStore asserts the user-detail modal renders an
// aggregated user summary from already-fetched store data.
func TestUserDetailRendersFromStore(t *testing.T) {
	st := store.New()
	st.SetAllUsersJobs([]store.AllUsersJob{
		{ID: "1", Name: "a", User: "alice", State: "RUNNING", Time: "1:00", NumNodes: "1", NodeList: "n1", TRES: "cpu=4,mem=8G"},
		{ID: "2", Name: "b", User: "alice", State: "PENDING", NumNodes: "1", TRES: "cpu=2"},
	}, st.NextGen(store.SectionAllUsersJobs), nil)

	d := NewUserDetail(st, testStyles(), "alice")
	d.SetSize(100, 30)
	view := d.View()
	if !strings.Contains(view, "User Summary") || !strings.Contains(view, "alice") {
		t.Errorf("user detail missing summary, got:\n%s", view)
	}
	if !strings.Contains(view, "Jobs by State") {
		t.Errorf("user detail missing jobs-by-state section, got:\n%s", view)
	}
}

// TestAccountDetailRendersFromStore asserts the account-detail modal renders the
// account summary and its users from store fair-share data.
func TestAccountDetailRendersFromStore(t *testing.T) {
	st := store.New()
	st.SetFairShare([]store.FairShareEntry{
		{Account: "physics", User: "", RawShares: "100", FairShare: "0.6"},
		{Account: "physics", User: "alice", RawShares: "10", FairShare: "0.4"},
	}, st.NextGen(store.SectionFairShare), nil)

	d := NewAccountDetail(st, testStyles(), "physics")
	d.SetSize(100, 30)
	view := d.View()
	if !strings.Contains(view, "Account Summary") || !strings.Contains(view, "physics") {
		t.Errorf("account detail missing summary, got:\n%s", view)
	}
	if !strings.Contains(view, "Users in Account") {
		t.Errorf("account detail missing users section, got:\n%s", view)
	}
}

// TestInfoDetailEscCloses asserts the generic info modals close on esc.
func TestInfoDetailEscCloses(t *testing.T) {
	st := store.New()
	d := NewUserDetail(st, testStyles(), "alice")
	d.SetSize(100, 30)
	_, _, done := d.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
	if !done {
		t.Error("esc should close the info detail modal")
	}
}
