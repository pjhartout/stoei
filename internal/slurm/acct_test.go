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
	// A single-task bracket id (a task cancelled while pending) must normalize
	// to the squeue "_N" form so the terminal record settles the journal row;
	// a multi-task range keeps its bracket id.
	brackets := ParseAcctJobs(
		"5337331_[90]|alice|CANCELLED by 6427|gpu|2026-07-21T17:13:35|Unknown|2026-07-21T17:24:35|00:00:00|0:0|None assigned|1|cpu=1|chemprot\n" +
			"5109800_[4-60%2]|alice|CANCELLED by 8255|gpu|2026-06-22T16:22:49|Unknown|2026-06-29T09:29:57|00:00:00|0:0|None assigned|1|cpu=1|binder\n")
	if len(brackets) != 2 || brackets[0].ID != "5337331_90" || brackets[1].ID != "5109800_[4-60%2]" {
		t.Errorf("bracket id normalization: %+v", brackets)
	}
}

// TestReconcileAcct is the reconcile happy path: sacct's terminal records land
// in history, its live record is left to squeue, and the accounting database is
// queried exactly once across history fetches inside the daily interval.
func TestReconcileAcct(t *testing.T) {
	r := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte(acctOut)}}
	c := NewClient(r, WithUsername("alice"),
		WithJournal(filepath.Join(t.TempDir(), "jobs.jsonl")),
		WithClock(func() time.Time { return time.Date(2026, 7, 17, 9, 0, 0, 0, time.UTC) }),
	)

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
	c := NewClient(r, WithUsername("alice"), WithJournal(path),
		WithClock(func() time.Time { return time.Date(2026, 7, 17, 9, 0, 0, 0, time.UTC) }),
	)
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

// TestReconcileAcctPrunesStaleOwnedRows covers the per-user prune: journal
// rows stuck in a live state the sacct dump can never settle — a dispatched
// array leader (sacct lists only per-task rows) and a legacy row keyed by a
// raw per-task JobId — must be dropped instead of lingering as UNKNOWN
// history rows. Another user's row survives: the per-user dump cannot vouch
// for it.
func TestReconcileAcctPrunesStaleOwnedRows(t *testing.T) {
	path := filepath.Join(t.TempDir(), "jobs.jsonl")
	seed := newJobJournal(path)
	if err := seed.upsert([]ControllerJob{{
		ID: "5320952", User: "alice", Name: "submit.sh", State: "PENDING",
		Submit: "2026-07-17T15:47:49",
	}}); err != nil {
		t.Fatalf("seed journal: %v", err)
	}
	if err := seed.upsert([]ControllerJob{
		// A legacy row keyed by the raw per-task JobId: sacct only ever lists
		// the "%A_%a" form, so this can never be settled — prune it.
		{ID: "5131633", User: "alice", Name: "legacy", State: "RUNNING",
			Submit: "2026-06-26T13:36:08"},
		// Another user's legacy row: the per-user dump cannot vouch for it.
		{ID: "7777", User: "bob", Name: "foreign", State: "RUNNING",
			Submit: "2026-07-17T09:00:00"},
	}); err != nil {
		t.Fatalf("seed journal: %v", err)
	}

	arrayOut := "5320952_0|alice|COMPLETED|gpu|2026-07-17T15:47:49|2026-07-17T15:47:49|2026-07-17T17:05:41|01:17:52|0:0|node01|32|cpu=32|submit.sh\n" +
		"5320952_1|alice|FAILED|gpu|2026-07-17T15:47:49|2026-07-17T15:47:49|2026-07-17T16:49:52|01:02:03|1:0|node02|32|cpu=32|submit.sh\n"
	r := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte(arrayOut)}}
	c := NewClient(r, WithUsername("alice"), WithJournal(path),
		WithClock(func() time.Time { return time.Date(2026, 7, 18, 9, 0, 0, 0, time.UTC) }),
	)
	jobs, _, err := c.JobHistory(context.Background(), 7)
	if err != nil {
		t.Fatalf("JobHistory: %v", err)
	}
	ids := map[string]bool{}
	for _, j := range jobs {
		ids[j.ID] = true
	}
	if ids["5320952"] {
		t.Error("stale array-leader placeholder survived the reconcile")
	}
	if !ids["5320952_0"] || !ids["5320952_1"] {
		t.Errorf("array tasks missing from history: %v", ids)
	}
	if ids["5131633"] {
		t.Error("legacy raw-task-id row survived the reconcile")
	}
	all := map[string]bool{}
	for _, j := range c.journal.all() {
		all[j.ID] = true
	}
	if !all["7777"] {
		t.Error("another user's row must survive the per-user prune")
	}
}

