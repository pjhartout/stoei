package ui

import (
	"strings"
	"testing"

	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
)

// TestActiveTabClippedToWidth asserts the composed view never exceeds the
// terminal width, even when the active tab's table is wider than its panel: a
// wide table must be clipped at the panel edge, not render at its full natural
// width and overflow past the sidebar / off the screen.
func TestActiveTabClippedToWidth(t *testing.T) {
	fc := &store.FakeClient{UsernameStr: "alice", RunningJobsData: []store.RunningJob{
		{ID: "5098105_[0-99%10]", Name: "very-long-experiment-name-v3-final", State: "RUNNING", Time: "1:23:00", Nodes: "8", NodeList: "node[001-008]"},
	}}
	a := newTestApp(t, fc)
	a.availChecked = true
	a.store.SetRunningJobs(fc.RunningJobsData, a.store.NextGen(store.SectionRunningJobs), nil)
	a.jobs.Refresh()

	for _, w := range []int{120, 100, 90} {
		a.width, a.height = w, 26
		a.fanoutSize()
		a.frame.invalidate()
		for _, ln := range strings.Split(a.View().Content, "\n") {
			if got := lipgloss.Width(ln); got > w {
				t.Errorf("term width %d: rendered line is %d wide (overflow):\n%q", w, got, ln)
				break
			}
		}
	}
}

// TestToastDoesNotOverflowHeight asserts a toast (which may wrap to several lines
// on a narrow terminal) is trimmed into the frame so its box never spills off the
// bottom of the screen, while staying visible.
func TestToastDoesNotOverflowHeight(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{UsernameStr: "alice"})
	a.availChecked = true
	a.toasts = []toastItem{
		{text: "Job history unavailable: slurmdbd connection refused", level: toastErrorLevel, ticks: 1},
	}
	for _, sz := range [][2]int{{80, 24}, {40, 18}, {120, 30}, {60, 16}} {
		a.width, a.height = sz[0], sz[1]
		a.fanoutSize()
		a.frame.invalidate()
		out := a.View().Content
		if lines := strings.Count(out, "\n") + 1; lines > sz[1] {
			t.Errorf("term %dx%d: %d rendered lines exceed terminal height", sz[0], sz[1], lines)
		}
		if !strings.Contains(out, "slurmdbd connection refused") {
			t.Errorf("term %dx%d: toast text not visible", sz[0], sz[1])
		}
	}
}
