package slurm

import (
	"context"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// acctFormat is the sacct --format list of the one-shot reconcile query; its
// columns map 1:1 onto ControllerJob fields. JobName is last so a legal '|' in
// a job name cannot shift the delimited columns (the parser lets the final
// field absorb the remainder).
const acctFormat = "JobID,User,State,Partition,Submit,Start,End," +
	"Elapsed,ExitCode,NodeList,AllocCPUS,AllocTRES,JobName"

// acctFieldCount is the number of pipe-delimited columns acctFormat produces.
var acctFieldCount = strings.Count(acctFormat, ",") + 1

// acctSingleTaskID matches sacct's bracket form of a single array task, e.g.
// "5337331_[90]" or "5337331_[90%2]": a task cancelled while still pending.
// squeue reports such a split-off task without brackets ("5337331_90"), so the
// bracket must be stripped for the terminal record to settle the journal row.
// Multi-task ranges are left untouched; staleOwnedIDs covers their split rows.
var acctSingleTaskID = regexp.MustCompile(`^(\d+)_\[(\d+)(?:%\d+)?\]$`)

// ParseAcctJobs parses pipe-delimited "sacct -n -P -X" output into
// ControllerJob records. Malformed lines are skipped; states are reduced to
// their base token so "CANCELLED by 1001" matches the journal's shape, and
// single-task bracket ids are normalized to the squeue form.
func ParseAcctJobs(raw string) []ControllerJob {
	var jobs []ControllerJob
	for _, line := range strings.Split(strings.TrimSpace(raw), "\n") {
		f := strings.SplitN(line, "|", acctFieldCount)
		if len(f) != acctFieldCount || f[0] == "" {
			continue
		}
		id := f[0]
		if m := acctSingleTaskID.FindStringSubmatch(id); m != nil {
			id = m[1] + "_" + m[2]
		}
		jobs = append(jobs, ControllerJob{
			ID:        id,
			User:      f[1],
			State:     baseState(f[2]),
			Partition: f[3],
			Submit:    f[4],
			Start:     f[5],
			End:       f[6],
			Elapsed:   f[7],
			ExitCode:  f[8],
			NodeList:  f[9],
			NCPUS:     f[10],
			AllocTRES: f[11],
			Name:      f[12],
		})
	}
	return jobs
}

// acctQueryTimeout caps the sacct query well below the UI's 30s fetch budget so
// a slow slurmdbd cannot starve the squeue journal query that shares the fetch
// context.
const acctQueryTimeout = 10 * time.Second

// queryAcctJobs runs the single per-user sacct query, windowed to the journal
// retention (not the display setting, which can widen later) and restricted to
// allocations (-X, no steps) so it stays cheap for slurmdbd.
func (c *Client) queryAcctJobs(ctx context.Context) ([]ControllerJob, error) {
	ctx, cancel := context.WithTimeout(ctx, acctQueryTimeout)
	defer cancel()
	out, err := c.runner.Run(ctx, "sacct",
		"-u", c.username,
		"-n", "-P", "-X",
		"-S", c.now().Add(-journalRetention).Format("2006-01-02"),
		"--format="+acctFormat,
	)
	if err != nil {
		return nil, err
	}
	return ParseAcctJobs(string(out)), nil
}

// acctReconcileInterval is the sacct reconcile cadence: once at startup, then
// daily, so a long-lived session self-heals completions missed during a
// controller outage without leaning on slurmdbd.
const acctReconcileInterval = 24 * time.Hour

// reconcileAcct merges sacct's terminal records into the journal, at most once
// per acctReconcileInterval across sessions (the stamp file). sacct is
// authoritative for jobs that finished while stoei was not watching (their
// journal record is stuck in a live state) and for jobs stoei never observed;
// live jobs are skipped because the squeue journal query owns them and carries
// richer data. On failure — query or journal write — history degrades to
// journal-only, a warning is recorded edge-triggered per session (I9), and the
// stamp is left untouched so a fresh session during the outage still attempts
// (and warns) once; within a session the in-memory gate retries daily.
func (c *Client) reconcileAcct(ctx context.Context) {
	if c.journal == nil {
		return
	}
	c.mu.Lock()
	if !c.lastAcct.IsZero() && c.now().Sub(c.lastAcct) < acctReconcileInterval {
		c.mu.Unlock()
		return
	}
	c.lastAcct = c.now()
	c.mu.Unlock()
	// The stamp file's mtime records the last success by any stoei instance, so
	// frequent restarts cost slurmdbd one query per day, not one per launch.
	// The check-then-touch race between concurrent instances is benign (worst
	// case one extra query), so it is not worth a lock.
	if fi, err := os.Stat(c.acctStampPath()); err == nil && c.now().Sub(fi.ModTime()) < acctReconcileInterval {
		// Align the in-memory gate with the stamp so the next attempt fires when
		// the stamp expires, not a full interval after this session noticed it.
		c.mu.Lock()
		c.lastAcct = fi.ModTime()
		c.mu.Unlock()
		return
	}
	jobs, err := c.queryAcctJobs(ctx)
	if err == nil {
		err = c.journal.upsert(c.mergeAcct(jobs))
	}
	if err == nil {
		err = c.journal.remove(staleOwnedIDs(c.journal.all(), jobs, c.username))
	}
	c.mu.Lock()
	if err != nil {
		if !c.acctFailing {
			c.acctWarning = "sacct reconcile failed — job history reflects only jobs stoei has observed"
		}
		c.acctFailing = true
		c.mu.Unlock()
		return
	}
	c.acctFailing = false
	c.mu.Unlock()
	c.touchAcctStamp()
}

// mergeAcct filters sacct records down to terminal states and carries the
// requeue count over from the existing journal record: sacct reports none, and
// a wholesale replace would silently wipe it from the history stats. The
// read-then-upsert pair is not atomic across processes; the window is benign
// (worst case one Restart merge from a slightly stale record).
func (c *Client) mergeAcct(jobs []ControllerJob) []ControllerJob {
	existing := make(map[string]string)
	for _, j := range c.journal.all() {
		existing[j.ID] = j.Restart
	}
	terminal := jobs[:0]
	for _, j := range jobs {
		if !IsTerminalState(j.State) {
			continue
		}
		if j.Restart == "" {
			j.Restart = existing[j.ID]
		}
		terminal = append(terminal, j)
	}
	return terminal
}

// staleOwnedIDs returns the current user's journal ids stuck in a live state
// that a non-empty sacct dump does not list. The per-user dump covers live and
// terminal jobs alike, so an id absent from it is no real job anymore — it is
// an id-shape artifact the upsert can never settle: a dispatched array leader
// (sacct lists only per-task rows), a split pending task cancelled inside a
// range ("123_[4-60%2]"), or a legacy row keyed by a raw per-task JobId from
// before the "%A_%a" normalization. Without pruning, such rows render as
// UNKNOWN history forever. A genuinely live job pruned by accounting lag is
// re-added by the next squeue journal query within seconds, so a premature
// prune self-heals. Other users' legacy rows are left to the retention prune
// (the dump cannot vouch for them), and an empty dump aborts: it would
// classify every live row as stale at once.
func staleOwnedIDs(journal, acct []ControllerJob, user string) []string {
	if len(acct) == 0 {
		return nil
	}
	ids := make(map[string]bool, len(acct))
	for _, j := range acct {
		ids[j.ID] = true
	}
	var stale []string
	for _, j := range journal {
		if j.User == user && !IsTerminalState(j.State) && !ids[j.ID] {
			stale = append(stale, j.ID)
		}
	}
	return stale
}

// AcctDue reports whether the next JobHistory call will attempt the sacct
// reconcile, so the UI can show progress feedback for the slower fetch. It
// consults only in-memory state — never the stamp file — because it runs on
// the UI's Update path, where file IO is forbidden; the cost is one brief
// false positive per launch when the stamp then suppresses the reconcile.
func (c *Client) AcctDue() bool {
	if c.journal == nil {
		return false
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.lastAcct.IsZero() || c.now().Sub(c.lastAcct) >= acctReconcileInterval
}

// AcctStampPath returns the cross-session sacct reconcile stamp, kept next to
// the journal at journalPath. Only its mtime matters; the content is empty.
// "stoei reset" removes it along with the journal so a reset is followed by a
// fresh backfill.
func AcctStampPath(journalPath string) string {
	return filepath.Join(filepath.Dir(journalPath), "sacct-reconcile.stamp")
}

func (c *Client) acctStampPath() string { return AcctStampPath(c.journal.path) }

// touchAcctStamp records a successful reconcile by rewriting the stamp file.
// The mtime is set from the injected clock so tests can drive the cadence
// deterministically. Best-effort: a write failure only weakens the
// cross-session cap to a per-session one, and the same unwritable directory
// already fails the journal upsert loudly.
func (c *Client) touchAcctStamp() {
	path := c.acctStampPath()
	_ = os.MkdirAll(filepath.Dir(path), 0o755)
	_ = os.WriteFile(path, nil, 0o644)
	now := c.now()
	_ = os.Chtimes(path, now, now)
}

// AcctWarning returns and clears the pending warning from a failed sacct
// reconcile, so the UI shows each outage exactly once per session. It is ""
// when the reconcile succeeded, has not run, or the outage was already
// reported.
func (c *Client) AcctWarning() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	w := c.acctWarning
	c.acctWarning = ""
	return w
}
