package ui

import (
	"errors"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/modals"
)

// drainAllMsgs runs a Cmd and recursively flattens nested tea.Batch layers,
// returning every message produced, so assertions never depend on how deeply
// the handler nested its batches or on child ordering.
func drainAllMsgs(cmd tea.Cmd) []tea.Msg {
	if cmd == nil {
		return nil
	}
	msg := cmd()
	batch, ok := msg.(tea.BatchMsg)
	if !ok {
		if msg == nil {
			return nil
		}
		return []tea.Msg{msg}
	}
	var out []tea.Msg
	for _, c := range batch {
		out = append(out, drainAllMsgs(c)...)
	}
	return out
}

// TestJobIDSubmittedOpensJobDetail asserts the root reacts to the job-id
// prompt's JobIDSubmittedMsg by pushing a job-detail modal whose Init fetches
// that id — the seam that makes the "i" lookup flow actually show a job.
func TestJobIDSubmittedOpensJobDetail(t *testing.T) {
	a, fc := seedJobsApp(t)

	m, cmd := a.Update(modals.JobIDSubmittedMsg{JobID: "4242"})
	a = m.(App)
	if len(a.modals) != 1 {
		t.Fatalf("job-id submit should open a modal; have %d", len(a.modals))
	}
	if _, ok := a.modals[0].(*modals.JobDetail); !ok {
		t.Fatalf("top modal = %T; want *modals.JobDetail", a.modals[0])
	}
	drainAllMsgs(cmd)
	if fc.LastJobDetailID != "4242" {
		t.Errorf("detail fetched for %q; want 4242", fc.LastJobDetailID)
	}
}

// TestCancelRequestedErrorToastsOnly asserts a failed cancellation surfaces a
// failure toast and nothing else: no refresh is dispatched, so the job list is
// not churned for an action that did not change scheduler state.
func TestCancelRequestedErrorToastsOnly(t *testing.T) {
	a, _ := seedJobsApp(t)
	before := a.store.Gen(store.SectionHistory)

	m, cmd := a.Update(modals.CancelRequestedMsg{JobID: "1001", Err: errors.New("scancel: boom")})
	a = m.(App)

	if cmd != nil {
		t.Error("a failed cancel must not dispatch any Cmd")
	}
	if len(a.toasts) != 1 || !strings.Contains(a.toasts[0].text, "Cancel failed for 1001") {
		t.Errorf("toasts = %+v; want one failure toast for job 1001", a.toasts)
	}
	if got := a.store.Gen(store.SectionHistory); got != before {
		t.Errorf("history generation bumped (%d→%d); a failed cancel must not refresh", before, got)
	}
}

// TestCancelRequestedSuccessToastsAndRefreshes asserts a confirmed cancellation
// toasts the outcome and triggers a manual refresh so the cancelled job leaves
// the list instead of lingering until the next tick.
func TestCancelRequestedSuccessToastsAndRefreshes(t *testing.T) {
	a, _ := seedJobsApp(t)
	before := a.store.Gen(store.SectionHistory)

	m, cmd := a.Update(modals.CancelRequestedMsg{JobID: "1001"})
	a = m.(App)

	if len(a.toasts) != 1 || !strings.Contains(a.toasts[0].text, "Cancelled job 1001") {
		t.Errorf("toasts = %+v; want one success toast for job 1001", a.toasts)
	}
	if cmd == nil {
		t.Fatal("a successful cancel must return the manual-refresh Cmd")
	}
	if got := a.store.Gen(store.SectionHistory); got != before+1 {
		t.Errorf("history generation bumped %d times; want 1 (manual refresh dispatched)", got-before)
	}
}

// TestModifyRequestedErrorToastsOnly asserts a failed scontrol update surfaces a
// failure toast without evicting the detail cache or dispatching a refresh: the
// job is unchanged, so the cached render is still valid.
func TestModifyRequestedErrorToastsOnly(t *testing.T) {
	a, _ := seedJobsApp(t)
	before := a.store.Gen(store.SectionHistory)

	m, cmd := a.Update(modals.ModifyRequestedMsg{JobID: "1001", Desc: "TimeLimit=2:00", Err: errors.New("scontrol: denied")})
	a = m.(App)

	if cmd != nil {
		t.Error("a failed modify must not dispatch any Cmd")
	}
	if len(a.toasts) != 1 || !strings.Contains(a.toasts[0].text, "Modify failed for 1001") {
		t.Errorf("toasts = %+v; want one failure toast for job 1001", a.toasts)
	}
	if got := a.store.Gen(store.SectionHistory); got != before {
		t.Errorf("history generation bumped (%d→%d); a failed modify must not refresh", before, got)
	}
}

// TestModifyRequestedSuccessRefreshesOpenDetail asserts the full success path of
// a modification: a toast, eviction of the job's cached detail, a manual-refresh
// dispatch, and a re-Init of the job-detail modal still open under the modify
// modal — without the re-Init the user would keep staring at the
// pre-modification render served from the (now stale) cache.
func TestModifyRequestedSuccessRefreshesOpenDetail(t *testing.T) {
	a, fc := seedJobsApp(t)

	// Open the detail modal and feed its fetch result back through Update so the
	// modal is loaded and the detail cache holds its render.
	m, cmd := a.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	a = m.(App)
	for _, msg := range drainAllMsgs(cmd) {
		m, _ = a.Update(msg)
		a = m.(App)
	}
	if a.detailCache.Len() != 1 {
		t.Fatalf("setup: detail cache has %d entries; want 1", a.detailCache.Len())
	}

	fc.LastJobDetailID = ""
	// Pretend the spinner tier is already armed so the drained batch holds no
	// wall-clock tick Cmd (ensureSpinner would otherwise arm a 100ms tea.Tick).
	a.spinnerActive = true
	before := a.store.Gen(store.SectionHistory)

	m, cmd = a.Update(modals.ModifyRequestedMsg{JobID: "1001", Desc: "TimeLimit=2:00"})
	a = m.(App)

	if len(a.toasts) != 1 || !strings.Contains(a.toasts[0].text, "Updated job 1001") {
		t.Errorf("toasts = %+v; want one success toast for job 1001", a.toasts)
	}
	if a.detailCache.Len() != 0 {
		t.Error("success must evict the job's cached detail so the next render re-fetches")
	}
	if got := a.store.Gen(store.SectionHistory); got != before+1 {
		t.Errorf("history generation bumped %d times; want 1 (manual refresh dispatched)", got-before)
	}

	if len(a.modals) != 1 {
		t.Fatalf("modal stack has %d entries; want the job-detail modal still open", len(a.modals))
	}
	d, ok := a.modals[0].(*modals.JobDetail)
	if !ok {
		t.Fatalf("top modal = %T; want *modals.JobDetail", a.modals[0])
	}
	if !strings.Contains(d.View(), "Loading job information") {
		t.Error("open detail modal was not re-Init'd; it would keep showing the stale pre-modification render")
	}
	drainAllMsgs(cmd)
	if fc.LastJobDetailID != "1001" {
		t.Errorf("re-Init fetched %q; want a fresh detail fetch for 1001", fc.LastJobDetailID)
	}
}
