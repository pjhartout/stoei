package tabs

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

func testStatusStyles() theme.Styles { return theme.BuildStyles(theme.Charm(), true) }

// TestSectionStatusDebouncesSpinner asserts a fast load that completes within the
// debounce window never shows a spinner, while a slow load shows one after the
// window elapses.
func TestSectionStatusDebouncesSpinner(t *testing.T) {
	now := time.Unix(0, 0)
	s := sectionStatus{now: func() time.Time { return now }}
	styles := testStatusStyles()

	// Loading with no data starts the debounce timer.
	s.observe(store.StateLoading, false)

	// Within the debounce window: no spinner.
	now = now.Add(spinnerDebounce / 2)
	if line, ok := s.statusLine(store.StateLoading, false, nil, styles); ok {
		t.Errorf("spinner shown within debounce window: %q", line)
	}

	// Past the debounce window: spinner appears.
	now = now.Add(spinnerDebounce)
	line, ok := s.statusLine(store.StateLoading, false, nil, styles)
	if !ok {
		t.Fatal("spinner not shown after debounce window elapsed")
	}
	if !strings.Contains(line, "Loading") {
		t.Errorf("loading line = %q; want a Loading indicator", line)
	}
}

// TestSectionStatusHasDataSuppresses asserts no spinner/badge is shown once the
// section has data, even while a background refresh is loading.
func TestSectionStatusHasDataSuppresses(t *testing.T) {
	now := time.Unix(100, 0)
	s := sectionStatus{now: func() time.Time { return now }}
	s.observe(store.StateLoading, true) // loading, but data already present
	if _, ok := s.statusLine(store.StateLoading, true, nil, testStatusStyles()); ok {
		t.Error("status line shown while data present; want suppressed")
	}
}

// TestSectionStatusErrorBadge asserts a failed section with no data renders an
// error badge carrying the error text.
func TestSectionStatusErrorBadge(t *testing.T) {
	now := time.Unix(200, 0)
	s := sectionStatus{now: func() time.Time { return now }}
	err := errors.New("squeue not found")
	line, ok := s.statusLine(store.StateError, false, err, testStatusStyles())
	if !ok {
		t.Fatal("error badge not shown for failed section")
	}
	if !strings.Contains(line, "squeue not found") {
		t.Errorf("error badge = %q; want the error text", line)
	}
}

// TestSectionStatusLoadedEmpty asserts a loaded-but-empty section (the user
// simply has no rows) shows neither a spinner nor a badge.
func TestSectionStatusLoadedEmpty(t *testing.T) {
	s := newSectionStatus()
	s.observe(store.StateLoaded, false)
	if _, ok := s.statusLine(store.StateLoaded, false, nil, testStatusStyles()); ok {
		t.Error("status line shown for loaded-empty section; want none")
	}
}
