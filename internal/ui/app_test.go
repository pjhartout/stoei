package ui

import (
	"bytes"
	"errors"
	"testing"
	"time"

	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
	"github.com/charmbracelet/x/exp/teatest/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/modals"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// newTestApp builds a root model over a FakeClient seeded with jobs and a known
// username, with a fixed clock so LastUpdated is deterministic.
func newTestApp(t *testing.T, fc *store.FakeClient) App {
	t.Helper()
	st := store.New()
	st.SetClock(func() time.Time { return time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC) })
	a := New(st, fc)
	// Use a negligible tick interval so re-arm timer Cmds fire immediately when a
	// test drains them; the assertions only inspect the produced message types,
	// never real timing.
	a.intervals = Intervals{Fast: time.Nanosecond, Slow: time.Nanosecond}
	return a
}

// drainCmd runs a Cmd and returns the messages it produced. tea.Batch returns a
// BatchMsg whose children are themselves Cmds; we flatten one level, which is
// enough for the tick/dispatch batches asserted here.
func drainCmd(cmd tea.Cmd) []tea.Msg {
	if cmd == nil {
		return nil
	}
	msg := cmd()
	batch, ok := msg.(tea.BatchMsg)
	if !ok {
		return []tea.Msg{msg}
	}
	var out []tea.Msg
	for _, c := range batch {
		if c == nil {
			continue
		}
		out = append(out, c())
	}
	return out
}

// countTickMsgs counts how many fast and slow tick messages appear in msgs.
func countTickMsgs(msgs []tea.Msg) (fast, slow int) {
	for _, m := range msgs {
		switch m.(type) {
		case fastTickMsg:
			fast++
		case slowTickMsg:
			slow++
		}
	}
	return fast, slow
}

// TestFastTickReArmsOwnTierExactlyOnce asserts I2 for the fast tier: handling a
// fastTickMsg returns a batch that includes a running-jobs fetch and re-arms the
// fast tier exactly once, never the slow tier.
func TestFastTickReArmsOwnTierExactlyOnce(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})
	a.runningInFlight = false

	model, cmd := a.Update(fastTickMsg{at: time.Now()})
	if _, ok := model.(App); !ok {
		t.Fatalf("model type = %T; want App", model)
	}

	msgs := drainCmd(cmd)
	fast, slow := countTickMsgs(msgs)
	if fast != 1 {
		t.Errorf("fast re-arms = %d; want exactly 1", fast)
	}
	if slow != 0 {
		t.Errorf("slow re-arms = %d; want 0 (own tier only)", slow)
	}

	var sawRunningFetch bool
	for _, m := range msgs {
		if _, ok := m.(runningJobsMsg); ok {
			sawRunningFetch = true
		}
	}
	if !sawRunningFetch {
		t.Error("fast tick did not dispatch a running-jobs fetch")
	}
}

// TestFastTickReArmsButSkipsFetchWhenInFlight asserts that a fast tick with a
// running-jobs fetch already outstanding still re-arms the fast tier exactly once
// but does not dispatch a second fetch.
func TestFastTickReArmsButSkipsFetchWhenInFlight(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})
	a.runningInFlight = true

	_, cmd := a.Update(fastTickMsg{at: time.Now()})
	msgs := drainCmd(cmd)

	fast, slow := countTickMsgs(msgs)
	if fast != 1 || slow != 0 {
		t.Errorf("re-arms fast=%d slow=%d; want fast=1 slow=0", fast, slow)
	}
	for _, m := range msgs {
		if _, ok := m.(runningJobsMsg); ok {
			t.Error("dispatched a running-jobs fetch while one was in flight")
		}
	}
}

// TestSlowTickReArmsOwnTierExactlyOnce asserts I2 for the slow tier.
func TestSlowTickReArmsOwnTierExactlyOnce(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})
	a.heavyInFlight = false

	_, cmd := a.Update(slowTickMsg{at: time.Now()})
	msgs := drainCmd(cmd)

	fast, slow := countTickMsgs(msgs)
	if slow != 1 {
		t.Errorf("slow re-arms = %d; want exactly 1", slow)
	}
	if fast != 0 {
		t.Errorf("fast re-arms = %d; want 0 (own tier only)", fast)
	}
}

// TestHeavyGuardClearsOnlyAfterAllFetchesReturn asserts the in-flight guard is
// cleared only once every heavy fetch has returned — not when whichever finishes
// first does. Otherwise a slow tick would re-dispatch the heavy wave while fetches
// are still running.
func TestHeavyGuardClearsOnlyAfterAllFetchesReturn(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})
	a.heavyInFlight = true
	a.heavyPending = heavyFetchCount

	g := func(s store.Section) uint64 { return a.store.Gen(s) }
	// Three of four results arrive. The guard must stay set, so handleSlowTick
	// (which checks !heavyInFlight) cannot re-dispatch.
	partial := []tea.Msg{
		nodesMsg{gen: g(store.SectionNodes)},
		allUsersJobsMsg{gen: g(store.SectionAllUsersJobs)},
		fairShareMsg{gen: g(store.SectionFairShare)},
	}
	cur := a
	for _, msg := range partial {
		next, _ := cur.Update(msg)
		cur = next.(App)
	}
	if !cur.heavyInFlight {
		t.Fatal("heavyInFlight cleared after only 3/4 heavy results returned")
	}
	if cur.heavyPending != 1 {
		t.Fatalf("heavyPending = %d after 3 results; want 1", cur.heavyPending)
	}

	// The fourth result clears the guard.
	next, _ := cur.Update(pendingPrioMsg{gen: g(store.SectionPendingPrio)})
	if next.(App).heavyInFlight {
		t.Error("heavyInFlight still set after all 4 heavy results returned")
	}
}

