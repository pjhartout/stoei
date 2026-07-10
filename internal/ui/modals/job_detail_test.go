package modals

import (
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// testStyles builds a dark style set for modal tests.
func testStyles() theme.Styles { return theme.BuildStyles(theme.Charm(), true) }

// drain runs a Cmd and returns the first message it produces (flattening a single
// Batch level so a fetch+spinner batch yields both children when iterated by the
// caller). Here we just return the first non-nil child message.
func firstMsg(cmd tea.Cmd) tea.Msg {
	if cmd == nil {
		return nil
	}
	msg := cmd()
	if batch, ok := msg.(tea.BatchMsg); ok {
		for _, c := range batch {
			if c == nil {
				continue
			}
			if m := c(); m != nil {
				return m
			}
		}
		return nil
	}
	return msg
}

// TestJobDetailRendersFieldsFromFakeClient drives the job-detail modal end to end
// against a FakeClient: Init issues a fetch Cmd (not a blocking read), and feeding
// the result message renders the scontrol fields.
func TestJobDetailRendersFieldsFromFakeClient(t *testing.T) {
	fc := &store.FakeClient{
		JobDetailData: store.JobDetail{
			Source: "scontrol",
			Fields: map[string]string{
				"JobId":    "12345",
				"JobName":  "train",
				"JobState": "RUNNING",
				"StdOut":   "/logs/out.log",
				"StdErr":   "/logs/err.log",
			},
		},
	}
	cache := NewJobDetailCache()
	d := NewJobDetail(fc, cache, testStyles(), "12345", "RUNNING")
	d.SetSize(80, 24)

	// Init must return a Cmd (the fetch + spinner), proving the read is deferred to
	// a Cmd rather than performed inline in the constructor/Init.
	cmd := d.Init()
	if cmd == nil {
		t.Fatal("Init returned nil Cmd; the fetch must be issued as a Cmd")
	}
	msg := firstMsg(cmd)
	loaded, ok := msg.(jobDetailLoadedMsg)
	if !ok {
		t.Fatalf("first Cmd message = %T; want jobDetailLoadedMsg", msg)
	}
	if fc.LastJobDetailID != "12345" {
		t.Errorf("JobDetail called with %q; want 12345", fc.LastJobDetailID)
	}

	d.Update(loaded)
	view := d.View()
	if !strings.Contains(view, "train") || !strings.Contains(view, "RUNNING") {
		t.Errorf("rendered detail missing fields, got:\n%s", view)
	}

	// The cache should now hold the rendered entry with stdout/stderr extracted.
	entry, hit := cache.Get("12345", "RUNNING")
	if !hit {
		t.Fatal("expected the loaded detail to be cached")
	}
	if entry.stdout != "/logs/out.log" || entry.stderr != "/logs/err.log" {
		t.Errorf("cached log paths = %q / %q; want /logs/out.log / /logs/err.log", entry.stdout, entry.stderr)
	}
}

// TestJobDetailCacheHitSkipsFetch asserts a cached entry for the same live state
// is shown instantly (Init returns no Cmd, no client call).
func TestJobDetailCacheHitSkipsFetch(t *testing.T) {
	fc := &store.FakeClient{}
	cache := NewJobDetailCache()
	cache.Put("12345", cachedDetail{content: "CACHED DETAIL", state: "RUNNING"})

	d := NewJobDetail(fc, cache, testStyles(), "12345", "RUNNING")
	d.SetSize(80, 24)
	if cmd := d.Init(); cmd != nil {
		t.Error("cache hit should not issue a fetch Cmd")
	}
	if fc.LastJobDetailID != "" {
		t.Error("cache hit should not call the client")
	}
	if !strings.Contains(d.View(), "CACHED DETAIL") {
		t.Errorf("cache hit not rendered, got:\n%s", d.View())
	}
}

// TestJobDetailRefetchesOnStateChange asserts that a cached entry for a different
// live state is a miss, forcing a fresh fetch (cache-evict-on-state-change).
func TestJobDetailRefetchesOnStateChange(t *testing.T) {
	fc := &store.FakeClient{
		JobDetailData: store.JobDetail{Source: "sacct", Fields: map[string]string{"State": "COMPLETED"}},
	}
	cache := NewJobDetailCache()
	cache.Put("12345", cachedDetail{content: "OLD RUNNING DETAIL", state: "RUNNING"})

	// Opening the job now in COMPLETED state must miss the RUNNING-state cache.
	d := NewJobDetail(fc, cache, testStyles(), "12345", "COMPLETED")
	d.SetSize(80, 24)
	cmd := d.Init()
	if cmd == nil {
		t.Fatal("state change should issue a fresh fetch Cmd")
	}
	if msg := firstMsg(cmd); msg == nil {
		t.Fatal("fetch Cmd produced no message")
	}
	if fc.LastJobDetailID != "12345" {
		t.Errorf("expected a re-fetch for the changed state, client not called")
	}
}

// TestJobDetailOpenLogEmitsMsg asserts pressing o/e emits an OpenLogMsg with the
// extracted path.
func TestJobDetailOpenLogEmitsMsg(t *testing.T) {
	fc := &store.FakeClient{
		JobDetailData: store.JobDetail{
			Source: "scontrol",
			Fields: map[string]string{"JobId": "1", "StdOut": "/o.log", "StdErr": "/e.log"},
		},
	}
	d := NewJobDetail(fc, NewJobDetailCache(), testStyles(), "1", "RUNNING")
	d.Update(firstMsg(d.Init()))

	_, cmd, done := d.Update(tea.KeyPressMsg{Code: 'o', Text: "o"})
	if done {
		t.Error("opening a log should not close the detail modal")
	}
	msg := firstMsg(cmd)
	open, ok := msg.(OpenLogMsg)
	if !ok {
		t.Fatalf("o produced %T; want OpenLogMsg", msg)
	}
	if open.Path != "/o.log" || open.Label != "stdout" {
		t.Errorf("OpenLogMsg = %+v; want /o.log stdout", open)
	}
}

// TestJobDetailEscCloses asserts esc reports done.
func TestJobDetailEscCloses(t *testing.T) {
	d := NewJobDetail(&store.FakeClient{}, NewJobDetailCache(), testStyles(), "1", "RUNNING")
	_, _, done := d.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
	if !done {
		t.Error("esc should close the job-detail modal")
	}
}

// TestJobDetailMOpensModify asserts "m" emits an OpenModifyMsg carrying the
// loaded scontrol fields, and is a no-op before the detail has loaded.
func TestJobDetailMOpensModify(t *testing.T) {
	fc := &store.FakeClient{
		JobDetailData: store.JobDetail{
			Source: "scontrol",
			Fields: map[string]string{"JobId": "12345", "JobState": "RUNNING", "Partition": "p.hpcl91"},
		},
	}
	d := NewJobDetail(fc, NewJobDetailCache(), testStyles(), "12345", "RUNNING")
	d.SetSize(80, 24)

	_, cmd, _ := d.Update(tea.KeyPressMsg{Code: 'm', Text: "m"})
	if cmd != nil {
		t.Error("m before the detail loads must be a no-op")
	}

	fetch := d.Init()
	d.Update(firstMsg(fetch))
	_, cmd, done := d.Update(tea.KeyPressMsg{Code: 'm', Text: "m"})
	if done {
		t.Error("m must not close the detail modal")
	}
	msg, ok := firstMsg(cmd).(OpenModifyMsg)
	if !ok {
		t.Fatalf("m produced %T; want OpenModifyMsg", firstMsg(cmd))
	}
	if msg.JobID != "12345" || msg.Fields["Partition"] != "p.hpcl91" {
		t.Errorf("OpenModifyMsg = %+v; want job 12345 with loaded fields", msg)
	}
}
