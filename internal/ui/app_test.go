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

// TestDispatchHeavyVisibleByTab pins the visibility predicate: nodes and all-users
// are always polled (they feed the sidebar / 'L' modal / banners), while
// fair-share and pending-priority are polled only while the Priority or Users tab
// is active.
func TestDispatchHeavyVisibleByTab(t *testing.T) {
	cases := []struct {
		name   string
		active tabIndex
		want   map[string]bool
	}{
		{"jobs", tabJobs, map[string]bool{"nodes": true, "allusers": true}},
		{"nodes", tabNodes, map[string]bool{"nodes": true, "allusers": true}},
		{"logs", tabLogs, map[string]bool{"nodes": true, "allusers": true}},
		{"priority", tabPriority, map[string]bool{"nodes": true, "allusers": true, "fairshare": true, "pendingprio": true}},
		{"users", tabUsers, map[string]bool{"nodes": true, "allusers": true, "fairshare": true, "pendingprio": true}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			a := newTestApp(t, &store.FakeClient{})
			a.active = tc.active
			got := map[string]bool{}
			for _, msg := range drainCmd(a.dispatchHeavyVisible()) {
				switch msg.(type) {
				case nodesMsg:
					got["nodes"] = true
				case allUsersJobsMsg:
					got["allusers"] = true
				case fairShareMsg:
					got["fairshare"] = true
				case pendingPrioMsg:
					got["pendingprio"] = true
				}
			}
			for _, s := range []string{"nodes", "allusers", "fairshare", "pendingprio"} {
				if got[s] != tc.want[s] {
					t.Errorf("section %q dispatched=%v, want=%v", s, got[s], tc.want[s])
				}
			}
		})
	}
}

// TestHeavySectionGuardSkipsWhileLoading asserts a needed section already loading
// is not re-dispatched (the per-section replacement for the old monolithic guard).
func TestHeavySectionGuardSkipsWhileLoading(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})

	gNodes := a.store.NextGen(store.SectionNodes)
	a.store.SetLoading(store.SectionNodes, gNodes)

	var sawNodes, sawAllUsers bool
	for _, msg := range drainCmd(a.dispatchHeavyVisible()) {
		switch msg.(type) {
		case nodesMsg:
			sawNodes = true
		case allUsersJobsMsg:
			sawAllUsers = true
		}
	}
	if sawNodes {
		t.Error("re-dispatched nodes while it was already loading")
	}
	if !sawAllUsers {
		t.Error("did not dispatch all-users jobs (not loading, sidebar visible)")
	}
	if got := a.store.Gen(store.SectionNodes); got != gNodes {
		t.Errorf("nodes generation bumped (%d→%d) while loading", gNodes, got)
	}
}

// TestSetActiveSwitchesAndNoOps asserts a tab switch updates the active tab and
// returns a fetch for the newly-visible data, while re-selecting the active tab is
// a no-op.
func TestSetActiveSwitchesAndNoOps(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})
	a.active = tabJobs

	cmd := a.setActive(tabPriority)
	if a.active != tabPriority {
		t.Fatalf("active = %v, want tabPriority", a.active)
	}
	if cmd == nil {
		t.Error("switching tabs returned nil; want a fetch for the newly-visible data")
	}
	if cmd := a.setActive(tabPriority); cmd != nil {
		t.Error("setActive to the already-active tab returned a non-nil Cmd")
	}
}

// TestSlowTickReconcilesHistoryOnJobsTab asserts the slow tier refreshes the job
// history while the Jobs tab is visible, so a completion the single-shot overlay
// missed self-heals without a manual refresh.
func TestSlowTickReconcilesHistoryOnJobsTab(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})
	a.active = tabJobs
	before := a.store.Gen(store.SectionHistory)

	a.Update(slowTickMsg{at: time.Now()})

	if a.store.Gen(store.SectionHistory) == before {
		t.Error("slow tick on the Jobs tab did not reconcile history (completions would need manual refresh)")
	}
}

// TestSlowTickSkipsHistoryOffJobsTab asserts history is not polled while the Jobs
// tab is hidden (its only consumer), keeping controller load off.
func TestSlowTickSkipsHistoryOffJobsTab(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})
	a.active = tabNodes
	before := a.store.Gen(store.SectionHistory)

	a.Update(slowTickMsg{at: time.Now()})

	if a.store.Gen(store.SectionHistory) != before {
		t.Error("slow tick off the Jobs tab dispatched a history fetch; it should stay unpolled")
	}
}

// TestEnterJobsTabReconcilesHistory asserts returning to the Jobs tab reconciles
// history immediately rather than waiting up to a slow interval.
func TestEnterJobsTabReconcilesHistory(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})
	a.active = tabNodes
	before := a.store.Gen(store.SectionHistory)

	if cmd := a.setActive(tabJobs); cmd == nil {
		t.Fatal("entering the Jobs tab returned no Cmd")
	}
	if a.store.Gen(store.SectionHistory) == before {
		t.Error("entering the Jobs tab did not reconcile history")
	}
}

// TestManualRefreshDispatchesHistoryOnce asserts the dispatchHistoryIfIdle guard
// keeps manualRefresh from stacking a second history fetch (it dispatches history
// directly, then dispatchHeavyVisible must self-skip on the same wave).
func TestManualRefreshDispatchesHistoryOnce(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})
	a.active = tabJobs
	before := a.store.Gen(store.SectionHistory)

	a.manualRefresh()

	if got := a.store.Gen(store.SectionHistory) - before; got != 1 {
		t.Errorf("manualRefresh bumped the history generation %d times; want 1", got)
	}
}

// TestTerminalBlurDoesNotFreezeLiveList asserts the live running tier keeps
// polling regardless of terminal focus: a tea.BlurMsg must not stop the fast-tier
// squeue dispatch, since focus is not visibility (a visible-but-unfocused pane
// would otherwise freeze the list the user is watching).
func TestTerminalBlurDoesNotFreezeLiveList(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})

	// A blur event is now an ordinary, ignored message; it must not latch any state
	// that suppresses dispatch.
	m, _ := a.Update(tea.BlurMsg{})
	a = m.(App)

	_, cmd := a.Update(fastTickMsg{at: time.Now()})
	var sawRunningFetch bool
	for _, msg := range drainCmd(cmd) {
		if _, ok := msg.(runningJobsMsg); ok {
			sawRunningFetch = true
		}
	}
	if !sawRunningFetch {
		t.Error("a blurred fast tick did not dispatch a running-jobs fetch (the live list would freeze)")
	}
}

// TestManualRefreshSkipsLoadingSection asserts manualRefresh does not re-dispatch a
// heavy section already loading — the per-section guard that replaced the old
// heavyPending counter (whose miscount let a slow tick stack a third wave).
func TestManualRefreshSkipsLoadingSection(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{})
	a.active = tabJobs // narrow: dispatchHeavyVisible needs only all-users jobs

	g := a.store.NextGen(store.SectionAllUsersJobs)
	a.store.SetLoading(store.SectionAllUsersJobs, g)

	a.manualRefresh()

	if got := a.store.Gen(store.SectionAllUsersJobs); got != g {
		t.Errorf("all-users generation bumped (%d→%d); manualRefresh must skip a loading section", g, got)
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
	narrow.frame.invalidate()
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
		{'1', "0A·1J"},         // back to Jobs (usage banner segments)
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
			bytes.Contains(out, []byte("alice"))
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
