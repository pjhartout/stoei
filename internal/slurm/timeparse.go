package slurm

import (
	"strconv"
	"strings"
	"time"
)

// slurmTimestampLayout is the SLURM timestamp format "YYYY-MM-DDTHH:MM:SS".
const slurmTimestampLayout = "2006-01-02T15:04:05"

// unknownTimestamps are the values SLURM uses to mean "no timestamp". Comparison
// is case-insensitive on the trimmed value. Ports wait_time.UNKNOWN_TIMESTAMP_VALUES
// (extended with the lower-case variants the wait-time getter also filters on).
var unknownTimestamps = map[string]struct{}{
	"unknown": {},
	"none":    {},
	"n/a":     {},
	"":        {},
}

// isUnknownTimestamp reports whether s is one of SLURM's unknown-timestamp
// sentinels (case-insensitive, whitespace-trimmed).
func isUnknownTimestamp(s string) bool {
	_, ok := unknownTimestamps[strings.ToLower(strings.TrimSpace(s))]
	return ok
}

// ParseElapsedToSeconds parses a SLURM elapsed-time string into seconds. It
// accepts the "D-HH:MM:SS", "HH:MM:SS", "MM:SS", and "SS" forms and returns 0 for
// empty or malformed input. Ports energy.parse_elapsed_to_seconds.
func ParseElapsedToSeconds(elapsed string) float64 {
	elapsed = strings.TrimSpace(elapsed)
	if elapsed == "" {
		return 0
	}

	var days int
	if idx := strings.Index(elapsed, "-"); idx >= 0 {
		d, err := strconv.Atoi(elapsed[:idx])
		if err != nil {
			return 0
		}
		days = d
		if idx+1 < len(elapsed) {
			elapsed = elapsed[idx+1:]
		} else {
			elapsed = "0"
		}
	}

	parts := strings.Split(elapsed, ":")
	var hours, minutes int
	var seconds float64
	var err error
	switch len(parts) {
	case 3:
		if hours, err = strconv.Atoi(parts[0]); err != nil {
			return 0
		}
		if minutes, err = strconv.Atoi(parts[1]); err != nil {
			return 0
		}
		if seconds, err = strconv.ParseFloat(parts[2], 64); err != nil {
			return 0
		}
	case 2:
		if minutes, err = strconv.Atoi(parts[0]); err != nil {
			return 0
		}
		if seconds, err = strconv.ParseFloat(parts[1], 64); err != nil {
			return 0
		}
	case 1:
		if seconds, err = strconv.ParseFloat(parts[0], 64); err != nil {
			return 0
		}
	default:
		return 0
	}

	total := float64(days*86400+hours*3600+minutes*60) + seconds
	if total < 0 {
		return 0
	}
	return total
}

// ParseSlurmTimestamp parses a SLURM timestamp into a time.Time. It returns
// ok=false for unknown sentinels (Unknown/None/N/A/empty) and for unparseable
// input. Ports wait_time.parse_slurm_timestamp.
func ParseSlurmTimestamp(s string) (time.Time, bool) {
	if isUnknownTimestamp(s) {
		return time.Time{}, false
	}
	t, err := time.Parse(slurmTimestampLayout, strings.TrimSpace(s))
	if err != nil {
		return time.Time{}, false
	}
	return t, true
}

// WaitTimeSeconds returns the seconds elapsed between a job's submit and start
// timestamps. It returns ok=false when either timestamp is unknown/unparseable or
// when the result would be negative (start before submit, a data error). Ports
// wait_time.calculate_wait_time_seconds.
func WaitTimeSeconds(submit, start string) (float64, bool) {
	submitT, ok := ParseSlurmTimestamp(submit)
	if !ok {
		return 0, false
	}
	startT, ok := ParseSlurmTimestamp(start)
	if !ok {
		return 0, false
	}
	secs := startT.Sub(submitT).Seconds()
	if secs < 0 {
		return 0, false
	}
	return secs, true
}
