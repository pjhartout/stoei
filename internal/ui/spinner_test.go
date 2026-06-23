package ui

import (
	"testing"
	"time"

	"github.com/pjhartout/stoei/internal/store"
)

// TestSpinnerTickAnimatesWhileLoadingThenStops asserts the loading-spinner tick
// marks the frame dirty (so the spinner re-renders its next frame) and re-arms
// while a section is loading, then stops re-arming once nothing is in flight — so
// the UI is idle when there is nothing to animate.
func TestSpinnerTickAnimatesWhileLoadingThenStops(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{UsernameStr: "alice"})
	a.spinnerActive = true
	a.store.SetLoading(store.SectionRunningJobs, a.store.NextGen(store.SectionRunningJobs))

	a.frame.dirty = false
	m, cmd := a.Update(spinnerTickMsg{at: time.Now()})
	a = m.(App)
	if !a.frame.dirty {
		t.Error("spinner tick should mark the frame dirty so the spinner re-renders")
	}
	if cmd == nil {
		t.Error("spinner tick should re-arm while a section is loading")
	}
	if !a.spinnerActive {
		t.Error("spinnerActive should stay true while loading")
	}

	// The section finishes loading -> idle.
	a.store.SetRunningJobs(nil, a.store.NextGen(store.SectionRunningJobs), nil)
	m, cmd = a.Update(spinnerTickMsg{at: time.Now()})
	a = m.(App)
	if cmd != nil {
		t.Error("spinner tick should not re-arm when nothing is loading")
	}
	if a.spinnerActive {
		t.Error("spinnerActive should be cleared when idle")
	}

	// A new load restarts the tick via the ensureSpinner path the tick handlers use.
	a.store.SetLoading(store.SectionRunningJobs, a.store.NextGen(store.SectionRunningJobs))
	if a.ensureSpinner() == nil {
		t.Error("ensureSpinner should restart the tick when a new load begins")
	}
}
