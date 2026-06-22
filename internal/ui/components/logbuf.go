package components

import (
	"strings"
	"sync"
	"time"
)

// DefaultMaxLogLines is the default ring capacity, mirroring
// settings.DEFAULT_MAX_LOG_LINES in the Python app.
const DefaultMaxLogLines = 1000

// LogEntry is one buffered application log line.
type LogEntry struct {
	// Time is when the line was logged.
	Time time.Time
	// Level is the log level (DEBUG, INFO, WARNING, ERROR, …), upper-cased.
	Level string
	// Message is the log text.
	Message string
}

// LogRing is a fixed-capacity, goroutine-safe ring buffer of application log
// lines. The app appends to it as a loguru-style sink; the Logs tab renders the
// most recent lines. It replaces the Python LogPane's in-widget RichLog history.
type LogRing struct {
	mu      sync.Mutex
	entries []LogEntry
	max     int
}

// NewLogRing returns a LogRing holding at most max entries (clamped to at least
// one).
func NewLogRing(max int) *LogRing {
	if max < 1 {
		max = 1
	}
	return &LogRing{max: max}
}

// Append adds a log entry, evicting the oldest line once the ring is full.
func (r *LogRing) Append(level, message string, t time.Time) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.entries = append(r.entries, LogEntry{
		Time:    t,
		Level:   strings.ToUpper(strings.TrimSpace(level)),
		Message: message,
	})
	if len(r.entries) > r.max {
		r.entries = r.entries[len(r.entries)-r.max:]
	}
}

// Last returns up to n most-recent entries, oldest first. A non-positive n
// returns every buffered entry.
func (r *LogRing) Last(n int) []LogEntry {
	r.mu.Lock()
	defer r.mu.Unlock()
	if n <= 0 || n >= len(r.entries) {
		out := make([]LogEntry, len(r.entries))
		copy(out, r.entries)
		return out
	}
	out := make([]LogEntry, n)
	copy(out, r.entries[len(r.entries)-n:])
	return out
}

// Len returns the number of buffered entries.
func (r *LogRing) Len() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.entries)
}
