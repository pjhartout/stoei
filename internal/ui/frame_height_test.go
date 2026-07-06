package ui

import (
	"strings"
	"testing"

	"github.com/pjhartout/stoei/internal/store"
)

// TestFrameFillsTerminalHeight asserts every tab composes to exactly the
// terminal height, so the footer sits on the last row with no blank gap
// beneath it, even when a tab renders shorter than its height budget.
func TestFrameFillsTerminalHeight(t *testing.T) {
	fc := &store.FakeClient{UsernameStr: "alice", RunningJobsData: []store.RunningJob{
		{ID: "1", Name: "job", State: "RUNNING", Time: "1:00", Nodes: "1", NodeList: "n1"},
	}}
	a := newTestApp(t, fc)
	a.availChecked = true
	a.store.SetRunningJobs(fc.RunningJobsData, a.store.NextGen(store.SectionRunningJobs), nil)
	a.jobs.Refresh()

	for tab := tabIndex(0); tab < numTabs; tab++ {
		a.active = tab
		for _, sz := range [][2]int{{80, 24}, {120, 40}} {
			a.width, a.height = sz[0], sz[1]
			a.fanoutSize()
			a.frame.invalidate()
			if lines := strings.Count(a.View().Content, "\n") + 1; lines != sz[1] {
				t.Errorf("tab %d %dx%d: frame is %d lines, want %d", tab, sz[0], sz[1], lines, sz[1])
			}
		}
	}
}
