package tabs

import (
	"errors"
	"strings"
	"testing"
	"time"

	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// priorityFixture is a small cluster with two accounts under root, four users
// with recent usage, one idle user, and alice holding a second, unused
// association in chem. Ranked by FairShare: bob 1, carol 2, alice 3, erin 4.
var priorityFixture = []store.FairShareEntry{
	{Account: "root", NormShares: "1", EffectvUsage: "1"},
	{Account: "physics", NormShares: "0.4", EffectvUsage: "0.6"},
	{Account: "physics", User: "alice", NormShares: "0.02", EffectvUsage: "0.25", FairShare: "0.0658"},
	{Account: "physics", User: "bob", NormShares: "0.1", EffectvUsage: "0.05", FairShare: "0.9"},
	{Account: "physics", User: "erin", NormShares: "0.1", EffectvUsage: "0.15", FairShare: "0.03"},
	{Account: "chem", NormShares: "0.6", EffectvUsage: "0.3"},
	{Account: "chem", User: "carol", NormShares: "0.1", EffectvUsage: "0.1", FairShare: "0.5"},
	{Account: "chem", User: "dave", NormShares: "0.1", EffectvUsage: "0", FairShare: "1.0"},
	{Account: "chem", User: "alice", NormShares: "0.05", EffectvUsage: "0", FairShare: "0.12"},
}

// priorityQueue is the pending queue for priorityFixture: alice's job is third
// cluster-wide and third of three in p.gpu; carol's is alone in p.cpu.
var priorityQueue = []store.PriorityEntry{
	{JobID: "5867681", User: "alice", Account: "physics", Partition: "p.gpu", QOS: "normal", Priority: 658139,
		Factors: store.PriorityFactors{FairShare: 658033, Partition: 100, JobSize: 5, Age: 1}},
	{JobID: "100", User: "bob", Account: "physics", Partition: "p.gpu", QOS: "normal", Priority: 900000,
		Factors: store.PriorityFactors{FairShare: 900000}},
	{JobID: "200", User: "carol", Account: "chem", Partition: "p.cpu", QOS: "long", Priority: 500000,
		Factors: store.PriorityFactors{FairShare: 500000}},
	{JobID: "300", User: "bob", Account: "physics", Partition: "p.gpu", QOS: "normal", Priority: 700000,
		Factors: store.PriorityFactors{FairShare: 700000}},
}

var multifactorConfig = store.PriorityConfig{
	Type: "priority/multifactor",
	Weights: store.PriorityWeights{
		FairShare: 10000000, Age: 1000, JobSize: 1000, Partition: 100,
	},
	MaxAge:        7 * 24 * time.Hour,
	DecayHalfLife: 14 * 24 * time.Hour,
}

// seedPriority builds a Priority tab over a store where every section the My
// pane waits on has settled: fair-share and the queue with the given rows, and
// the config either loaded from cfg or, when nil, failed (the pane renders
// without the weights block rather than waiting).
func seedPriority(t *testing.T, fs []store.FairShareEntry, prio []store.PriorityEntry, cfg *store.PriorityConfig, username string) (*Priority, *store.Store) {
	t.Helper()
	st := store.New()
	st.SetFairShare(fs, st.NextGen(store.SectionFairShare), nil)
	st.SetPendingPrio(prio, st.NextGen(store.SectionPendingPrio), nil)
	if cfg != nil {
		st.SetPriorityConfig(*cfg, st.NextGen(store.SectionPriorityConfig), nil)
	} else {
		st.SetPriorityConfig(store.PriorityConfig{}, st.NextGen(store.SectionPriorityConfig), errors.New("config unavailable"))
	}
	p := NewPriority(st, theme.BuildStyles(theme.Charm(), true), username)
	p.SetSize(200, 40)
	return p, st
}

// plainView renders the tab with ANSI styling stripped so assertions read the
// visible text.
func plainView(p *Priority) string { return ansi.Strip(p.View()) }

func assertContains(t *testing.T, view string, wants ...string) {
	t.Helper()
	for _, want := range wants {
		if !strings.Contains(view, want) {
			t.Errorf("view missing %q; view:\n%s", want, view)
		}
	}
}

// TestPriorityMyPaneExplainsStanding asserts the My pane answers where the user
// stands (rank, percentile, status), why (usage versus share, factor weights and
// their share of the user's priority), when it improves (recovery estimate), and
// where the user's best job sits in the queue with its breakdown.
func TestPriorityMyPaneExplainsStanding(t *testing.T) {
	cfg := multifactorConfig
	p, _ := seedPriority(t, priorityFixture, priorityQueue, &cfg, "alice")
	view := plainView(p)

	assertContains(t, view,
		"Your Priority", "alice · physics",
		"0.0658", "rank 3 of 4 active users (bottom 25%)", "Heavily over-served",
		"12.5× — 25.0% of recent cluster usage on a 2.00% share",
		"usage halves every 14d → ≈51d without jobs to reach 1×",
		"Also in: chem (0.1200)",
		"FairShare ×10,000,000 · Age ×1,000 (maxes after 7d) · JobSize ×1,000 · Partition ×100",
		"Your Pending Jobs (1)", "p.gpu", "best at #3 of 3 · 2 ahead of you",
		"5867681", "#3/3", "FairShare 658033 · Partition 100 · JobSize 5 · Age 1",
	)
	if strings.Contains(view, "100 ") && strings.Contains(view, "bob") {
		t.Errorf("My pane should only list alice's jobs; view:\n%s", view)
	}
}

// TestPriorityMyPaneReflowsToWidth asserts a narrow pane wraps the summary prose
// instead of clipping it: no summary line exceeds the width, a wrapped labelled
// row hangs its continuation under the value column, a resize re-wraps, and the
// pending-jobs table still gets rows below the taller summary.
func TestPriorityMyPaneReflowsToWidth(t *testing.T) {
	cfg := multifactorConfig
	p, _ := seedPriority(t, priorityFixture, priorityQueue, &cfg, "alice")
	p.SetSize(70, 40)
	view := plainView(p)

	lines := strings.Split(view, "\n")
	for _, ln := range lines {
		if strings.HasPrefix(strings.TrimSpace(ln), "JobID") {
			break
		}
		if w := lipgloss.Width(ln); w > 70 {
			t.Errorf("summary line %d wide at width 70: %q", w, ln)
		}
	}
	// The recovery row no longer fits on one line; its continuation must sit in
	// the value column (indent 2 + label 18 + gap 2) rather than at the margin.
	var recoveryIdx int
	for i, ln := range lines {
		if strings.Contains(ln, "Recovery") {
			recoveryIdx = i
		}
	}
	if recoveryIdx == 0 || !strings.HasPrefix(lines[recoveryIdx+1], strings.Repeat(" ", 22)) ||
		strings.TrimSpace(lines[recoveryIdx+1]) == "" {
		t.Errorf("recovery row continuation not hung under the value column; view:\n%s", view)
	}
	assertContains(t, view, "5867681", "#3/3")

	p.SetSize(200, 40)
	if wide := plainView(p); !strings.Contains(wide, "usage halves every 14d → ≈51d without jobs to reach 1×  (approx; assumes steady load)") {
		t.Errorf("widening the pane must un-wrap the summary; view:\n%s", wide)
	}
}

// TestPriorityMyPaneUnusedAssociation asserts a user who has an allocation but
// no recent usage is told they start near the front rather than ranked.
func TestPriorityMyPaneUnusedAssociation(t *testing.T) {
	p, _ := seedPriority(t, priorityFixture, nil, nil, "dave")
	view := plainView(p)
	assertContains(t, view, "dave · chem", "1.0000", "Unused — no recent usage")
	if strings.Contains(view, "rank ") {
		t.Errorf("unused user must not be ranked; view:\n%s", view)
	}
}

// TestPriorityMyPaneWaitsForEverySection asserts the My pane shows a single
// loading status until fair-share, the pending queue, and the priority config
// have all completed a first fetch — never a half-built summary — and that a
// later refresh of a settled section leaves the summary on screen.
func TestPriorityMyPaneWaitsForEverySection(t *testing.T) {
	st := store.New()
	st.SetLoading(store.SectionFairShare, st.NextGen(store.SectionFairShare))
	st.SetLoading(store.SectionPendingPrio, st.NextGen(store.SectionPendingPrio))
	st.SetLoading(store.SectionPriorityConfig, st.NextGen(store.SectionPriorityConfig))
	p := NewPriority(st, theme.BuildStyles(theme.Charm(), true), "alice")
	p.SetSize(200, 40)

	now := time.Unix(0, 0)
	p.status = sectionStatus{now: func() time.Time { return now }}
	p.Refresh()
	now = now.Add(spinnerDebounce)

	assertWaiting := func(stage string) {
		t.Helper()
		view := plainView(p)
		assertContains(t, view, "Loading…")
		for _, absent := range []string{"Your Priority", "No fair-share association", "Your Pending Jobs"} {
			if strings.Contains(view, absent) {
				t.Errorf("%s: pane rendered %q before every section settled; view:\n%s", stage, absent, view)
			}
		}
	}
	assertWaiting("all loading")

	st.SetFairShare(priorityFixture, st.NextGen(store.SectionFairShare), nil)
	p.Refresh()
	now = now.Add(spinnerDebounce)
	assertWaiting("fair-share landed, queue and config pending")

	st.SetPendingPrio(priorityQueue, st.NextGen(store.SectionPendingPrio), nil)
	p.Refresh()
	now = now.Add(spinnerDebounce)
	assertWaiting("queue landed, config pending")

	// A failed config fetch still settles the pane: the summary renders without
	// the weights block rather than waiting forever.
	st.SetPriorityConfig(store.PriorityConfig{}, st.NextGen(store.SectionPriorityConfig), errors.New("scontrol: boom"))
	p.Refresh()
	view := plainView(p)
	assertContains(t, view, "Your Priority", "alice · physics", "Your Pending Jobs (1)", "best at #3 of 3")
	for _, absent := range []string{"Loading…", "How priority is computed", "Recovery"} {
		if strings.Contains(view, absent) {
			t.Errorf("settled pane must not render %q; view:\n%s", absent, view)
		}
	}

	// A later refresh of a settled section keeps the summary on screen.
	st.SetLoading(store.SectionPendingPrio, st.NextGen(store.SectionPendingPrio))
	p.Refresh()
	now = now.Add(spinnerDebounce)
	if view := plainView(p); strings.Contains(view, "Loading…") || !strings.Contains(view, "Your Priority") {
		t.Errorf("refresh of a settled section must not hide the summary; view:\n%s", view)
	}
}

// TestPriorityMyPaneNoAssociationNote asserts the "no association" note appears
// only after a completed fair-share load finds no rows for the user.
func TestPriorityMyPaneNoAssociationNote(t *testing.T) {
	p, _ := seedPriority(t, nil, nil, nil, "alice")
	assertContains(t, plainView(p), `No fair-share association found for "alice"`)
}

// TestPriorityMyPaneFIFOConfig asserts a non-multifactor plugin renders the FIFO
// sentence and none of the multifactor explanation.
func TestPriorityMyPaneFIFOConfig(t *testing.T) {
	cfg := store.PriorityConfig{Type: "priority/basic"}
	p, _ := seedPriority(t, priorityFixture, priorityQueue, &cfg, "alice")
	view := plainView(p)
	assertContains(t, view, "Scheduler: priority/basic — jobs start in submission order; fair-share does not apply.")
	for _, absent := range []string{"×10,000,000", "Your jobs:", "Recovery"} {
		if strings.Contains(view, absent) {
			t.Errorf("FIFO config must not render %q; view:\n%s", absent, view)
		}
	}
}

// TestPriorityActiveUsersPane asserts the Active Users pane ranks only users with
// recent usage, reports how many idle users it hides, colors nothing into the
// plain names, and marks and selects the current user's row.
func TestPriorityActiveUsersPane(t *testing.T) {
	p, _ := seedPriority(t, priorityFixture, nil, nil, "alice")
	p.activeSubtab = subtabUsers
	view := plainView(p)

	assertContains(t, view,
		"4 active users · 1 without recent usage hidden",
		"1/4", "bob", "4/4", "erin", ">> alice", "Heavily over-served", "Under-served",
		"2.00%", "25.0%", "12.5×",
	)
	if strings.Contains(view, "dave") {
		t.Errorf("user without usage must be hidden; view:\n%s", view)
	}
	if kind, who := p.SelectedDetail(); kind != PriorityDetailUser || who != "alice" {
		t.Errorf("cursor should land on the current user: got (%v, %q)", kind, who)
	}
}

// TestPriorityAccountsPane asserts the Accounts pane ranks only accounts with
// recent usage (root and idle accounts are hidden behind a count), orders them
// by usage/share (best served first), counts active/total users, and marks the
// current user's account.
func TestPriorityAccountsPane(t *testing.T) {
	fs := append([]store.FairShareEntry{{Account: "idle", NormShares: "0.1", EffectvUsage: "0"}}, priorityFixture...)
	p, _ := seedPriority(t, fs, nil, nil, "alice")
	p.activeSubtab = subtabAccounts
	view := plainView(p)

	assertContains(t, view, "2 active accounts · 1 without recent usage hidden",
		"chem", ">> physics", "0.50×", "1.5×", "1/3", "3/3", "Under-served", "Over-served")
	for _, absent := range []string{"root", "idle"} {
		if strings.Contains(view, absent) {
			t.Errorf("%q must be hidden; view:\n%s", absent, view)
		}
	}
	if strings.Index(view, "chem") > strings.Index(view, "physics") {
		t.Errorf("accounts not ordered by usage/share ascending; view:\n%s", view)
	}
	if kind, who := p.SelectedDetail(); kind != PriorityDetailAccount || who == "" || strings.HasPrefix(who, ">>") {
		t.Errorf("SelectedDetail = (%v, %q); want an account name without the prefix", kind, who)
	}
}

// TestPriorityJobsPane asserts the Jobs pane groups the queue by partition in
// queue order (a job only competes within its partition), shows real
// account/partition/QOS names, the in-partition and cluster-wide positions, and
// marks the current user's rows.
func TestPriorityJobsPane(t *testing.T) {
	p, _ := seedPriority(t, priorityFixture, priorityQueue, nil, "alice")
	p.activeSubtab = subtabJobs
	view := plainView(p)

	assertContains(t, view, "#1/4", "#4/4", "#1/1", "chem", "p.cpu", "long", ">> alice", "658033")
	// p.cpu (carol's 200, the lowest priority) groups before p.gpu, and within
	// p.gpu bob's 100 (highest) precedes alice's 5867681.
	cpu, gpuBest, mine := strings.Index(view, "200 "), strings.Index(view, "100 "), strings.Index(view, "5867681")
	if cpu < 0 || gpuBest < 0 || mine < 0 || cpu > gpuBest || gpuBest > mine {
		t.Errorf("jobs not grouped by partition in queue order; view:\n%s", view)
	}
	if kind, _ := p.SelectedDetail(); kind != PriorityDetailNone {
		t.Errorf("Jobs pane has no row detail; got %v", kind)
	}
}
