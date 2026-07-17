package slurm

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

const acctOut = "4242|alice|COMPLETED|gpu|2026-07-15T10:00:00|2026-07-15T10:05:00|2026-07-15T12:00:00|01:55:00|0:0|node01|8|cpu=8,gres/gpu=2|train\n" +
	"4243|alice|CANCELLED by 1001|gpu|2026-07-15T10:00:00|2026-07-15T10:05:00|2026-07-15T11:00:00|00:55:00|0:0|node02|4|cpu=4|prep|sweep\n" +
	"4244|alice|RUNNING|gpu|2026-07-16T10:00:00|2026-07-16T10:05:00|Unknown|01:00:00|0:0|node03|2|cpu=2|live\n"

func sacctCalls(r *FakeRunner) int {
	n := 0
	for _, call := range r.Calls {
		if call.Name == "sacct" {
			n++
		}
	}
	return n
}

func TestParseAcctJobs(t *testing.T) {
	jobs := ParseAcctJobs(acctOut + "malformed line\n")
	if len(jobs) != 3 {
		t.Fatalf("got %d jobs, want 3", len(jobs))
	}
	j := jobs[0]
	if j.ID != "4242" || j.User != "alice" || j.State != "COMPLETED" || j.Name != "train" || j.NCPUS != "8" || j.AllocTRES != "cpu=8,gres/gpu=2" {
		t.Errorf("unexpected first job: %+v", j)
	}
	if jobs[1].State != "CANCELLED" {
		t.Errorf("state %q not reduced to base token", jobs[1].State)
	}
	// JobName is the last column so a legal '|' in the name must not shift or
	// drop the record.
	if jobs[1].Name != "prep|sweep" {
		t.Errorf("pipe-bearing job name mangled: %q", jobs[1].Name)
	}
}

// TestReconcileAcct is the reconcile happy path: sacct's terminal records land
// in history, its live record is left to squeue, and the accounting database is
// queried exactly once across history fetches inside the daily interval.
func TestReconcileAcct(t *testing.T) {
	r := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte(acctOut)}}
	c := NewClient(r, WithUsername("alice"), WithJournal(filepath.Join(t.TempDir(), "jobs.jsonl")))

	for range 2 {
		jobs, _, err := c.JobHistory(context.Background(), 7)
		if err != nil {
			t.Fatalf("JobHistory: %v", err)
		}
		states := map[string]string{}
		for _, j := range jobs {
			states[j.ID] = j.State
		}
		if states["4242"] != "COMPLETED" || states["4243"] != "CANCELLED" {
			t.Errorf("terminal sacct jobs missing from history: %v", states)
		}
		if _, ok := states["4244"]; ok {
			t.Error("live sacct job must not enter the journal")
		}
	}
	if got := sacctCalls(r); got != 1 {
		t.Errorf("got %d sacct calls, want 1", got)
	}
	if w := c.AcctWarning(); w != "" {
		t.Errorf("unexpected warning %q", w)
	}
}

// TestReconcileAcctPreservesRestart covers the Restart carry-over: sacct
// records report no requeue count, so backfilling a terminal state must not
// wipe the count the squeue journal query recorded.
func TestReconcileAcctPreservesRestart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "jobs.jsonl")
	seed := newJobJournal(path)
	if err := seed.upsert([]ControllerJob{{
		ID: "4242", User: "alice", Name: "train", State: "RUNNING",
		Restart: "2", Submit: "2026-07-15T10:00:00",
	}}); err != nil {
		t.Fatalf("seed journal: %v", err)
	}

	r := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte(acctOut)}}
	c := NewClient(r, WithUsername("alice"), WithJournal(path))
	jobs, _, err := c.JobHistory(context.Background(), 7)
	if err != nil {
		t.Fatalf("JobHistory: %v", err)
	}
	for _, j := range jobs {
		if j.ID == "4242" {
			if j.State != "COMPLETED" {
				t.Errorf("state %q, want COMPLETED from sacct", j.State)
			}
			if j.Restart != "2" {
				t.Errorf("Restart %q, want journal's \"2\" preserved", j.Restart)
			}
			return
		}
	}
	t.Fatal("job 4242 missing from history")
}

// TestReconcileAcctFailure is the failover: history still works from the
// journal, the warning is delivered exactly once, sacct is not retried before
// the daily interval elapses, and no stamp is written — so a fresh session
// during the outage attempts (and warns) again.
func TestReconcileAcctFailure(t *testing.T) {
	dir := t.TempDir()
	r := &FakeRunner{Errs: map[string]error{"sacct": errors.New("slurmdbd down")}}
	c := NewClient(r, WithUsername("alice"), WithJournal(filepath.Join(dir, "jobs.jsonl")))

	if _, _, err := c.JobHistory(context.Background(), 7); err != nil {
		t.Fatalf("JobHistory must not fail on sacct failover: %v", err)
	}
	if w := c.AcctWarning(); w == "" {
		t.Error("expected a one-shot warning after sacct failure")
	}
	if w := c.AcctWarning(); w != "" {
		t.Errorf("warning must clear after collection, got %q", w)
	}
	if _, _, err := c.JobHistory(context.Background(), 7); err != nil {
		t.Fatalf("JobHistory: %v", err)
	}
	if got := sacctCalls(r); got != 1 {
		t.Errorf("got %d sacct calls, want 1 (no retry within the interval)", got)
	}

	// A failed attempt must not stamp: a new session during the outage gets its
	// own attempt and its own warning.
	r2 := &FakeRunner{Errs: map[string]error{"sacct": errors.New("slurmdbd down")}}
	c2 := NewClient(r2, WithUsername("alice"), WithJournal(filepath.Join(dir, "jobs.jsonl")))
	if _, _, err := c2.JobHistory(context.Background(), 7); err != nil {
		t.Fatalf("JobHistory: %v", err)
	}
	if got := sacctCalls(r2); got != 1 {
		t.Errorf("fresh session during outage: got %d sacct calls, want 1", got)
	}
	if w := c2.AcctWarning(); w == "" {
		t.Error("fresh session during outage must warn once")
	}
}

