package components

import (
	"fmt"
	"sync"
	"testing"
	"time"
)

// fillRing appends n numbered INFO lines ("line-1".."line-n") at a fixed time.
func fillRing(r *LogRing, n int) {
	ts := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	for i := 1; i <= n; i++ {
		r.Append("info", fmt.Sprintf("line-%d", i), ts)
	}
}

// TestLogRingLastPartialWindow asserts Last(n) with fewer lines requested than
// buffered returns exactly the n most-recent entries, oldest first — the
// partial-window branch the Logs tab exercises on every short viewport.
func TestLogRingLastPartialWindow(t *testing.T) {
	r := NewLogRing(10)
	fillRing(r, 5)

	got := r.Last(2)
	if len(got) != 2 {
		t.Fatalf("Last(2) returned %d entries; want 2", len(got))
	}
	if got[0].Message != "line-4" || got[1].Message != "line-5" {
		t.Errorf("window = %q,%q; want line-4,line-5 (most recent, oldest first)", got[0].Message, got[1].Message)
	}
}

// TestLogRingLastWholeBufferWindows asserts Last returns every buffered entry
// when the request equals or exceeds the buffered count, so an exact-size or
// oversized viewport never truncates or pads the log window.
func TestLogRingLastWholeBufferWindows(t *testing.T) {
	r := NewLogRing(10)
	fillRing(r, 3)

	for _, n := range []int{3, 4, 100} {
		got := r.Last(n)
		if len(got) != 3 {
			t.Fatalf("Last(%d) returned %d entries; want all 3 buffered", n, len(got))
		}
		if got[0].Message != "line-1" || got[2].Message != "line-3" {
			t.Errorf("Last(%d) window = %q..%q; want line-1..line-3", n, got[0].Message, got[2].Message)
		}
	}
}

// TestLogRingLastAfterWraparound asserts the window stays correct once the ring
// has evicted old lines: Last must return only the newest survivors, never an
// evicted line, for full, exact, and partial requests alike.
func TestLogRingLastAfterWraparound(t *testing.T) {
	r := NewLogRing(3)
	fillRing(r, 7)

	if r.Len() != 3 {
		t.Fatalf("Len = %d; want the capacity 3 after wrap-around", r.Len())
	}
	all := r.Last(0)
	if len(all) != 3 || all[0].Message != "line-5" || all[2].Message != "line-7" {
		t.Errorf("Last(0) = %+v; want line-5..line-7", all)
	}
	exact := r.Last(3)
	if len(exact) != 3 || exact[0].Message != "line-5" || exact[2].Message != "line-7" {
		t.Errorf("Last(3) = %+v; want line-5..line-7", exact)
	}
	part := r.Last(2)
	if len(part) != 2 || part[0].Message != "line-6" || part[1].Message != "line-7" {
		t.Errorf("Last(2) = %+v; want line-6,line-7", part)
	}
}

// TestLogRingConcurrentAppendLast asserts the ring is goroutine-safe: the app's
// logging sink appends from outside the Update loop while the Logs tab reads,
// so concurrent Append/Last/Len must not race (verified by -race) and the
// post-join state must be exactly the capacity's worth of well-formed entries.
func TestLogRingConcurrentAppendLast(t *testing.T) {
	const (
		writers   = 4
		perWriter = 50
		capacity  = 64
	)
	r := NewLogRing(capacity)
	ts := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)

	var wg sync.WaitGroup
	for w := range writers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range perWriter {
				r.Append("info", fmt.Sprintf("w%d-%d", w, i), ts)
				r.Last(8)
			}
		}()
	}
	wg.Add(1)
	go func() {
		defer wg.Done()
		for range writers * perWriter {
			r.Len()
			r.Last(0)
		}
	}()
	wg.Wait()

	if got := r.Len(); got != capacity {
		t.Errorf("after %d appends Len = %d; want the full capacity %d", writers*perWriter, got, capacity)
	}
	last := r.Last(8)
	if len(last) != 8 {
		t.Fatalf("Last(8) returned %d entries; want 8", len(last))
	}
	for i, e := range last {
		if e.Level != "INFO" || e.Message == "" {
			t.Errorf("entry %d = %+v; want a well-formed INFO line", i, e)
		}
	}
}
