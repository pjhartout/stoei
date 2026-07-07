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
	st := store.New()
	st.SetAllUsersJobs([]store.AllUsersJob{
		{ID: "42", Name: "train", User: "bob", State: "RUNNING", Time: "1:23:00", NodeList: "node01", TRES: "cpu=8,mem=16G,gres/gpu:a100=2"},
		{ID: "43", Name: "idle", User: "carol", State: "RUNNING", Time: "0:05", NodeList: "node99", TRES: "cpu=1"},
	}, st.NextGen(store.SectionAllUsersJobs), nil)

	n := NewNodeDetail(fc, st, testStyles(), "node01")
	n.SetSize(80, 24)

	cmd := n.Init()
	if cmd == nil {
		t.Fatal("Init must issue a fetch Cmd")
	}
	n.Update(firstMsg(cmd))
	if fc.LastNodeDetailName != "node01" {
		t.Errorf("NodeDetail called with %q; want node01", fc.LastNodeDetailName)
	}
	view := n.View()
	if !strings.Contains(view, "node01") || !strings.Contains(view, "IDLE") {
		t.Errorf("node detail did not render fields, got:\n%s", view)
	}
	if !strings.Contains(view, "Jobs on Node") || !strings.Contains(view, "bob") {
		t.Errorf("node detail missing Jobs on Node section for the node's occupant, got:\n%s", view)
	}
	if strings.Contains(view, "carol") {
		t.Errorf("node detail should exclude jobs on other nodes, got:\n%s", view)
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
	st.SetAllUsersJobs([]store.AllUsersJob{
		{ID: "1", Name: "a", User: "alice", Partition: "gpu", State: "RUNNING", Time: "1:00", NumNodes: "2", NodeList: "n[01-02]", TRES: "cpu=8,mem=16G,gres/gpu:a100=2"},
		{ID: "2", Name: "b", User: "alice", Partition: "gpu", State: "PENDING", NumNodes: "1", TRES: "cpu=4"},
	}, st.NextGen(store.SectionAllUsersJobs), nil)
	st.SetPendingPrio([]store.PriorityEntry{
		{JobID: "2", User: "alice", Priority: "5000", Age: "10", FairShare: "0.4", Partition: "gpu"},
		{JobID: "99", User: "bob", Priority: "9000", Partition: "cpu"}, // not in account: excluded
	}, st.NextGen(store.SectionPendingPrio), nil)

	d := NewAccountDetail(st, testStyles(), "physics")
	d.SetSize(120, 40)
	view := d.View()
	if !strings.Contains(view, "Account Summary") || !strings.Contains(view, "physics") {
		t.Errorf("account detail missing summary, got:\n%s", view)
	}
	if !strings.Contains(view, "Users in Account") {
		t.Errorf("account detail missing users section, got:\n%s", view)
	}
	// Current Resource Usage aggregate block (formatters.py 888-916).
	if !strings.Contains(view, "Current Resource Usage") {
		t.Errorf("account detail missing Current Resource Usage block, got:\n%s", view)
	}
	if !strings.Contains(view, "Total GPUs") || !strings.Contains(view, "Unique Nodes") {
		t.Errorf("account detail Current Resource Usage missing fields, got:\n%s", view)
	}
	// Account-level Pending Job Priorities block (formatters.py 953-983), showing
	// the account's pending job and excluding bob's out-of-account job.
	if !strings.Contains(view, "Pending Job Priorities") {
		t.Errorf("account detail missing Pending Job Priorities block, got:\n%s", view)
	}
	if strings.Contains(view, "9000") {
		t.Errorf("account detail should exclude out-of-account pending priority, got:\n%s", view)
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