// TestReconcileAcctUpsertFailure covers the journal-write failover: a
// successful query whose merge cannot be persisted must warn and must not
// stamp, so the backfill is retried rather than silently lost.
func TestReconcileAcctUpsertFailure(t *testing.T) {
	dir := t.TempDir()
	journalPath := filepath.Join(dir, "unwritable", "jobs.jsonl")
	// Make the journal directory uncreatable by occupying its path with a file.
	if err := os.WriteFile(filepath.Join(dir, "unwritable"), nil, 0o644); err != nil {
		t.Fatal(err)
	}
	r := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte(acctOut)}}
	c := NewClient(r, WithUsername("alice"), WithJournal(journalPath))
	if _, _, err := c.JobHistory(context.Background(), 7); err == nil {
		// The squeue journal refresh fails on the same unwritable path; either
		// way the reconcile must have recorded its warning.
		t.Log("JobHistory succeeded despite unwritable journal")
	}
	if w := c.AcctWarning(); w == "" {
		t.Error("expected a warning when the backfill cannot be persisted")
	}
}

// TestReconcileAcctCrossSession is the restart case: the stamp file next to the
// journal makes a fresh client (a new stoei launch) skip sacct inside the daily
// interval and query again as soon as the stamp — not the skip — is a day old.
func TestReconcileAcctCrossSession(t *testing.T) {
	dir := t.TempDir()
	cur := time.Date(2026, 7, 17, 9, 0, 0, 0, time.UTC)
	clock := func() time.Time { return cur }
	newSession := func() (*FakeRunner, *Client) {
		r := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte(acctOut)}}
		return r, NewClient(r, WithUsername("alice"),
			WithJournal(filepath.Join(dir, "jobs.jsonl")), WithClock(clock))
	}
	fetch := func(c *Client) {
		t.Helper()
		if _, _, err := c.JobHistory(context.Background(), 7); err != nil {
			t.Fatalf("JobHistory: %v", err)
		}
	}

	r1, c1 := newSession()
	fetch(c1)
	if got := sacctCalls(r1); got != 1 {
		t.Fatalf("first session: got %d sacct calls, want 1", got)
	}
	cur = cur.Add(23 * time.Hour)
	r2, c2 := newSession() // relaunch within the interval: stamp suppresses sacct
	fetch(c2)
	if got := sacctCalls(r2); got != 0 {
		t.Errorf("relaunch within interval: got %d sacct calls, want 0", got)
	}
	// The next query must fire when the STAMP is a day old (1h from now), not a
	// full day after the skip — the up-to-48h drift bug.
	cur = cur.Add(2 * time.Hour)
	fetch(c2)
	if got := sacctCalls(r2); got != 1 {
		t.Errorf("after stamp expiry: got %d sacct calls, want 1", got)
	}
}

// TestReconcileAcctDailyRearm drives the clock across the daily interval: the
// query re-runs, an ongoing outage stays silent (I9), and a recovery re-arms
// the warning for the next outage.
func TestReconcileAcctDailyRearm(t *testing.T) {
	cur := time.Date(2026, 7, 17, 9, 0, 0, 0, time.UTC)
	r := &FakeRunner{Errs: map[string]error{"sacct": errors.New("slurmdbd down")}}
	c := NewClient(r, WithUsername("alice"),
		WithJournal(filepath.Join(t.TempDir(), "jobs.jsonl")),
		WithClock(func() time.Time { return cur }),
	)
	fetch := func() {
		t.Helper()
		if _, _, err := c.JobHistory(context.Background(), 7); err != nil {
			t.Fatalf("JobHistory: %v", err)
		}
	}

	fetch() // first attempt fails: warn
	if c.AcctWarning() == "" {
		t.Error("expected a warning on the first failure")
	}
	cur = cur.Add(25 * time.Hour)
	fetch() // still failing: re-query, but no repeat warning
	if got := sacctCalls(r); got != 2 {
		t.Errorf("got %d sacct calls, want 2 after the interval elapsed", got)
	}
	if w := c.AcctWarning(); w != "" {
		t.Errorf("ongoing outage must not re-warn, got %q", w)
	}
	delete(r.Errs, "sacct")
	r.Outputs = map[string][]byte{"sacct": []byte(acctOut)}
	cur = cur.Add(25 * time.Hour)
	fetch() // recovery
	if w := c.AcctWarning(); w != "" {
		t.Errorf("recovery must not warn, got %q", w)
	}
	r.Errs = map[string]error{"sacct": errors.New("slurmdbd down again")}
	cur = cur.Add(25 * time.Hour)
	fetch() // new outage after recovery: warn again
	if c.AcctWarning() == "" {
		t.Error("expected a warning on a new outage after recovery")
	}
}
