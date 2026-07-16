package ui

import (
	"time"

	tea "charm.land/bubbletea/v2"
)

// Default refresh intervals. The fast tier drives squeue-based sections; the slow
// tier (4x the fast interval) drives the heavy batch sections. These are the
// fallback defaults; the live intervals are derived from the user config.
const (
	defaultFastInterval = time.Minute
	slowIntervalFactor  = 4
)

// Intervals holds the two refresh-tier durations. A zero Intervals is invalid;
// the live values are derived from the user config (intervalsFromConfig).
type Intervals struct {
	Fast time.Duration
	Slow time.Duration
}

// fastTickMsg fires on the fast refresh tier.
type fastTickMsg struct{}

// slowTickMsg fires on the slow refresh tier.
type slowTickMsg struct{}

// toastTickInterval is the cadence of toast expiry. Toasts age in ticks of this
// tier rather than the fast tier so their ~20s lifetime stays independent of the
// configured refresh interval (at a 60s fast tick a toast would linger minutes).
const toastTickInterval = 10 * time.Second

// toastTickMsg drives toast expiry.
type toastTickMsg struct{}

// toastTick returns a Cmd that fires a single toastTickMsg after d. Like the
// other tiers it is re-armed only from its own handler.
func toastTick(d time.Duration) tea.Cmd {
	return tea.Tick(d, func(time.Time) tea.Msg { return toastTickMsg{} })
}

// spinnerTickInterval is the frame cadence of the loading-spinner animation
// (~10 fps). It is a conditional tier: it runs only while a section is loading
// and stops re-arming once nothing is in flight, so the UI is idle when there is
// nothing to animate.
const spinnerTickInterval = 100 * time.Millisecond

// spinnerTickMsg advances the loading-spinner animation frames.
type spinnerTickMsg struct{}

// spinnerTick returns a Cmd that fires a single spinnerTickMsg after d. It is
// started when a load begins and re-armed only while at least one section is
// still loading (handleSpinnerTick), so it never runs when the UI is idle.
func spinnerTick(d time.Duration) tea.Cmd {
	return tea.Tick(d, func(time.Time) tea.Msg { return spinnerTickMsg{} })
}

// animTickInterval is the frame cadence of the chrome shimmer (~30 fps; the
// shimmer moves in sub-rune gradient steps so the extra frames buy smoothness,
// not speed). It is a conditional tier: it re-arms only while the terminal
// reports focus, so a stoei sitting in a background tmux pane or window renders
// zero animation frames. Only cosmetics are focus-gated — data refresh never is.
const animTickInterval = 33 * time.Millisecond

// animIdleAfter is how long without user input the shimmer runs at full rate; a
// focused-but-untouched stoei (a dashboard left on a login node) then drops to
// animIdleInterval (~4 fps crawl) and snaps back on the next keypress or focus.
const (
	animIdleAfter    = 2 * time.Minute
	animIdleInterval = 250 * time.Millisecond
)

// animInterval picks the shimmer frame interval from the time since the last
// user input: full rate while the user is interacting, the idle crawl after.
func animInterval(sinceInput time.Duration) time.Duration {
	if sinceInput > animIdleAfter {
		return animIdleInterval
	}
	return animTickInterval
}

// animTickMsg advances the chrome shimmer animation.
type animTickMsg struct{ at time.Time }

// animTick returns a Cmd that fires a single animTickMsg after d. It is armed at
// startup and on FocusMsg, and re-armed only from its own handler while focused.
func animTick(d time.Duration) tea.Cmd {
	return tea.Tick(d, func(t time.Time) tea.Msg { return animTickMsg{at: t} })
}

// fastTick returns a Cmd that fires a single fastTickMsg after d. Each tier
// re-arms only from its own handler (I2): the root model, on receiving a
// fastTickMsg, dispatches the fast fetches and calls fastTick again. It is never
// re-armed from resize/keypress, which would geometrically multiply timers.
func fastTick(d time.Duration) tea.Cmd {
	return tea.Tick(d, func(time.Time) tea.Msg { return fastTickMsg{} })
}

// slowTick returns a Cmd that fires a single slowTickMsg after d. Like fastTick,
// it is re-armed only from the slowTickMsg handler.
func slowTick(d time.Duration) tea.Cmd {
	return tea.Tick(d, func(time.Time) tea.Msg { return slowTickMsg{} })
}
