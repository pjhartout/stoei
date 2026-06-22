package ui

import (
	"bytes"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/charmbracelet/x/exp/teatest/v2"

	"github.com/pjhartout/stoei/internal/store"
)

// seedJobsApp builds an App whose store already has one running job, sized and
// ready, so Enter on the Jobs tab has a row to open.
func seedJobsApp(t *testing.T) (App, *store.FakeClient) {
	t.Helper()
	fc := &store.FakeClient{
		UsernameStr: "alice",
		RunningJobsData: []store.RunningJob{
			{ID: "1001", Name: "train", State: "RUNNING", Time: "1:00", Nodes: "1", NodeList: "node01"},
		},
		JobDetailData: store.JobDetail{
			Source: "scontrol",
			Fields: map[string]string{"JobId": "1001", "JobName": "train", "JobState": "RUNNING"},
		},
	}
	a := newTestApp(t, fc)
	a.width, a.height = 100, 30
	a.store.SetRunningJobs(fc.RunningJobsData, a.store.NextGen(store.SectionRunningJobs), nil)
	a.jobs.Refresh()
	a.fanoutSize()
	return a, fc
}

// updateApp applies one message to the app and returns the concrete App back.
func updateApp(a App, msg tea.Msg) App {
	m, _ := a.Update(msg)
	return m.(App)
}

// TestModalRoutesKeysAndFreezesBase asserts that while a modal is open the base
// tab does not receive input: number-key tab switches are consumed by the modal
// stack, and the active tab stays put.
func TestModalRoutesKeysAndFreezesBase(t *testing.T) {
	a, _ := seedJobsApp(t)

	// Open the help modal.
	a = updateApp(a, tea.KeyPressMsg{Code: '?', Text: "?"})
	if len(a.modals) != 1 {
		t.Fatalf("? should open a modal; have %d", len(a.modals))
	}
	if a.active != tabJobs {
		t.Fatalf("active tab = %v; want Jobs", a.active)
	}

	// A number key that would switch tabs must be consumed by the modal, not the
	// base: the active tab stays Jobs.
	a = updateApp(a, tea.KeyPressMsg{Code: '2', Text: "2"})
	if a.active != tabJobs {
		t.Errorf("base tab switched while a modal was open; active = %v", a.active)
	}
	if len(a.modals) != 1 {
		t.Errorf("modal stack changed on a non-close key; have %d", len(a.modals))
	}
}

// TestModalEscPops asserts esc pops the top modal rather than quitting the app.
func TestModalEscPops(t *testing.T) {
	a, _ := seedJobsApp(t)
	a = updateApp(a, tea.KeyPressMsg{Code: '?', Text: "?"})
	if len(a.modals) != 1 {
		t.Fatalf("setup: modal not open")
	}

	a = updateApp(a, tea.KeyPressMsg{Code: tea.KeyEscape})
	if len(a.modals) != 0 {
		t.Errorf("esc should pop the modal; have %d", len(a.modals))
	}
	if a.quitting {
		t.Error("esc on a modal must not quit the app")
	}
}

// TestEnterOpensJobDetail asserts Enter on the Jobs tab opens a job-detail modal
// and fetches the detail for the selected job (state passed for cache-evict).
func TestEnterOpensJobDetail(t *testing.T) {
	a, fc := seedJobsApp(t)

	m, cmd := a.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	a = m.(App)
	if len(a.modals) != 1 {
		t.Fatalf("Enter should open a job-detail modal; have %d", len(a.modals))
	}
	// Draining the modal's Init Cmd performs the fetch.
	drainCmd(cmd)
	if fc.LastJobDetailID != "1001" {
		t.Errorf("job detail fetched for %q; want 1001", fc.LastJobDetailID)
	}
}

// TestCancelRefusedForCompletedJob asserts "c" on a non-active job is refused
// with a toast and opens no modal (port of the active-job guard).
func TestCancelRefusedForCompletedJob(t *testing.T) {
	fc := &store.FakeClient{
		UsernameStr:     "alice",
		HistoryJobsData: []store.HistoryJob{{ID: "2002", Name: "done", State: "COMPLETED", Elapsed: "5:00"}},
	}
	a := newTestApp(t, fc)
	a.width, a.height = 100, 30
	a.store.SetHistory(fc.HistoryJobsData, store.HistoryStats{}, a.store.NextGen(store.SectionHistory), nil)
	a.jobs.Refresh()
	a.fanoutSize()

	a = updateApp(a, tea.KeyPressMsg{Code: 'c', Text: "c"})
	if len(a.modals) != 0 {
		t.Errorf("cancel must be refused for a completed job; modal opened")
	}
	if len(a.toasts) == 0 {
		t.Error("refusing cancel should toast the user")
	}
}

// TestIPromptOpensJobInput asserts "i" on the Jobs tab opens the job-id prompt.
func TestIPromptOpensJobInput(t *testing.T) {
	a, _ := seedJobsApp(t)
	a = updateApp(a, tea.KeyPressMsg{Code: 'i', Text: "i"})
	if len(a.modals) != 1 {
		t.Errorf("i should open the job-id prompt; have %d", len(a.modals))
	}
}

// TestTeatestJobDetailOpenClose drives the real loop: open a job detail from the
// Jobs tab, see its content, close it with esc, and quit.
func TestTeatestJobDetailOpenClose(t *testing.T) {
	fc := &store.FakeClient{
		UsernameStr: "alice",
		RunningJobsData: []store.RunningJob{
			{ID: "1001", Name: "train", State: "RUNNING", Time: "1:00", Nodes: "1", NodeList: "node01"},
		},
		JobDetailData: store.JobDetail{
			Source: "scontrol",
			Fields: map[string]string{"JobId": "1001", "JobName": "trainjob", "JobState": "RUNNING"},
		},
	}
	st := store.New()
	st.SetClock(func() time.Time { return time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC) })
	st.SetRunningJobs(fc.RunningJobsData, st.NextGen(store.SectionRunningJobs), nil)

	tm := teatest.NewTestModel(t, New(st, fc), teatest.WithInitialTermSize(100, 30))

	teatest.WaitFor(t, tm.Output(), func(out []byte) bool {
		return bytes.Contains(out, []byte("train"))
	}, teatest.WithDuration(3*time.Second), teatest.WithCheckInterval(10*time.Millisecond))

	// Enter opens the job-detail modal, which fetches and renders the job name.
	tm.Send(tea.KeyPressMsg{Code: tea.KeyEnter})
	teatest.WaitFor(t, tm.Output(), func(out []byte) bool {
		return bytes.Contains(out, []byte("Job Details")) && bytes.Contains(out, []byte("trainjob"))
	}, teatest.WithDuration(3*time.Second), teatest.WithCheckInterval(10*time.Millisecond))

	// Esc closes the modal, revealing the base Jobs tab again.
	tm.Send(tea.KeyPressMsg{Code: tea.KeyEscape})
	teatest.WaitFor(t, tm.Output(), func(out []byte) bool {
		return !bytes.Contains(out, []byte("Job Details"))
	}, teatest.WithDuration(3*time.Second), teatest.WithCheckInterval(10*time.Millisecond))

	tm.Send(tea.KeyPressMsg{Code: 'q', Text: "q"})
	tm.WaitFinished(t, teatest.WithFinalTimeout(5*time.Second))
}
