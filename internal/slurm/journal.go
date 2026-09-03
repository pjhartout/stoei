package slurm

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// JournalPath returns the on-disk path of the persistent job journal, under
// $XDG_DATA_HOME/stoei (or ~/.local/share/stoei). It returns "" when no home or
// data directory can be resolved, which disables the journal.
func JournalPath() string {
	base := os.Getenv("XDG_DATA_HOME")
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return ""
		}
		base = filepath.Join(home, ".local", "share")
	}
	return filepath.Join(base, "stoei", "jobs.jsonl")
}

// journalRecord is one persisted job: the controller job plus the first and last
// time stoei observed it.
type journalRecord struct {
	ControllerJob
	FirstSeen string
	LastSeen  string
}

// jobJournal is a disk-backed record of every job stoei has observed (via the
// per-user journal query, scontrol completion records, and the nightly sacct
// reconcile), keyed by job id.
// It is the durable job history: it accumulates across runs, and a job already
// recorded in a terminal state is never overwritten by a later (stale) record, so
// final outcomes stick. It is stored as JSON Lines and rewritten atomically
// under a cross-process file lock; all methods are safe for concurrent use,
// including from concurrent stoei instances.
type jobJournal struct {
	path string
	mu   sync.Mutex
	now  func() time.Time
}

// newJobJournal returns a journal backed by the file at path.
func newJobJournal(path string) *jobJournal {
	return &jobJournal{path: path, now: time.Now}
}

// journalRetention bounds how long an unobserved record is kept. It matches the
// 90-day ceiling of the job_history_days setting: a record last seen beyond it
// can never enter the history window again, so upsert drops it to keep the file
// from growing without bound.
const journalRetention = 90 * 24 * time.Hour

// upsert merges observed jobs into the journal and rewrites it atomically. A job
// already recorded in a terminal state keeps its final record (only LastSeen is
// touched, plus a path-only backfill: rows written before stoei captured log
// paths gain them from the nightly sacct reconcile without disturbing the final
// state); any other job is inserted or updated, preserving FirstSeen and any
// recorded log paths a pathless source would otherwise wipe; records last seen
// beyond journalRetention are pruned. The read-merge-write cycle runs under a
// cross-process file lock so concurrent stoei instances cannot clobber each
// other's records.
func (j *jobJournal) upsert(jobs []ControllerJob) error {
	j.mu.Lock()
	defer j.mu.Unlock()
	if err := os.MkdirAll(filepath.Dir(j.path), 0o755); err != nil {
		return err
	}
	unlock := lockJournal(j.path)
	defer unlock()
	recs := j.load()
	now := j.now().UTC().Format(time.RFC3339)
	for _, job := range jobs {
		if job.ID == "" {
			continue
		}
		if existing, ok := recs[job.ID]; ok && IsTerminalState(existing.State) {
			existing.LastSeen = now
			if existing.StdOut == "" {
				existing.StdOut = job.StdOut
			}
			if existing.StdErr == "" {
				existing.StdErr = job.StdErr
			}
			recs[job.ID] = existing
			continue
		}
		rec := journalRecord{ControllerJob: job, FirstSeen: now, LastSeen: now}
		if existing, ok := recs[job.ID]; ok {
			rec.FirstSeen = existing.FirstSeen
			if rec.StdOut == "" {
				rec.StdOut = existing.StdOut
			}
			if rec.StdErr == "" {
				rec.StdErr = existing.StdErr
			}
		}
		recs[job.ID] = rec
	}
	horizon := j.now().Add(-journalRetention)
	for id, r := range recs {
		if t, err := time.Parse(time.RFC3339, r.LastSeen); err == nil && t.Before(horizon) {
			delete(recs, id)
		}
	}
	return j.write(recs)
}

// remove deletes the given ids and rewrites the journal atomically under the
// cross-process lock. An empty ids is a no-op. It is used by the sacct
// reconcile to drop the user's stale live records sacct no longer lists.
func (j *jobJournal) remove(ids []string) error {
	if len(ids) == 0 {
		return nil
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	unlock := lockJournal(j.path)
	defer unlock()
	recs := j.load()
	for _, id := range ids {
		delete(recs, id)
	}
	return j.write(recs)
}

// all returns every recorded job, without the bookkeeping timestamps.
func (j *jobJournal) all() []ControllerJob {
	j.mu.Lock()
	defer j.mu.Unlock()
	recs := j.load()
	out := make([]ControllerJob, 0, len(recs))
	for _, r := range recs {
		out = append(out, r.ControllerJob)
	}
	return out
}

// load reads the journal file into a map keyed by job id. A missing file yields
// an empty map; malformed lines are skipped. The journal is best-effort and must
// never break a fetch, so read errors degrade to whatever was parsed.
func (j *jobJournal) load() map[string]journalRecord {
	recs := make(map[string]journalRecord)
	f, err := os.Open(j.path)
	if err != nil {
		return recs
	}
	defer func() { _ = f.Close() }()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		var r journalRecord
		if json.Unmarshal([]byte(line), &r) == nil && r.ID != "" {
			recs[r.ID] = r
		}
	}
	return recs
}

// write rewrites the journal atomically. The temp file name is unique per
// writer so concurrent stoei instances never publish each other's partial file;
// upsert's cross-process lock additionally serializes whole read-merge-write
// cycles so a rename cannot discard another instance's merge.
func (j *jobJournal) write(recs map[string]journalRecord) error {
	f, err := os.CreateTemp(filepath.Dir(j.path), "jobs-*.tmp")
	if err != nil {
		return err
	}
	tmp := f.Name()
	fail := func(err error) error {
		_ = f.Close()
		_ = os.Remove(tmp)
		return err
	}
	w := bufio.NewWriter(f)
	enc := json.NewEncoder(w)
	for _, r := range recs {
		if err := enc.Encode(r); err != nil {
			return fail(err)
		}
	}
	if err := w.Flush(); err != nil {
		return fail(err)
	}
	if err := f.Close(); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	return os.Rename(tmp, j.path)
}
