package modals

import (
	"strings"

	"github.com/pjhartout/stoei/internal/store"
)

// cachedDetail is a memoized job-detail render plus the extracted log paths and
// the job state it was rendered for. The state is what drives eviction.
type cachedDetail struct {
	content string
	stdout  string
	stderr  string
	source  string
	// state is the job state at the time the detail was cached; when the live
	// state diverges the entry is evicted so the next open re-fetches.
	state string
	// err is a non-empty fetch error message, cached so a failed lookup is not
	// re-attempted on every open within the same state.
	err string
	// fields is the parsed scontrol detail backing the render, kept so the
	// modify modal can pre-fill current values on a cache hit.
	fields map[string]string
}

// JobDetailCache memoizes rendered job details keyed by normalized job id and
// evicts an entry when that job's live state changes. The modal flow consults Get
// with the job's current state and only reuses a cached entry when the state
// matches; SyncStates evicts entries whose state has drifted (or that vanished)
// after a store refresh.
type JobDetailCache struct {
	entries map[string]cachedDetail
}

// NewJobDetailCache returns an empty cache.
func NewJobDetailCache() *JobDetailCache {
	return &JobDetailCache{entries: map[string]cachedDetail{}}
}

// normalizeID strips an array-task range suffix so array tasks share a cache key.
// A plain "12345" or "12345_0" is returned unchanged; "12345_[0-9]" collapses to
// "12345".
func normalizeID(jobID string) string {
	jobID = strings.TrimSpace(jobID)
	if i := strings.IndexByte(jobID, '['); i >= 0 {
		// "12345_[0-99]" -> "12345"
		return strings.TrimSuffix(jobID[:i], "_")
	}
	return jobID
}

// Get returns the cached detail for jobID when present and the cached state
// matches wantState, the live state of the job. A mismatch (or a missing entry)
// reports ok=false so the caller re-fetches. An empty wantState means the job is
// gone from the live list, which always misses (forcing a fresh lookup).
func (c *JobDetailCache) Get(jobID, wantState string) (cachedDetail, bool) {
	e, ok := c.entries[normalizeID(jobID)]
	if !ok {
		return cachedDetail{}, false
	}
	if e.state != wantState {
		return cachedDetail{}, false
	}
	return e, true
}

// Put stores a rendered detail for jobID at the given live state.
func (c *JobDetailCache) Put(jobID string, e cachedDetail) {
	c.entries[normalizeID(jobID)] = e
}

// Evict removes the cached entries for jobID's whole job family — the exact
// entry plus the array leader and sibling tasks sharing its base id. The root
// calls it after a successful modification: the job's state usually does not
// change, so SyncStates would keep serving the pre-modification render, and an
// array-scoped update (e.g. ArrayTaskThrottle) targets the leader while the
// modal was opened for one task.
func (c *JobDetailCache) Evict(jobID string) {
	base := baseJobID(normalizeID(jobID))
	for id := range c.entries {
		if baseJobID(id) == base {
			delete(c.entries, id)
		}
	}
}

// baseJobID strips a "_<task>" suffix so array tasks share a family key.
func baseJobID(jobID string) string {
	if i := strings.IndexByte(jobID, '_'); i >= 0 {
		return jobID[:i]
	}
	return jobID
}

// SyncStates evicts cached entries whose live state has changed since they were
// cached, or that no longer appear in jobs. It is called after each store
// refresh so the modal cache stays consistent with the live job list.
func (c *JobDetailCache) SyncStates(jobs []store.MergedJob) {
	live := make(map[string]string, len(jobs))
	for _, j := range jobs {
		live[normalizeID(j.ID)] = j.State
	}
	for id, e := range c.entries {
		if cur, ok := live[id]; !ok || cur != e.state {
			delete(c.entries, id)
		}
	}
}

// Len reports the number of cached entries (used by tests).
func (c *JobDetailCache) Len() int { return len(c.entries) }