// TestUnavailableScreenRendered asserts that an unavailable client makes the
// model render the full-screen unavailable screen rather than the tab bar.
func TestUnavailableScreenRendered(t *testing.T) {
	fc := &store.FakeClient{AvailableErr: errors.New("squeue not found on PATH")}
	a := newTestApp(t, fc)
	a.width, a.height = 80, 24

	model, _ := a.Update(availabilityMsg{err: fc.AvailableErr})
	out := model.(App).View().Content

	if !bytes.Contains([]byte(out), []byte("SLURM unavailable")) {
		t.Errorf("expected unavailable screen, got:\n%s", out)
	}
	if !bytes.Contains([]byte(out), []byte("squeue not found on PATH")) {
		t.Errorf("expected the availability error text, got:\n%s", out)
	}
}

// TestModalStackPushPop exercises the modal stack helpers and that a non-empty
// stack composites over the base.
func TestModalStackPushPop(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})
	a.width, a.height = 80, 24

	if len(a.modals) != 0 {
		t.Fatalf("new model has %d modals; want 0", len(a.modals))
	}
	a.pushModal(&fakeModal{body: "MODAL-BODY"})
	if len(a.modals) != 1 {
		t.Fatalf("after push: %d modals; want 1", len(a.modals))
	}

	out := a.View().Content
	if !bytes.Contains([]byte(out), []byte("MODAL-BODY")) {
		t.Errorf("modal not composited over base, got:\n%s", out)
	}

	a.popModal()
	if len(a.modals) != 0 {
		t.Fatalf("after pop: %d modals; want 0", len(a.modals))
	}
}

// fakeModal is a minimal modals.Modal used to exercise the modal stack.
type fakeModal struct{ body string }

func (m *fakeModal) Init() tea.Cmd                                  { return nil }
func (m *fakeModal) Update(_ tea.Msg) (modals.Modal, tea.Cmd, bool) { return m, nil, false }
func (m *fakeModal) View() string                                   { return m.body }
func (m *fakeModal) SetSize(_, _ int)                               {}
func (m *fakeModal) SetStyles(_ theme.Styles)                       {}
func (m *fakeModal) ShortHelp() []key.Binding                       { return nil }
func (m *fakeModal) FullHelp() [][]key.Binding                      { return nil }

// TestSidebarShownWhenWideHiddenWhenNarrow asserts the cluster sidebar is
// composed beside the tab on a wide terminal and auto-hidden on a narrow one.
func TestSidebarShownWhenWideHiddenWhenNarrow(t *testing.T) {
	fc := &store.FakeClient{
		UsernameStr: "alice",
		NodesData: []store.Node{
			{Name: "n1", State: "IDLE", CPUTot: "8", Fields: map[string]string{"NodeName": "n1"}},
		},
	}
	a := newTestApp(t, fc)

	// Wide: feed nodes so the sidebar has loaded data, then render at width 120.
	a.width, a.height = 120, 30
	a.fanoutSize()
	model, _ := a.Update(nodesMsg{nodes: fc.NodesData, gen: a.store.Gen(store.SectionNodes)})
	wide := model.(App)
	if !bytes.Contains([]byte(wide.View().Content), []byte("Cluster Load")) {
		t.Errorf("wide terminal should show the cluster sidebar")
	}

	// Narrow: below the threshold the sidebar is hidden.
	narrow := wide
	narrow.width, narrow.height = 80, 30
	narrow.fanoutSize()
	narrow.frame.dirty = true
	if bytes.Contains([]byte(narrow.View().Content), []byte("Cluster Load")) {
		t.Errorf("narrow terminal should auto-hide the cluster sidebar")
	}
}

// TestHistoryErrorTransitionEmitsOneToast asserts the edge-triggered behavior
// (I9): a repeat history failure does not stack a second toast, and a generic
// history error still surfaces some toast.
func TestHistoryErrorTransitionEmitsOneToast(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{UsernameStr: "alice"})
	a.width, a.height = 100, 30
	a.fanoutSize()

	histErr := errors.New("history fetch failed")
	m1, _ := a.Update(historyMsg{gen: a.store.Gen(store.SectionHistory), err: histErr})
	a1 := m1.(App)
	if len(a1.toasts) != 1 {
		t.Fatalf("after first failure: %d toasts, want 1", len(a1.toasts))
	}
	m2, _ := a1.Update(historyMsg{gen: a1.store.Gen(store.SectionHistory), err: histErr})
	a2 := m2.(App)
	if len(a2.toasts) != 1 {
		t.Errorf("after repeat failure: %d toasts, want 1 (edge-triggered, no spam)", len(a2.toasts))
	}
}

