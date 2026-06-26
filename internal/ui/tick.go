package ui

import (
	"time"

	tea "charm.land/bubbletea/v2"
)

// Default refresh intervals. The fast tier drives squeue-based sections; the slow
// tier (4x the fast interval) drives the heavy batch sections. These are the
// fallback defaults; the live intervals are derived from the user config.
const (
	defaultFastInterval = 10 * time.Second
	slowIntervalFactor  = 4
)

// Intervals holds the two refresh-tier durations. A zero Intervals is invalid;
// use DefaultIntervals or build one explicitly.
type Intervals struct {
	Fast time.Duration
	Slow time.Duration
}

// DefaultIntervals returns the locked default refresh intervals (10s fast, 40s
// slow).
func DefaultIntervals() Intervals {
	return Intervals{
		Fast: defaultFastInterval,
		Slow: defaultFastInterval * slowIntervalFactor,
	}
}

// fastTickMsg fires on the fast refresh tier. It carries the time it fired so
// elapsed/age rendering can use the loop's clock.
type fastTickMsg struct{ at time.Time }

// slowTickMsg fires on the slow refresh tier.
type slowTickMsg struct{ at time.Time }

// spinnerTickInterval is the frame cadence of the loading-spinner animation
// (~10 fps). It is a conditional tier: it runs only while a section is loading
// and stops re-arming once nothing is in flight, so the UI is idle when there is
// nothing to animate.
const spinnerTickInterval = 100 * time.Millisecond

// spinnerTickMsg advances the loading-spinner animation frames.
type spinnerTickMsg struct{ at time.Time }

// spinnerTick returns a Cmd that fires a single spinnerTickMsg after d. It is
// started when a load begins and re-armed only while at least one section is
// still loading (handleSpinnerTick), so it never runs when the UI is idle.
func spinnerTick(d time.Duration) tea.Cmd {
	return tea.Tick(d, func(t time.Time) tea.Msg { return spinnerTickMsg{at: t} })
}

// fastTick returns a Cmd that fires a single fastTickMsg after d. Each tier
// re-arms only from its own handler (I2): the root model, on receiving a
// fastTickMsg, dispatches the fast fetches and calls fastTick again. It is never
// re-armed from resize/keypress, which would geometrically multiply timers.
func fastTick(d time.Duration) tea.Cmd {
	return tea.Tick(d, func(t time.Time) tea.Msg { return fastTickMsg{at: t} })
}

// slowTick returns a Cmd that fires a single slowTickMsg after d. Like fastTick,
// it is re-armed only from the slowTickMsg handler.
func slowTick(d time.Duration) tea.Cmd {
	return tea.Tick(d, func(t time.Time) tea.Msg { return slowTickMsg{at: t} })
}
