package slurm

import (
	"regexp"
	"strconv"
	"strings"
)

var (
	// arrayBracket captures the spec inside array brackets, e.g. the "0-99%5" of
	// "12345_[0-99%5]".
	arrayBracket = regexp.MustCompile(`_\[([^\]]+)\]`)
	// arrayThrottle strips a trailing throttle, e.g. "%5" in "0-99%5".
	arrayThrottle = regexp.MustCompile(`(.+)%\d+$`)
	// arrayRange matches a simple "start-end" range.
	arrayRange = regexp.MustCompile(`^(\d+)-(\d+)$`)
)

// NormalizeArrayJobID strips bracket-based array range notation that scontrol and
// sacct cannot accept, while leaving single array task IDs intact. For example
// "12345_[0-99]" becomes "12345" but "12345_5" is unchanged.
func NormalizeArrayJobID(jobID string) string {
	if jobID == "" {
		return jobID
	}
	if idx := strings.Index(jobID, "_["); idx >= 0 {
		return jobID[:idx]
	}
	return jobID
}

// ParseArraySize returns the number of array tasks a job ID represents: 1 for a
// regular job or a single array task, and the expanded count for bracket
// notation. For example "12345_[0-99]" yields 100 and "12345_[0-99%5]" yields
// 100 (the throttle does not change the task count).
func ParseArraySize(jobID string) int {
	jobID = strings.TrimSpace(jobID)
	if jobID == "" {
		return 1
	}
	m := arrayBracket.FindStringSubmatch(jobID)
	if m == nil {
		return 1
	}
	return parseArraySpec(m[1])
}

// parseArraySpec parses the contents of array brackets, e.g. "0-99", "0-99%5", or
// "1,3,5,7-10", returning the number of tasks it denotes.
func parseArraySpec(spec string) int {
	if m := arrayThrottle.FindStringSubmatch(spec); m != nil {
		spec = m[1]
	}
	if strings.Contains(spec, ",") {
		return parseCommaList(spec)
	}
	return parseRange(spec)
}

// parseCommaList sums a comma-separated array spec such as "1,3,5,7-10", treating
// each bare number as one task and each "a-b" segment as a range. The result is
// at least 1.
func parseCommaList(spec string) int {
	total := 0
	for _, part := range strings.Split(spec, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		if strings.Contains(part, "-") {
			total += parseRange(part)
		} else if _, err := strconv.Atoi(part); err == nil {
			total++
		}
	}
	if total < 1 {
		return 1
	}
	return total
}

// parseRange counts the tasks in a single "start-end" range. Anything that is not
// a valid increasing range (including a bare number or malformed text) counts as
// 1.
func parseRange(spec string) int {
	spec = strings.TrimSpace(spec)
	if m := arrayRange.FindStringSubmatch(spec); m != nil {
		start, err1 := strconv.Atoi(m[1])
		end, err2 := strconv.Atoi(m[2])
		if err1 == nil && err2 == nil && end >= start {
			return end - start + 1
		}
	}
	return 1
}
