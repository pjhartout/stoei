package modals

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
)

// writeTempLog writes lines to a temp file and returns its path.
func writeTempLog(t *testing.T, lines []string) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "job.log")
	if err := os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0o600); err != nil {
		t.Fatalf("write temp log: %v", err)
	}
	return path
}

// TestLogViewerInitIssuesCmdNotBlockingRead asserts that opening the viewer
// issues the file read as a Cmd (I1) rather than reading inline in Init/Update.
func TestLogViewerInitIssuesCmdNotBlockingRead(t *testing.T) {
	path := writeTempLog(t, []string{"alpha", "beta", "gamma"})
	v := NewLogViewer(testStyles(), path, "stdout", 0)
	v.SetSize(80, 24)

	cmd := v.Init()
	if cmd == nil {
		t.Fatal("Init must issue the file read as a Cmd")
	}
	// The viewer holds no content until the load message is delivered.
	if len(v.rawLines) != 0 {
		t.Error("file must not be read inline; rawLines should be empty before the load msg")
	}

	msg := firstMsg(cmd)
	loaded, ok := msg.(logLoadedMsg)
	if !ok {
		t.Fatalf("first Cmd message = %T; want logLoadedMsg", msg)
	}
	v.Update(loaded)
	if len(v.rawLines) != 3 {
		t.Errorf("loaded %d lines; want 3", len(v.rawLines))
	}
	if !strings.Contains(v.View(), "beta") {
		t.Errorf("viewer did not render file content, got:\n%s", v.View())
	}
}

// TestLogViewerTailsLargeFile asserts a file longer than maxLines is tailed to
// the last maxLines lines and labeled truncated.
func TestLogViewerTailsLargeFile(t *testing.T) {
	var lines []string
	for i := 1; i <= 50; i++ {
		lines = append(lines, fmt.Sprintf("line-%d", i))
	}
	path := writeTempLog(t, lines)

	v := NewLogViewer(testStyles(), path, "stdout", 10)
	v.SetSize(80, 24)
	v.Update(firstMsg(v.Init()))

	if !v.truncated {
		t.Error("a file longer than maxLines should be truncated")
	}
	if len(v.rawLines) != 10 {
		t.Errorf("tail loaded %d lines; want 10", len(v.rawLines))
	}
	if v.rawLines[0] != "line-41" || v.rawLines[9] != "line-50" {
		t.Errorf("tail window = %q..%q; want line-41..line-50", v.rawLines[0], v.rawLines[9])
	}
	if v.startLine != 41 {
		t.Errorf("startLine = %d; want 41", v.startLine)
	}
}

// TestLogViewerSearchHighlightsAndNavigates asserts / + Enter finds matches and
// reports the count; n/N navigate without error.
func TestLogViewerSearchHighlightsAndNavigates(t *testing.T) {
	path := writeTempLog(t, []string{"foo", "bar foo", "baz", "foo end"})
	v := NewLogViewer(testStyles(), path, "stdout", 0)
	v.SetSize(80, 24)
	v.Update(firstMsg(v.Init()))

	// Open search, type "foo", submit.
	v.Update(tea.KeyPressMsg{Code: '/', Text: "/"})
	for _, r := range "foo" {
		v.Update(tea.KeyPressMsg{Code: r, Text: string(r)})
	}
	_, cmd, _ := v.Update(tea.KeyPressMsg{Code: tea.KeyEnter})

	if v.matchCount != 3 {
		t.Errorf("matchCount = %d; want 3", v.matchCount)
	}
	if msg, ok := firstMsg(cmd).(LogToastMsg); !ok || !strings.Contains(msg.Text, "3 matches") {
		t.Errorf("search did not toast the match count, got %v", firstMsg(cmd))
	}

	// Navigation must not panic and should keep the highlights.
	v.Update(tea.KeyPressMsg{Code: 'n', Text: "n"})
	v.Update(tea.KeyPressMsg{Code: 'N', Text: "N"})
}

// flattenMsgs runs a Cmd and recursively flattens any nested tea.Batch layers,
// returning every message produced, so assertions never depend on batch shape
// or child ordering.
func flattenMsgs(cmd tea.Cmd) []tea.Msg {
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
		out = append(out, flattenMsgs(c)...)
	}
	return out
}

// TestLogViewerReloadIssuesCmd asserts r re-issues the read as a Cmd: the fresh
// logLoadedMsg must appear somewhere in whatever batch reload returns.
func TestLogViewerReloadIssuesCmd(t *testing.T) {
	path := writeTempLog(t, []string{"one"})
	v := NewLogViewer(testStyles(), path, "stdout", 0)
	v.SetSize(80, 24)
	v.Update(firstMsg(v.Init()))

	_, cmd, done := v.Update(tea.KeyPressMsg{Code: 'r', Text: "r"})
	if done {
		t.Error("reload should not close the viewer")
	}
	if cmd == nil {
		t.Fatal("reload must issue a load Cmd")
	}
	found := false
	for _, m := range flattenMsgs(cmd) {
		if _, ok := m.(logLoadedMsg); ok {
			found = true
		}
	}
	if !found {
		t.Error("reload Cmd did not re-read the file")
	}
}

// TestLogViewerMissingFileShowsError asserts a missing file produces a load error
// rather than panicking.
func TestLogViewerMissingFileShowsError(t *testing.T) {
	v := NewLogViewer(testStyles(), "/no/such/file.log", "stderr", 0)
	v.SetSize(80, 24)
	v.Update(firstMsg(v.Init()))
	if v.loadErr == "" {
		t.Error("missing file should set a load error")
	}
}

// TestLogViewerEscCloses asserts esc closes the viewer (when not searching).
func TestLogViewerEscCloses(t *testing.T) {
	path := writeTempLog(t, []string{"x"})
	v := NewLogViewer(testStyles(), path, "stdout", 0)
	v.SetSize(80, 24)
	v.Update(firstMsg(v.Init()))
	_, _, done := v.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
	if !done {
		t.Error("esc should close the log viewer")
	}
}
