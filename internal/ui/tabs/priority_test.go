package tabs

import (
	"strings"
	"testing"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

func seedPriority(t *testing.T, fs []store.FairShareEntry, prio []store.PriorityEntry, username string) *Priority {
	t.Helper()
	st := store.New()
	st.SetFairShare(fs, st.NextGen(store.SectionFairShare), nil)
	st.SetPendingPrio(prio, st.NextGen(store.SectionPendingPrio), nil)
	p := NewPriority(st, theme.BuildStyles(theme.Charm(), true), username)
	p.SetSize(120, 30)
	return p
}

func TestPriorityUsersPaneRanksAndFairShare(t *testing.T) {
	fs := []store.FairShareEntry{
		{Account: "physics", User: "alice", RawShares: "100", NormShares: "0.5", RawUsage: "10", EffectvUsage: "0.1", FairShare: "0.80"},
		{Account: "physics", User: "bob", RawShares: "100", NormShares: "0.5", RawUsage: "50", EffectvUsage: "0.5", FairShare: "0.30"},
		{Account: "physics", User: "", FairShare: "0.60"}, // account-level row
	}
	p := seedPriority(t, fs, nil, "alice")

	// Switch to the All Users pane.
	p.activeSubtab = subtabUsers
	view := p.View()

	if !strings.Contains(view, "alice") || !strings.Contains(view, "bob") {
		t.Fatalf("users pane missing users; view:\n%s", view)
	}
	// alice has the higher fair-share → rank 1/2, and her fair-share appears.
	if !strings.Contains(view, "1/2") {
		t.Errorf("expected dense rank 1/2; view:\n%s", view)
	}
	if !strings.Contains(view, "0.80") {
		t.Errorf("expected alice's fair-share 0.80; view:\n%s", view)
	}
	// Status label derives from the fair-share thresholds.
	if !strings.Contains(view, "Under-served") {
		t.Errorf("expected Under-served status; view:\n%s", view)
	}
}

func TestPriorityAccountsPaneRendersAccountFairShare(t *testing.T) {
	fs := []store.FairShareEntry{
		{Account: "physics", User: "", RawShares: "200", NormShares: "0.4", FairShare: "0.45"},
		{Account: "chem", User: "", RawShares: "300", NormShares: "0.6", FairShare: "0.70"},
	}
	p := seedPriority(t, fs, nil, "alice")
	p.activeSubtab = subtabAccounts
	view := p.View()

	if !strings.Contains(view, "physics") || !strings.Contains(view, "chem") {
		t.Fatalf("accounts pane missing accounts; view:\n%s", view)
	}
	if !strings.Contains(view, "0.70") {
		t.Errorf("expected chem account fair-share 0.70; view:\n%s", view)
	}
	if !strings.Contains(view, "1/2") {
		t.Errorf("expected account dense rank; view:\n%s", view)
	}
}

func TestPriorityMyPaneShowsSummary(t *testing.T) {
	fs := []store.FairShareEntry{
		{Account: "physics", User: "alice", RawShares: "100", NormShares: "0.5", FairShare: "0.80"},
	}
	prio := []store.PriorityEntry{
		{JobID: "7001", User: "alice", Account: "physics", Priority: "5000", Partition: "gpu"},
		{JobID: "7002", User: "bob", Account: "physics", Priority: "9000", Partition: "gpu"},
	}
	p := seedPriority(t, fs, prio, "alice")
	// Default sub-tab is "mine".
	view := p.View()

	if !strings.Contains(view, "Your Priority") {
		t.Fatalf("My pane missing summary header; view:\n%s", view)
	}
	if !strings.Contains(view, "0.80") {
		t.Errorf("summary should show alice's fair-share; view:\n%s", view)
	}
	if !strings.Contains(view, "physics") {
		t.Errorf("summary should show alice's account; view:\n%s", view)
	}
	// Only alice's pending job appears on the My pane (bob's is excluded).
	if !strings.Contains(view, "7001") {
		t.Errorf("My pane should show alice's pending job 7001; view:\n%s", view)
	}
	if strings.Contains(view, "7002") {
		t.Errorf("My pane should not show bob's job 7002; view:\n%s", view)
	}
}

func TestPriorityJobsPaneSortedByPriority(t *testing.T) {
	prio := []store.PriorityEntry{
		{JobID: "100", User: "alice", Priority: "1000"},
		{JobID: "200", User: "bob", Priority: "9000"},
	}
	p := seedPriority(t, nil, prio, "alice")
	p.activeSubtab = subtabJobs
	view := p.View()

	// The higher-priority job (200) should appear before the lower one (100).
	i200 := strings.Index(view, "200")
	i100 := strings.Index(view, "100")
	if i200 < 0 || i100 < 0 {
		t.Fatalf("jobs pane missing rows; view:\n%s", view)
	}
	if i200 > i100 {
		t.Errorf("jobs pane not sorted by priority desc; view:\n%s", view)
	}
}