// TestTeatestTabNavigation drives the real loop and steps through tabs 1→5,
// asserting each renders its distinctive content.
func TestTeatestTabNavigation(t *testing.T) {
	fc := &store.FakeClient{
		UsernameStr: "alice",
		RunningJobsData: []store.RunningJob{
			{ID: "1001", Name: "train", State: "RUNNING", Time: "1:00", Nodes: "1", NodeList: "node01"},
		},
		NodesData: []store.Node{
			{Name: "node01", State: "MIXED", CPUTot: "64", CPUAlloc: "16", Fields: map[string]string{"NodeName": "node01"}},
		},
		AllUsersJobsData: []store.AllUsersJob{
			{ID: "1001", User: "alice", State: "RUNNING", NumNodes: "1", NodeList: "node01", TRES: "cpu=16,mem=32G"},
		},
		FairShareData: []store.FairShareEntry{
			{Account: "physics", User: "alice", FairShare: "0.80"},
		},
	}
	st := store.New()
	st.SetClock(func() time.Time { return time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC) })
	st.SetRunningJobs(fc.RunningJobsData, st.NextGen(store.SectionRunningJobs), nil)
	st.SetNodes(fc.NodesData, st.NextGen(store.SectionNodes), nil)
	st.SetAllUsersJobs(fc.AllUsersJobsData, st.NextGen(store.SectionAllUsersJobs), nil)
	st.SetFairShare(fc.FairShareData, st.NextGen(store.SectionFairShare), nil)

	// Narrow width so the sidebar is hidden and tab bodies fill the frame.
	tm := teatest.NewTestModel(t, New(st, fc), teatest.WithInitialTermSize(90, 30))

	steps := []struct {
		key  rune
		want string
	}{
		{'2', "Node"},          // Nodes tab header/columns
		{'3', "User Overview"}, // Users tab sub-tab header
		{'4', "Priority"},      // Priority tab header
		{'5', "log"},           // Logs tab placeholder ("No log entries yet.")
		{'1', "My Usage"},      // back to Jobs
	}
	for _, s := range steps {
		tm.Send(tea.KeyPressMsg{Code: s.key, Text: string(s.key)})
		want := s.want
		teatest.WaitFor(t, tm.Output(), func(out []byte) bool {
			return bytes.Contains(out, []byte(want))
		}, teatest.WithDuration(3*time.Second), teatest.WithCheckInterval(10*time.Millisecond))
	}

	tm.Send(tea.KeyPressMsg{Code: 'q', Text: "q"})
	tm.WaitFinished(t, teatest.WithFinalTimeout(3*time.Second))
}

// TestTeatestJobsFlow drives the real program loop with teatest: jobs render
// from the seeded store, "/" opens the filter and narrows the view, and "q"
// quits. This is the single end-to-end smoke flow for Phase 3.
func TestTeatestJobsFlow(t *testing.T) {
	fc := &store.FakeClient{
		UsernameStr: "alice",
		RunningJobsData: []store.RunningJob{
			{ID: "1001", Name: "train", State: "RUNNING", Time: "1:00", Nodes: "1", NodeList: "node01"},
			{ID: "1002", Name: "eval", State: "PENDING", Time: "0:00", Nodes: "2", NodeList: ""},
		},
	}
	st := store.New()
	st.SetClock(func() time.Time { return time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC) })
	st.SetRunningJobs(fc.RunningJobsData, st.NextGen(store.SectionRunningJobs), nil)

	tm := teatest.NewTestModel(t, New(st, fc), teatest.WithInitialTermSize(100, 30))

	// Jobs render from the seeded store: both rows and the My-Usage banner appear.
	teatest.WaitFor(t, tm.Output(), func(out []byte) bool {
		return bytes.Contains(out, []byte("train")) &&
			bytes.Contains(out, []byte("eval")) &&
			bytes.Contains(out, []byte("My Usage"))
	}, teatest.WithDuration(3*time.Second), teatest.WithCheckInterval(10*time.Millisecond))

	// Drive the filter through a full open → type → close cycle, then quit. The
	// per-keystroke filter rendering is asserted in the unit tests (the diff-based
	// terminal stream splits styled prompt/cell text across cursor moves, so it is
	// not byte-stable here); this leg only proves the real loop processes the input
	// sequence and exits cleanly.
	tm.Send(tea.KeyPressMsg{Code: '/', Text: "/"})
	for _, r := range "state" {
		tm.Send(tea.KeyPressMsg{Code: r, Text: string(r)})
	}
	tm.Send(tea.KeyPressMsg{Code: tea.KeyEnter})
	tm.Send(tea.KeyPressMsg{Code: 'q', Text: "q"})
	tm.WaitFinished(t, teatest.WithFinalTimeout(5*time.Second))
}
