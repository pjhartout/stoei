package modals

import (
	"testing"

	"github.com/pjhartout/stoei/internal/store"
)

// TestCacheSyncEvictsOnStateChange asserts SyncStates evicts an entry whose live
// state changed and keeps an unchanged one (Python _invalidate_changed_job_info).
func TestCacheSyncEvictsOnStateChange(t *testing.T) {
	c := NewJobDetailCache()
	c.Put("1", cachedDetail{state: "RUNNING"})
	c.Put("2", cachedDetail{state: "RUNNING"})

	// Job 1 changes to COMPLETED, job 2 stays RUNNING.
	c.SyncStates([]store.MergedJob{
		{ID: "1", State: "COMPLETED"},
		{ID: "2", State: "RUNNING"},
	})

	if _, ok := c.Get("1", "RUNNING"); ok {
		t.Error("entry 1 should have been evicted after its state changed")
	}
	if _, ok := c.Get("2", "RUNNING"); !ok {
		t.Error("entry 2 should remain cached (state unchanged)")
	}
}

// TestCacheSyncEvictsVanishedJob asserts a job that disappears from the live list
// is evicted.
func TestCacheSyncEvictsVanishedJob(t *testing.T) {
	c := NewJobDetailCache()
	c.Put("1", cachedDetail{state: "RUNNING"})
	c.SyncStates(nil)
	if c.Len() != 0 {
		t.Errorf("vanished job should be evicted; cache len = %d", c.Len())
	}
}

// TestCacheGetStateMismatchMisses asserts Get with a different live state misses
// even before SyncStates runs (the open-time re-fetch guard).
func TestCacheGetStateMismatchMisses(t *testing.T) {
	c := NewJobDetailCache()
	c.Put("1", cachedDetail{state: "RUNNING", content: "x"})
	if _, ok := c.Get("1", "COMPLETED"); ok {
		t.Error("Get should miss when the live state differs from the cached state")
	}
	if _, ok := c.Get("1", "RUNNING"); !ok {
		t.Error("Get should hit when the live state matches")
	}
}

// TestCacheNormalizesArrayTasks asserts array tasks share a normalized key.
func TestCacheNormalizesArrayTasks(t *testing.T) {
	c := NewJobDetailCache()
	c.Put("12345_[0-99]", cachedDetail{state: "PENDING", content: "arr"})
	if _, ok := c.Get("12345", "PENDING"); !ok {
		t.Error("array-range and base id should share a cache key")
	}
}
