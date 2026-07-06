package tabs

import (
	"strings"
	"testing"
)

func TestHScrollWindowPassthroughWhenContentFits(t *testing.T) {
	view := "abc\ndef"
	if got := hscrollWindow(view, 0, 10, 20); got != view {
		t.Errorf("expected passthrough, got %q", got)
	}
}

func TestHScrollWindowCutsEveryLineToPane(t *testing.T) {
	view := "0123456789\nabcdefghij"
	got := hscrollWindow(view, 4, 10, 4)
	want := "4567\nefgh"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
	for _, line := range strings.Split(got, "\n") {
		if len(line) > 4 {
			t.Errorf("line %q wider than pane", line)
		}
	}
}

func TestClampHScroll(t *testing.T) {
	if got := clampHScroll(100, 30, 20); got != 10 {
		t.Errorf("over-scroll: got %d, want 10", got)
	}
	if got := clampHScroll(-5, 30, 20); got != 0 {
		t.Errorf("negative: got %d, want 0", got)
	}
	if got := clampHScroll(8, 20, 40); got != 0 {
		t.Errorf("content fits: got %d, want 0", got)
	}
}
