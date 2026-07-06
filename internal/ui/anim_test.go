package ui

import (
	"strings"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
)

// newAnimApp builds a minimal App for anim-tier tests.
func newAnimApp() App {
	return New(store.New(), &store.FakeClient{UsernameStr: "alice"})
}

// TestAnimTickAdvancesAndReArmsWhileFocused asserts the anim tier advances the
// shimmer phase and re-arms itself while the terminal is focused.
func TestAnimTickAdvancesAndReArmsWhileFocused(t *testing.T) {
	a := newAnimApp()
	m, cmd := a.Update(animTickMsg{at: time.Now()})
	a = m.(App)
	if cmd == nil {
		t.Error("focused anim tick must re-arm")
	}
	if a.animPhase != 1 {
		t.Errorf("animPhase = %d; want 1", a.animPhase)
	}
	if !a.frame.dirty {
		t.Error("anim tick must dirty the frame")
	}
}

// TestAnimTickStopsOnBlurAndRestartsOnFocus asserts a blurred terminal stops the
// anim tier (no re-arm, no phase advance) and a focus report restarts it exactly
// once — a backgrounded tmux pane renders zero animation frames.
func TestAnimTickStopsOnBlurAndRestartsOnFocus(t *testing.T) {
	a := newAnimApp()

	m, _ := a.Update(tea.BlurMsg{})
	a = m.(App)
	m, cmd := a.Update(animTickMsg{at: time.Now()})
	a = m.(App)
	if cmd != nil {
		t.Error("blurred anim tick must not re-arm")
	}
	if a.animActive {
		t.Error("anim tier must mark itself stopped on blur")
	}
	if a.animPhase != 0 {
		t.Errorf("blurred tick advanced the phase: %d", a.animPhase)
	}

	m, cmd = a.Update(tea.FocusMsg{})
	a = m.(App)
	if cmd == nil || !a.animActive {
		t.Error("focus must restart the anim tier")
	}
	// A duplicate focus report must not double-arm the tier.
	if _, cmd = a.Update(tea.FocusMsg{}); cmd != nil {
		t.Error("duplicate focus report double-armed the anim tier")
	}
}

// TestAnimIntervalThrottlesWhenInputIdle asserts the shimmer runs at full rate
// while the user interacts and drops to the idle crawl once input goes stale,
// so a focused-but-untouched stoei costs a fraction of the active frame rate.
func TestAnimIntervalThrottlesWhenInputIdle(t *testing.T) {
	if got := animInterval(time.Second); got != animTickInterval {
		t.Errorf("active interval = %v; want %v", got, animTickInterval)
	}
	if got := animInterval(animIdleAfter + time.Second); got != animIdleInterval {
		t.Errorf("idle interval = %v; want %v", got, animIdleInterval)
	}

	// The handler feeds the tick's own timestamp into the throttle, so the idle
	// decision is deterministic against lastInput.
	a := newAnimApp()
	a.lastInput = time.Date(2026, 7, 6, 12, 0, 0, 0, time.UTC)
	m, cmd := a.Update(animTickMsg{at: a.lastInput.Add(3 * time.Minute)})
	a = m.(App)
	if cmd == nil || a.animPhase != 1 {
		t.Error("idle anim tick must still advance and re-arm (at the crawl rate)")
	}
}

// TestUpdateHintShownForNewerRelease asserts a release build shows the status
// bar update hint when the startup check finds a newer tag, and that dev builds
// and same-version results never do.
func TestUpdateHintShownForNewerRelease(t *testing.T) {
	a := newAnimApp().WithVersion("v0.10.0")
	m, _ := a.Update(latestReleaseMsg{tag: "v0.11.0"})
	a = m.(App)
	if a.latestRelease != "v0.11.0" {
		t.Fatalf("latestRelease = %q; want v0.11.0", a.latestRelease)
	}
	if f := a.footer(); !strings.Contains(f, "v0.11.0 available") || !strings.Contains(f, "stoei update") {
		t.Errorf("footer missing update hint:\n%s", f)
	}

	same := newAnimApp().WithVersion("v0.11.0")
	m, _ = same.Update(latestReleaseMsg{tag: "v0.11.0"})
	if got := m.(App).latestRelease; got != "" {
		t.Errorf("up-to-date build set a hint: %q", got)
	}

	dev := newAnimApp() // no version → dev build
	m, _ = dev.Update(latestReleaseMsg{tag: "v99.0.0"})
	if got := m.(App).latestRelease; got != "" {
		t.Errorf("dev build set a hint: %q", got)
	}
}

// TestBlurNeverGatesDataRefresh asserts the fast tick still dispatches fetches
// while the terminal is blurred: only cosmetics are focus-gated.
func TestBlurNeverGatesDataRefresh(t *testing.T) {
	a := newAnimApp()
	m, _ := a.Update(tea.BlurMsg{})
	a = m.(App)
	if _, cmd := a.Update(fastTickMsg{at: time.Now()}); cmd == nil {
		t.Error("fast tick must keep dispatching while blurred")
	}
}
