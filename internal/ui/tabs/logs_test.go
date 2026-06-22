package tabs

import (
	"strings"
	"testing"
	"time"

	"github.com/pjhartout/stoei/internal/ui/components"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

func TestLogsRendersRingEntries(t *testing.T) {
	ring := components.NewLogRing(10)
	ts := time.Date(2024, 1, 2, 13, 30, 15, 0, time.UTC)
	ring.Append("INFO", "started refresh", ts)
	ring.Append("ERROR", "sacct failed", ts)

	l := NewLogs(ring, theme.BuildStyles(theme.Charm(), true))
	l.SetSize(80, 10)
	l.Refresh()
	view := l.View()

	for _, want := range []string{"13:30:15", "INFO", "started refresh", "ERROR", "sacct failed"} {
		if !strings.Contains(view, want) {
			t.Errorf("logs view missing %q; view:\n%s", want, view)
		}
	}
}

func TestLogsEmptyShowsPlaceholder(t *testing.T) {
	l := NewLogs(components.NewLogRing(10), theme.BuildStyles(theme.Charm(), true))
	l.SetSize(80, 10)
	if !strings.Contains(l.View(), "No log entries") {
		t.Errorf("empty logs should show placeholder; view:\n%s", l.View())
	}
}

func TestLogRingEvictsOldest(t *testing.T) {
	ring := components.NewLogRing(2)
	ts := time.Now()
	ring.Append("INFO", "one", ts)
	ring.Append("INFO", "two", ts)
	ring.Append("INFO", "three", ts)

	got := ring.Last(0)
	if len(got) != 2 {
		t.Fatalf("ring len = %d; want 2 (capacity)", len(got))
	}
	if got[0].Message != "two" || got[1].Message != "three" {
		t.Errorf("ring kept %q,%q; want two,three", got[0].Message, got[1].Message)
	}
}
