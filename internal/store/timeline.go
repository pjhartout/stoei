package store

import (
	"strconv"
	"strings"
	"time"
)

// timelineNow is the clock used to decide whether a timestamp falls on "today"
// for the compact format. It is a package var so tests can pin it; production
// uses time.Now.
var timelineNow = time.Now

// parseRestarts parses a history job's Restart field into an int, returning 0
// when it is not a plain non-negative integer.
func parseRestarts(s string) int {
	s = strings.TrimSpace(s)
	if s == "" {
		return 0
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return 0
		}
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return 0
	}
	return n
}

// formatCompactTime formats a SLURM timestamp ("2024-01-15T14:30:00") to a
// compact display: "HH:MM" if it is today, "MM-DD HH:MM" otherwise. Empty or
// unparseable input (including the sentinels Unknown/N/A/None) yields "".
func formatCompactTime(ts string) string {
	t := strings.TrimSpace(ts)
	switch strings.ToLower(t) {
	case "", "unknown", "n/a", "none":
		return ""
	}
	parsed, err := time.ParseInLocation("2006-01-02T15:04:05", t, time.Local)
	if err != nil {
		return ""
	}
	if sameDay(parsed, timelineNow()) {
		return parsed.Format("15:04")
	}
	return parsed.Format("01-02 15:04")
}

// sameDay reports whether a and b fall on the same calendar day.
func sameDay(a, b time.Time) bool {
	ay, am, ad := a.Date()
	by, bm, bd := b.Date()
	return ay == by && am == bm && ad == bd
}

// FormatCompactTimeline renders the submit/start/end timestamps into a compact
// timeline cell for the Jobs table, with a pending hourglass and a "↻ N" requeue
// indicator:
//   - no submit time -> "—"
//   - PENDING        -> "submit ⏳"
//   - RUNNING        -> "submit → start" (or "submit ⏳" when start unknown)
//   - has end        -> "submit → start → end" (or "submit → end" when no start)
//   - has start only -> "submit → start"
//   - else           -> "submit"
//
// A trailing "  ↻ N" is appended when restarts > 0.
func FormatCompactTimeline(submit, start, end, state string, restarts int) string {
	submitFmt := formatCompactTime(submit)
	startFmt := formatCompactTime(start)
	endFmt := formatCompactTime(end)

	if submitFmt == "" {
		return "—"
	}

	stateUpper := strings.ToUpper(state)
	var result string
	switch {
	case strings.Contains(stateUpper, "PENDING"):
		result = submitFmt + " ⏳"
	case strings.Contains(stateUpper, "RUNNING"):
		if startFmt != "" {
			result = submitFmt + " → " + startFmt
		} else {
			result = submitFmt + " ⏳"
		}
	case endFmt != "":
		if startFmt != "" {
			result = submitFmt + " → " + startFmt + " → " + endFmt
		} else {
			result = submitFmt + " → " + endFmt
		}
	case startFmt != "":
		result = submitFmt + " → " + startFmt
	default:
		result = submitFmt
	}

	if restarts > 0 {
		result += "  ↻ " + strconv.Itoa(restarts)
	}
	return result
}

// Timeline renders the compact timeline cell for a merged job, delegating to
// FormatCompactTimeline. It is the single surfacing site for the parsed requeue
// count.
func (j MergedJob) Timeline() string {
	return FormatCompactTimeline(j.SubmitTime, j.StartTime, j.EndTime, j.State, j.Restarts)
}
