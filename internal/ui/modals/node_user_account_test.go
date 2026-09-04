package modals

import (
	"strings"
	"testing"
	"time"
	"unicode/utf8"

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
// aggregated user summary plus the user's fair-share standing (rank, status,
// usage vs share, recovery) and pending jobs with their queue positions and
// priority breakdown, all from already-fetched store data.
func TestUserDetailRendersFromStore(t *testing.T) {
	st := store.New()
	st.SetAllUsersJobs([]store.AllUsersJob{
		{ID: "1", Name: "a", User: "alice", State: "RUNNING", Time: "1:00", NumNodes: "1", NodeList: "n1", TRES: "cpu=4,mem=8G"},
		{ID: "2", Name: "b", User: "alice", State: "PENDING", NumNodes: "1", TRES: "cpu=2"},
	}, st.NextGen(store.SectionAllUsersJobs), nil)
	st.SetFairShare([]store.FairShareEntry{
		{Account: "physics", User: "", RawShares: "100", NormShares: "0.5", EffectvUsage: "0.5"},
		{Account: "physics", User: "alice", RawShares: "1", NormShares: "0.020833", EffectvUsage: "0.261082", FairShare: "0.065803"},
		{Account: "physics", User: "bob", RawShares: "1", NormShares: "0.1", EffectvUsage: "0.05", FairShare: "0.9"},
		{Account: "chem", User: "alice", RawShares: "1", NormShares: "0.1", EffectvUsage: "0", FairShare: "0.012"},
	}, st.NextGen(store.SectionFairShare), nil)
	st.SetPendingPrio([]store.PriorityEntry{
		{JobID: "2", User: "alice", Account: "physics", Partition: "gpu", Priority: 658139,
			Factors: store.PriorityFactors{FairShare: 658033, Partition: 100, JobSize: 5, Age: 1}},
		{JobID: "3", User: "bob", Account: "physics", Partition: "gpu", Priority: 900000,
			Factors: store.PriorityFactors{FairShare: 900000}},
	}, st.NextGen(store.SectionPendingPrio), nil)
	st.SetPriorityConfig(store.PriorityConfig{DecayHalfLife: 14 * 24 * time.Hour}, st.NextGen(store.SectionPriorityConfig), nil)

	d := NewUserDetail(st, testStyles(), "alice")
	d.SetSize(140, 80)
	view := d.View()
	if !strings.Contains(view, "User Summary") || !strings.Contains(view, "alice") {
		t.Errorf("user detail missing summary, got:\n%s", view)
	}
	if !strings.Contains(view, "Jobs by State") {
		t.Errorf("user detail missing jobs-by-state section, got:\n%s", view)
	}
	for _, want := range []string{
		"2 of 2 active users (bottom 1%)",
		"Heavily over-served",
		"12.5×",
		"2.08% of cluster (1 raw shares)",
		"26.1% of recent cluster usage",
		"≈51d idle to reach 1× (usage halves every 14d)",
		"chem (0.012)",
		"best at #2 of 2 · 1 ahead of you",
		"#2/2",
		"FairShare 658033 · Partition 100 · JobSize 5 · Age 1",
	} {
		if !strings.Contains(view, want) {
			t.Errorf("user detail missing %q, got:\n%s", want, view)
		}
	}
	if strings.Contains(view, "900000") {
		t.Errorf("user detail should not list other users' pending jobs, got:\n%s", view)
	}
}

// TestUserDetailWithoutPriorityConfigOmitsRecovery asserts the recovery estimate
// is withheld until the decay half-life is known, rather than showing a
// zero-based guess.
func TestUserDetailWithoutPriorityConfigOmitsRecovery(t *testing.T) {
	st := store.New()
	st.SetFairShare([]store.FairShareEntry{
		{Account: "physics", User: "alice", RawShares: "1", NormShares: "0.1", EffectvUsage: "0.4", FairShare: "0.1"},
	}, st.NextGen(store.SectionFairShare), nil)

	d := NewUserDetail(st, testStyles(), "alice")
	d.SetSize(140, 40)
	view := d.View()
	if !strings.Contains(view, "Heavily over-served") || !strings.Contains(view, "4.0×") {
		t.Errorf("user detail missing usage classification, got:\n%s", view)
	}
	if strings.Contains(view, "Recovery") {
		t.Errorf("user detail should omit recovery before the priority config loads, got:\n%s", view)
	}
}

// TestAccountDetailRendersFromStore asserts the account-detail modal renders the
// account summary, its fair-share standing among accounts, its users with their
// usage status, and only the account's own pending jobs with queue positions.
func TestAccountDetailRendersFromStore(t *testing.T) {
	st := store.New()
	st.SetFairShare([]store.FairShareEntry{
		{Account: "root", User: "", RawShares: "1", NormShares: "1", EffectvUsage: "1"},
		{Account: "physics", User: "", RawShares: "100", NormShares: "0.5", EffectvUsage: "0.75"},
		{Account: "physics", User: "alice", RawShares: "10", NormShares: "0.25", EffectvUsage: "0.75", FairShare: "0.4"},
		{Account: "physics", User: "carol", RawShares: "10", NormShares: "0.25", EffectvUsage: "0", FairShare: "1.0"},
		{Account: "chem", User: "", RawShares: "100", NormShares: "0.5", EffectvUsage: "0.25"},
		{Account: "chem", User: "bob", RawShares: "10", NormShares: "0.5", EffectvUsage: "0.25", FairShare: "0.9"},
	}, st.NextGen(store.SectionFairShare), nil)
	st.SetAllUsersJobs([]store.AllUsersJob{
		{ID: "1", Name: "a", User: "alice", Partition: "gpu", State: "RUNNING", Time: "1:00", NumNodes: "2", NodeList: "n[01-02]", TRES: "cpu=8,mem=16G,gres/gpu:a100=2"},
		{ID: "2", Name: "b", User: "alice", Partition: "gpu", State: "PENDING", NumNodes: "1", TRES: "cpu=4"},
	}, st.NextGen(store.SectionAllUsersJobs), nil)
	st.SetPendingPrio([]store.PriorityEntry{
		{JobID: "2", User: "alice", Account: "physics", Partition: "gpu", Priority: 5000, Factors: store.PriorityFactors{FairShare: 4000, Age: 1000}},
		{JobID: "99", User: "bob", Account: "chem", Partition: "cpu", Priority: 9000, Factors: store.PriorityFactors{FairShare: 9000}},
	}, st.NextGen(store.SectionPendingPrio), nil)

	d := NewAccountDetail(st, testStyles(), "physics")
	d.SetSize(140, 80)
	view := d.View()
	if !strings.Contains(view, "Account Summary") || !strings.Contains(view, "physics") {
		t.Errorf("account detail missing summary, got:\n%s", view)
	}
	if !strings.Contains(view, "Current Resource Usage") || !strings.Contains(view, "Total GPUs") || !strings.Contains(view, "Unique Nodes") {
		t.Errorf("account detail missing Current Resource Usage block, got:\n%s", view)
	}
	for _, want := range []string{
		"2 of 2 accounts (best-served first)",
		"Over-served",
		"1.5×",
		"50.0% of cluster (100 raw shares)",
		"Users in Account",
		"Unused",
		"3.0×",
		"Pending Job Priorities",
		"gpu",
		"#1/1",
		"FairShare 4000 · Age 1000",
	} {
		if !strings.Contains(view, want) {
			t.Errorf("account detail missing %q, got:\n%s", want, view)
		}
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

// TestTruncMeasuresCellsNotBytes asserts trunc cuts by display cells: a
// multi-byte name must survive un-mangled (no mid-rune cut) and double-width
// runes must count as two cells.
func TestTruncMeasuresCellsNotBytes(t *testing.T) {
	if got := trunc("ünïcödé", 5); got != "ünïcö" {
		t.Errorf("trunc(ünïcödé, 5) = %q, want %q", got, "ünïcö")
	}
	if got := trunc("日本語ジョブ", 4); got != "日本" {
		t.Errorf("trunc(日本語ジョブ, 4) = %q, want %q (2 double-width runes)", got, "日本")
	}
	if got := trunc("ascii", 10); got != "ascii" {
		t.Errorf("trunc(ascii, 10) = %q, want unchanged", got)
	}
	if !utf8.ValidString(trunc("ünïcödé", 3)) {
		t.Error("trunc produced invalid UTF-8")
	}
}
