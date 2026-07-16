package ui

import (
	"errors"
	"strings"
	"testing"

	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// errBoom is a generic fetch failure for toast-level tests.
var errBoom = errors.New("boom")

// TestRecoveredToastIsSuccessStyled asserts a failing→recovered transition emits
// a success-level toast (not error), exercising the health-machine distinction
// that the charm-style toast now surfaces with green chrome.
func TestRecoveredToastIsSuccessStyled(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{UsernameStr: "alice"})

	// First, a failure to move the section into the failing state.
	a.observe(store.SectionNodes, errBoom)
	if len(a.toasts) != 1 || a.toasts[0].level != toastError {
		t.Fatalf("after failure: toasts=%+v; want one error-level toast", a.toasts)
	}

	// Then a success: the transition emits a recovered toast at success level.
	a.observe(store.SectionNodes, nil)
	if len(a.toasts) != 2 {
		t.Fatalf("after recovery: %d toasts; want 2", len(a.toasts))
	}
	if a.toasts[1].level != toastSuccess {
		t.Errorf("recovered toast level = %d; want toastSuccess", a.toasts[1].level)
	}
}

// TestToastsExpire asserts toasts auto-dismiss after toastTTL toast ticks.
func TestToastsExpire(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{UsernameStr: "alice"})
	a.pushToast("hello")
	if len(a.toasts) != 1 {
		t.Fatalf("push: %d toasts; want 1", len(a.toasts))
	}
	for i := 0; i < toastTTL; i++ {
		a.expireToasts()
	}
	if len(a.toasts) != 0 {
		t.Errorf("after %d ticks: %d toasts; want 0 (expired)", toastTTL, len(a.toasts))
	}
}

// TestRenderToastsLevels asserts the boxed renderer produces bordered output and
// the text for each level.
func TestRenderToastsLevels(t *testing.T) {
	styles := theme.BuildStyles(theme.Charm(), true)
	out := renderToasts([]toastItem{
		{text: "failed thing", level: toastError, ticks: 1},
		{text: "recovered thing", level: toastSuccess, ticks: 1},
	}, 80, styles, 0)
	if !strings.Contains(out, "failed thing") || !strings.Contains(out, "recovered thing") {
		t.Errorf("toast render missing text:\n%s", out)
	}
	// Rounded border corners should appear.
	if !strings.Contains(out, "╭") {
		t.Errorf("toast render not boxed:\n%s", out)
	}
	if renderToasts(nil, 80, styles, 0) != "" {
		t.Error("empty toast stack should render empty")
	}
}

// TestRefreshToastAnimatesAndClearsOnCompletion asserts the manual-refresh
// progress toast shows an animated spinner (frame follows the anim phase) and is
// dropped the moment the running-jobs result lands, instead of waiting out the
// toast TTL.
func TestRefreshToastAnimatesAndClearsOnCompletion(t *testing.T) {
	styles := theme.BuildStyles(theme.Charm(), true)
	tagged := []toastItem{{text: "Refreshing", level: toastInfo, ticks: toastTTL, tag: refreshToastTag}}
	if renderToasts(tagged, 80, styles, 0) == renderToasts(tagged, 80, styles, toastSpinnerDivisor) {
		t.Error("progress toast spinner did not advance with the anim phase")
	}

	a := New(store.New(), &store.FakeClient{UsernameStr: "alice"})
	a.pushToastTagged("Refreshing", toastInfo, refreshToastTag)
	// A repeated refresh replaces the progress toast instead of stacking it.
	a.pushToastTagged("Refreshing", toastInfo, refreshToastTag)
	if len(a.toasts) != 1 {
		t.Fatalf("progress toasts stacked: %d; want 1", len(a.toasts))
	}
	m, _ := a.Update(runningJobsMsg{gen: a.store.Gen(store.SectionRunningJobs)})
	a = m.(App)
	if len(a.toasts) != 0 {
		t.Errorf("progress toast survived completion: %+v", a.toasts)
	}
}

// TestRenderToastsFadeOnFinalTick asserts a toast on its last tick renders in
// the muted tone (fading out) instead of its level color.
func TestRenderToastsFadeOnFinalTick(t *testing.T) {
	styles := theme.BuildStyles(theme.Charm(), true)
	fresh := renderToasts([]toastItem{{text: "note", level: toastError, ticks: toastTTL}}, 80, styles, 0)
	fading := renderToasts([]toastItem{{text: "note", level: toastError, ticks: 1}}, 80, styles, 0)
	if fresh == fading {
		t.Error("final-tick toast should render dimmed, not identical to a fresh one")
	}
}

// TestRenderToastsCapsWidth asserts a long toast wraps inside the terminal width
// instead of overflowing it (regression for the slurmdbd notice box overflowing).
func TestRenderToastsCapsWidth(t *testing.T) {
	styles := theme.BuildStyles(theme.Charm(), true)
	long := "Job history unavailable: slurmdbd connection refused"
	for _, w := range []int{40, 30, 20} {
		out := renderToasts([]toastItem{{text: long, level: toastError, ticks: 1}}, w, styles, 0)
		if got := lipgloss.Width(out); got > w {
			t.Errorf("toast box width %d exceeds terminal width %d:\n%s", got, w, out)
		}
	}
}
