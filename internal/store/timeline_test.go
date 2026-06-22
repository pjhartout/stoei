package store

import (
	"testing"
	"time"
)

// pinTimelineClock pins timelineNow to a fixed instant for the duration of the
// test so "today" is deterministic.
func pinTimelineClock(t *testing.T, now time.Time) {
	t.Helper()
	prev := timelineNow
	timelineNow = func() time.Time { return now }
	t.Cleanup(func() { timelineNow = prev })
}

func TestFormatCompactTimeline(t *testing.T) {
	// Pin "today" to 2024-01-15 so same-day timestamps render HH:MM.
	pinTimelineClock(t, time.Date(2024, 1, 15, 23, 0, 0, 0, time.Local))

	cases := []struct {
		name               string
		submit, start, end string
		state              string
		restarts           int
		want               string
	}{
		{
			name:  "no submit time",
			state: "RUNNING",
			want:  "—",
		},
		{
			name:   "pending shows hourglass",
			submit: "2024-01-15T14:30:00",
			state:  "PENDING",
			want:   "14:30 ⏳",
		},
		{
			name:   "running with start",
			submit: "2024-01-15T14:30:00",
			start:  "2024-01-15T14:35:00",
			state:  "RUNNING",
			want:   "14:30 → 14:35",
		},
		{
			name:   "running without start shows hourglass",
			submit: "2024-01-15T14:30:00",
			state:  "RUNNING",
			want:   "14:30 ⏳",
		},
		{
			name:   "completed full timeline",
			submit: "2024-01-15T14:30:00",
			start:  "2024-01-15T14:35:00",
			end:    "2024-01-15T15:00:00",
			state:  "COMPLETED",
			want:   "14:30 → 14:35 → 15:00",
		},
		{
			name:   "completed without start",
			submit: "2024-01-15T14:30:00",
			end:    "2024-01-15T15:00:00",
			state:  "COMPLETED",
			want:   "14:30 → 15:00",
		},
		{
			name:   "has start only",
			submit: "2024-01-15T14:30:00",
			start:  "2024-01-15T14:35:00",
			state:  "SUSPENDED",
			want:   "14:30 → 14:35",
		},
		{
			name:   "submit only",
			submit: "2024-01-15T14:30:00",
			state:  "CONFIGURING",
			want:   "14:30",
		},
		{
			name:     "requeue indicator appended",
			submit:   "2024-01-15T14:30:00",
			start:    "2024-01-15T14:35:00",
			end:      "2024-01-15T15:00:00",
			state:    "FAILED",
			restarts: 3,
			want:     "14:30 → 14:35 → 15:00  ↻ 3",
		},
		{
			name:   "other day uses MM-DD prefix",
			submit: "2024-01-10T09:00:00",
			start:  "2024-01-10T09:05:00",
			end:    "2024-01-10T10:00:00",
			state:  "COMPLETED",
			want:   "01-10 09:00 → 01-10 09:05 → 01-10 10:00",
		},
		{
			name:   "unknown sentinels treated as empty",
			submit: "2024-01-15T14:30:00",
			start:  "Unknown",
			end:    "N/A",
			state:  "RUNNING",
			want:   "14:30 ⏳",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := FormatCompactTimeline(tc.submit, tc.start, tc.end, tc.state, tc.restarts)
			if got != tc.want {
				t.Errorf("FormatCompactTimeline(%q,%q,%q,%q,%d) = %q; want %q",
					tc.submit, tc.start, tc.end, tc.state, tc.restarts, got, tc.want)
			}
		})
	}
}

func TestParseRestarts(t *testing.T) {
	cases := map[string]int{
		"":    0,
		"0":   0,
		"3":   3,
		"12":  12,
		" 2 ": 2,
		"1.0": 0,
		"abc": 0,
		"-1":  0,
	}
	for in, want := range cases {
		if got := parseRestarts(in); got != want {
			t.Errorf("parseRestarts(%q) = %d; want %d", in, got, want)
		}
	}
}

// TestMergedJobTimelineSurfacesRequeues verifies the merged job carries the
// sacct Restart count and submit/start/end through to the Timeline cell — the
// only render site for the parsed requeue stats.
func TestMergedJobTimelineSurfacesRequeues(t *testing.T) {
	pinTimelineClock(t, time.Date(2024, 1, 15, 23, 0, 0, 0, time.Local))
	s := New()
	s.HistoryJobs = []HistoryJob{
		{
			ID: "C", Name: "x", State: "FAILED", Elapsed: "0:10",
			Restart: "2",
			Submit:  "2024-01-15T14:30:00",
			Start:   "2024-01-15T14:35:00",
			End:     "2024-01-15T15:00:00",
		},
	}
	merged := s.MergedJobs()
	if len(merged) != 1 {
		t.Fatalf("len = %d, want 1", len(merged))
	}
	if merged[0].Restarts != 2 {
		t.Errorf("Restarts = %d, want 2", merged[0].Restarts)
	}
	want := "14:30 → 14:35 → 15:00  ↻ 2"
	if got := merged[0].Timeline(); got != want {
		t.Errorf("Timeline() = %q, want %q", got, want)
	}
}
