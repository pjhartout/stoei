package modals

import (
	"errors"
	"regexp"
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

// ansiSeq matches SGR escape sequences so layout assertions can inspect the
// plain text of a styled render.
var ansiSeq = regexp.MustCompile(`\x1b\[[0-9;]*m`)

// stripAnsi removes SGR escape sequences from a rendered view.
func stripAnsi(s string) string { return ansiSeq.ReplaceAllString(s, "") }

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
	d := NewJobDetail(fc, cache, testStyles(), "12345", "RUNNING", store.JobDetail{})
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
// is shown instantly: no detail fetch reaches the client. A running job still
// issues the live usage lookup so the Efficiency numbers stay fresh.
func TestJobDetailCacheHitSkipsFetch(t *testing.T) {
	fc := &store.FakeClient{}
	cache := NewJobDetailCache()
	cache.Put("12345", cachedDetail{content: "CACHED DETAIL", state: "RUNNING"})

	d := NewJobDetail(fc, cache, testStyles(), "12345", "RUNNING", store.JobDetail{})
	d.SetSize(80, 24)
	cmd := d.Init()
	if cmd == nil {
		t.Fatal("running-job cache hit must still issue the live usage Cmd")
	}
	if _, ok := firstMsg(cmd).(jobUsageLoadedMsg); !ok {
		t.Error("cache-hit Cmd is not the usage lookup")
	}
	if fc.LastJobDetailID != "" {
		t.Error("cache hit should not re-fetch the detail")
	}
	if fc.LastJobUsageID != "12345" || !fc.LastJobUsageRunning {
		t.Errorf("usage lookup = %q running=%v; want 12345 running=true", fc.LastJobUsageID, fc.LastJobUsageRunning)
	}
	if !strings.Contains(d.View(), "CACHED DETAIL") {
		t.Errorf("cache hit not rendered, got:\n%s", d.View())
	}
}

// TestJobDetailUsageSectionRendersAfterLoad drives the full two-step flow: the
// detail load starts the usage lookup, and feeding its result appends the
// Efficiency section with the derived metrics.
func TestJobDetailUsageSectionRendersAfterLoad(t *testing.T) {
	fc := &store.FakeClient{
		UsernameStr: "alice",
		JobDetailData: store.JobDetail{
			Source: "scontrol",
			Fields: map[string]string{
				"JobId":    "5834914",
				"JobState": "COMPLETED",
				"UserId":   "alice(1000)",
				"TRES":     "cpu=4,mem=2G,node=1",
			},
		},
		JobUsageData: store.JobUsage{
			Source:         "sacct",
			Sampled:        true,
			ElapsedSec:     171,
			AllocCPUs:      4,
			CPUTimeSec:     171.3,
			MaxRSSBytes:    2502 * 1024,
			DiskReadBytes:  32225772153,
			DiskWriteBytes: 1572864182,
		},
	}
	cache := NewJobDetailCache()
	d := NewJobDetail(fc, cache, testStyles(), "5834914", "COMPLETED", store.JobDetail{})
	d.SetSize(100, 40)

	loaded := firstMsg(d.Init()).(jobDetailLoadedMsg)
	_, usageCmd, _ := d.Update(loaded)
	if usageCmd == nil {
		t.Fatal("detail load did not start the usage lookup")
	}
	if fc.LastJobUsageRunning {
		t.Error("terminal job queried via sstat; want sacct (running=false)")
	}
	usageMsg, ok := firstMsg(usageCmd).(jobUsageLoadedMsg)
	if !ok {
		t.Fatal("usage Cmd did not produce a jobUsageLoadedMsg")
	}
	d.Update(usageMsg)

	view := d.View()
	for _, want := range []string{"Efficiency", "CPU efficiency", "25%", "Peak RAM", "2.4M", "Disk read", "30.0G"} {
		if !strings.Contains(view, want) {
			t.Errorf("Efficiency section missing %q, got:\n%s", want, view)
		}
	}

	// A blank separator line precedes the Efficiency title, matching the
	// spacing formatCategorized puts between every other category.
	lines := strings.Split(stripAnsi(view), "\n")
	for i, line := range lines {
		if strings.Contains(line, "Efficiency") {
			if i == 0 || strings.Trim(lines[i-1], "│ \t") != "" {
				t.Errorf("no blank line before Efficiency title; previous line: %q", lines[i-1])
			}
			break
		}
	}

	// The section is mirrored into the cache: a reopen of the finished job
	// renders instantly with no further lookups.
	entry, hit := cache.Get("5834914", "COMPLETED")
	if !hit || entry.usage == "" {
		t.Fatal("usage section not cached")
	}
	reopened := NewJobDetail(fc, cache, testStyles(), "5834914", "COMPLETED", store.JobDetail{})
	reopened.SetSize(100, 40)
	if cmd := reopened.Init(); cmd != nil {
		t.Error("terminal job with cached usage re-fetched on reopen")
	}
	if !strings.Contains(reopened.View(), "CPU efficiency") {
		t.Error("reopen lost the cached Efficiency section")
	}
}

// TestJobDetailForeignRunningJobUsageNote asserts a running job owned by
// another user gets the ownership note instead of an sstat lookup, which
// slurmstepd would refuse.
func TestJobDetailForeignRunningJobUsageNote(t *testing.T) {
	fc := &store.FakeClient{
		UsernameStr: "alice",
		JobDetailData: store.JobDetail{
			Source: "scontrol",
			Fields: map[string]string{"JobState": "RUNNING", "UserId": "bob(1001)"},
		},
	}
	d := NewJobDetail(fc, NewJobDetailCache(), testStyles(), "99", "RUNNING", store.JobDetail{})
	d.SetSize(100, 40)

	loaded := firstMsg(d.Init()).(jobDetailLoadedMsg)
	_, usageCmd, _ := d.Update(loaded)
	if usageCmd != nil {
		t.Error("foreign running job issued a usage lookup")
	}
	if fc.LastJobUsageID != "" {
		t.Error("client usage lookup called for a foreign running job")
	}
	if !strings.Contains(d.View(), "only visible to the job's owner") {
		t.Errorf("ownership note missing, got:\n%s", d.View())
	}
}

// TestJobDetailPendingJobHasNoUsage asserts a pending job triggers no usage
// lookup: nothing has run, so there is nothing to measure.
func TestJobDetailPendingJobHasNoUsage(t *testing.T) {
	fc := &store.FakeClient{
		JobDetailData: store.JobDetail{
			Source: "scontrol",
			Fields: map[string]string{"JobState": "PENDING", "UserId": "alice(1000)"},
		},
	}
	d := NewJobDetail(fc, NewJobDetailCache(), testStyles(), "7", "PENDING", store.JobDetail{})
	d.SetSize(100, 40)

	loaded := firstMsg(d.Init()).(jobDetailLoadedMsg)
	_, usageCmd, _ := d.Update(loaded)
	if usageCmd != nil {
		t.Error("pending job issued a usage lookup")
	}
	if strings.Contains(d.View(), "Efficiency") {
		t.Errorf("pending job renders an Efficiency section:\n%s", d.View())
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
	d := NewJobDetail(fc, cache, testStyles(), "12345", "COMPLETED", store.JobDetail{})
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
	d := NewJobDetail(fc, NewJobDetailCache(), testStyles(), "1", "RUNNING", store.JobDetail{})
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
	d := NewJobDetail(&store.FakeClient{}, NewJobDetailCache(), testStyles(), "1", "RUNNING", store.JobDetail{})
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
	d := NewJobDetail(fc, NewJobDetailCache(), testStyles(), "12345", "RUNNING", store.JobDetail{})
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

// TestJobDetailFallbackOnFetchError covers the aged-out completed job: the
// controller lookup fails, but the journal-sourced fallback must render in its
// place and keep o/e delivering the recorded log paths — the whole point of
// keeping paths for jobs whose logs outlive the controller record.
func TestJobDetailFallbackOnFetchError(t *testing.T) {
	fc := &store.FakeClient{JobDetailErr: errors.New("job 9 not found")}
	fb := JournalDetail(store.HistoryJob{
		ID: "9", Name: "done", State: "COMPLETED",
		StdOut: "/l/9.out", StdErr: "/l/9.err",
	})
	d := NewJobDetail(fc, NewJobDetailCache(), testStyles(), "9", "COMPLETED", fb)
	d.SetSize(80, 24)
	d.Update(firstMsg(d.Init()))

	if d.errMsg != "" {
		t.Errorf("fallback must replace the error view, got %q", d.errMsg)
	}
	_, cmd, _ := d.Update(tea.KeyPressMsg{Code: 'o', Text: "o"})
	if open, ok := firstMsg(cmd).(OpenLogMsg); !ok || open.Path != "/l/9.out" {
		t.Fatalf("o after fallback produced %v; want OpenLogMsg for /l/9.out", firstMsg(cmd))
	}
	_, cmd, _ = d.Update(tea.KeyPressMsg{Code: 'e', Text: "e"})
	if open, ok := firstMsg(cmd).(OpenLogMsg); !ok || open.Path != "/l/9.err" {
		t.Fatalf("e after fallback produced %v; want OpenLogMsg for /l/9.err", firstMsg(cmd))
	}

	// Without a fallback the fetch error still surfaces (the prior contract).
	bare := NewJobDetail(fc, NewJobDetailCache(), testStyles(), "9", "COMPLETED", store.JobDetail{})
	bare.SetSize(80, 24)
	bare.Update(firstMsg(bare.Init()))
	if bare.errMsg == "" {
		t.Error("fetch error without a fallback must still surface")
	}
}
