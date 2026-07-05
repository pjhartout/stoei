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
	if len(a.toasts) != 1 || a.toasts[0].level != toastErrorLevel {
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
		{text: "failed thing", level: toastErrorLevel, ticks: 1},
		{text: "recovered thing", level: toastSuccess, ticks: 1},
	}, 80, styles)
	if !strings.Contains(out, "failed thing") || !strings.Contains(out, "recovered thing") {
		t.Errorf("toast render missing text:\n%s", out)
	}
	// Rounded border corners should appear.
	if !strings.Contains(out, "╭") {
		t.Errorf("toast render not boxed:\n%s", out)
	}
	if renderToasts(nil, 80, styles) != "" {
		t.Error("empty toast stack should render empty")
	}
}

// TestRenderToastsCapsWidth asserts a long toast wraps inside the terminal width
// instead of overflowing it (regression for the slurmdbd notice box overflowing).
func TestRenderToastsCapsWidth(t *testing.T) {
	styles := theme.BuildStyles(theme.Charm(), true)
	long := "Job history unavailable: slurmdbd connection refused"
	for _, w := range []int{40, 30, 20} {
		out := renderToasts([]toastItem{{text: long, level: toastErrorLevel, ticks: 1}}, w, styles)
		if got := lipgloss.Width(out); got > w {
			t.Errorf("toast box width %d exceeds terminal width %d:\n%s", got, w, out)
		}
	}
}