// TestReconcileAcctSettlesPendingCancelledTask covers the bracket-id case: a
// task cancelled while still pending is reported by sacct as "123_[90]" while
// the journal keys it "123_90"; the normalized terminal record must settle the
// row rather than leave it stuck PENDING (rendered UNKNOWN).
func TestReconcileAcctSettlesPendingCancelledTask(t *testing.T) {
	path := filepath.Join(t.TempDir(), "jobs.jsonl")
	seed := newJobJournal(path)
	if err := seed.upsert([]ControllerJob{{
		ID: "5337331_90", User: "alice", Name: "chemprot", State: "PENDING",
		Submit: "2026-07-21T17:13:35",
	}}); err != nil {
		t.Fatalf("seed journal: %v", err)
	}

	out := "5337331_[90]|alice|CANCELLED by 6427|gpu|2026-07-21T17:13:35|Unknown|2026-07-21T17:24:35|00:00:00|0:0|None assigned|1|cpu=1|chemprot\n"
	r := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte(out)}}
	c := NewClient(r, WithUsername("alice"), WithJournal(path),
		WithClock(func() time.Time { return time.Date(2026, 7, 22, 9, 0, 0, 0, time.UTC) }),
	)
	jobs, _, err := c.JobHistory(context.Background(), 7)
	if err != nil {
		t.Fatalf("JobHistory: %v", err)
	}
	for _, j := range jobs {
		if j.ID == "5337331_90" {
			if j.State != "CANCELLED" {
				t.Errorf("state = %q, want CANCELLED settled from the bracket record", j.State)
			}
			return
		}
	}
	t.Fatal("job 5337331_90 missing from history")
}

// TestReconcileAcctEmptyDumpKeepsLiveRows is the prune guard: a successful but
// empty sacct dump must not classify every live row as stale at once.
func TestReconcileAcctEmptyDumpKeepsLiveRows(t *testing.T) {
	path := filepath.Join(t.TempDir(), "jobs.jsonl")
	seed := newJobJournal(path)
	if err := seed.upsert([]ControllerJob{{
		ID: "4242", User: "alice", Name: "train", State: "RUNNING",
		Submit: "2026-07-17T09:00:00",
	}}); err != nil {
		t.Fatalf("seed journal: %v", err)
	}

	r := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte("")}}
	c := NewClient(r, WithUsername("alice"), WithJournal(path))
	if _, _, err := c.JobHistory(context.Background(), 7); err != nil {
		t.Fatalf("JobHistory: %v", err)
	}
	for _, j := range c.journal.all() {
		if j.ID == "4242" {
			return
		}
	}
	t.Error("live row pruned on an empty sacct dump")
}

// TestAcctDue covers the UI progress gate: due before the first attempt of the
// interval, not after (success or failure), and never without a journal.
func TestAcctDue(t *testing.T) {
	cur := time.Date(2026, 7, 17, 9, 0, 0, 0, time.UTC)
	r := &FakeRunner{Outputs: map[string][]byte{"sacct": []byte(acctOut)}}
	c := NewClient(r, WithUsername("alice"),
		WithJournal(filepath.Join(t.TempDir(), "jobs.jsonl")),
		WithClock(func() time.Time { return cur }),
	)
	if !c.AcctDue() {
		t.Error("AcctDue must be true before the first attempt")
	}
	if _, _, err := c.JobHistory(context.Background(), 7); err != nil {
		t.Fatalf("JobHistory: %v", err)
	}
	if c.AcctDue() {
		t.Error("AcctDue must be false after an attempt")
	}
	cur = cur.Add(25 * time.Hour)
	if !c.AcctDue() {
		t.Error("AcctDue must re-arm after the interval")
	}
	if NewClient(r).AcctDue() {
		t.Error("AcctDue must be false without a journal")
	}
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
