package slurm

import (
	"bytes"
	"context"
	"errors"
	"os"
	"testing"
	"time"
)

// sacctRun counts how many times the inner runner saw a sacct call.
func sacctRun(fr *FakeRunner) int {
	n := 0
	for _, c := range fr.Calls {
		if c.Name == "sacct" {
			n++
		}
	}
	return n
}

func TestCachingRunnerServesFreshSacctFromCache(t *testing.T) {
	fr := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte("history-data")}}
	r := NewCachingRunner(fr, t.TempDir(), time.Hour)
	ctx := context.Background()

	out1, err := r.Run(ctx, "sacct", "-S", "now-7days")
	if err != nil {
		t.Fatalf("first Run: %v", err)
	}
	out2, err := r.Run(ctx, "sacct", "-S", "now-7days")
	if err != nil {
		t.Fatalf("second Run: %v", err)
	}
	if !bytes.Equal(out1, out2) || string(out2) != "history-data" {
		t.Fatalf("cached output = %q, %q; want both %q", out1, out2, "history-data")
	}
	if got := sacctRun(fr); got != 1 {
		t.Errorf("inner sacct calls = %d, want 1 (second served from cache)", got)
	}
}

func TestCachingRunnerKeysOnArgs(t *testing.T) {
	fr := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte("x")}}
	r := NewCachingRunner(fr, t.TempDir(), time.Hour)
	ctx := context.Background()

	_, _ = r.Run(ctx, "sacct", "-S", "now-7days")
	_, _ = r.Run(ctx, "sacct", "-S", "now-30days") // different window → distinct entry
	if got := sacctRun(fr); got != 2 {
		t.Errorf("inner sacct calls = %d, want 2 (distinct args)", got)
	}
}

func TestCachingRunnerOnlyCachesSacct(t *testing.T) {
	fr := &FakeRunner{Outputs: map[string][]byte{"squeue": []byte("live")}}
	r := NewCachingRunner(fr, t.TempDir(), time.Hour)
	ctx := context.Background()

	_, _ = r.Run(ctx, "squeue", "-o", "%i")
	_, _ = r.Run(ctx, "squeue", "-o", "%i")
	live := 0
	for _, c := range fr.Calls {
		if c.Name == "squeue" {
			live++
		}
	}
	if live != 2 {
		t.Errorf("squeue ran %d times, want 2 (never cached)", live)
	}
}

func TestCachingRunnerExpiresAfterTTL(t *testing.T) {
	fr := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte("x")}}
	r := NewCachingRunner(fr, t.TempDir(), time.Hour)
	base := time.Unix(1_700_000_000, 0)
	ctx := context.Background()

	_, _ = r.Run(ctx, "sacct", "-S", "now-7days")
	// The entry's "fetched at" is its file mtime; backdate it to base so advancing
	// now past base+ttl makes it stale deterministically (no wall clock).
	path := r.cachePath("sacct", []string{"-S", "now-7days"})
	if err := os.Chtimes(path, base, base); err != nil {
		t.Fatalf("chtimes: %v", err)
	}
	r.now = func() time.Time { return base.Add(time.Hour + time.Second) } // past TTL
	_, _ = r.Run(ctx, "sacct", "-S", "now-7days")
	if got := sacctRun(fr); got != 2 {
		t.Errorf("inner sacct calls = %d, want 2 (cache expired)", got)
	}
}

func TestCachingRunnerDoesNotCacheErrors(t *testing.T) {
	fr := &FakeRunner{Errs: map[string]error{"sacct": errors.New("boom")}}
	r := NewCachingRunner(fr, t.TempDir(), time.Hour)
	ctx := context.Background()

	if _, err := r.Run(ctx, "sacct"); err == nil {
		t.Fatal("want error from inner")
	}
	if _, err := r.Run(ctx, "sacct"); err == nil {
		t.Fatal("want error from inner on retry")
	}
	if got := sacctRun(fr); got != 2 {
		t.Errorf("inner sacct calls = %d, want 2 (errors not cached)", got)
	}
}

func TestCachingRunnerDisabled(t *testing.T) {
	fr := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte("x")}}
	ctx := context.Background()
	for _, tc := range []struct {
		name string
		r    *CachingRunner
	}{
		{"zero ttl", NewCachingRunner(fr, t.TempDir(), 0)},
		{"empty dir", NewCachingRunner(fr, "", time.Hour)},
	} {
		fr.Calls = nil
		_, _ = tc.r.Run(ctx, "sacct")
		_, _ = tc.r.Run(ctx, "sacct")
		if got := sacctRun(fr); got != 2 {
			t.Errorf("%s: inner sacct calls = %d, want 2 (caching off)", tc.name, got)
		}
	}
}
