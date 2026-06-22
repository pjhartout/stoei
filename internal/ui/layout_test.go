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
		a.frame.dirty = true
		for _, ln := range strings.Split(a.View().Content, "\n") {
			if got := lipgloss.Width(ln); got > w {
				t.Errorf("term width %d: rendered line is %d wide (overflow):\n%q", w, got, ln)
				break
			}
		}
	}
}
