package slurm

import (
	"context"
	"hash/fnv"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// acctFormat is the sacct --format list of the one-shot reconcile query; its
// columns map 1:1 onto ControllerJob fields. JobName is last so a legal '|' in
// a job name cannot shift the delimited columns (the parser lets the final
// field absorb the remainder); a '|' inside a log path would shift them, but
// unlike job names such paths do not occur in practice.
const acctFormat = "JobID,User,State,Partition,Submit,Start,End," +
	"Elapsed,ExitCode,NodeList,AllocCPUS,AllocTRES,StdErr,StdOut,JobName"

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
		// Accounting reports log paths with the sbatch patterns unexpanded.
		// For an array task the raw per-task id is absent from this query, so
		// %j stays verbatim there (numericOnly rejects the "M_T" form) rather
		// than expanding to a wrong path.
		master, task, _ := strings.Cut(id, "_")
		if task == "" {
			master = ""
		}
		stdOut, stdErr := jobStdIO(f[13], f[12], id, master, task, f[1], f[14])
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
			StdOut:    stdOut,
			StdErr:    stdErr,
			Name:      f[14],
		})
	}
	return jobs
}

// acctQueryTimeout bounds each sacct call so a slurmdbd outage cannot consume
// the caller's entire fetch budget.
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

// accountingJobDetail returns one scontrol-shaped detail record from sacct.
// It is used only after the controller has purged a completed job; --allusers
// requests another user's record when cluster accounting policy permits it.
func (c *Client) accountingJobDetail(ctx context.Context, jobID string) (JobDetail, bool, error) {
	ctx, cancel := context.WithTimeout(ctx, acctQueryTimeout)
	defer cancel()
	out, err := c.runner.Run(ctx, "sacct",
		"--allusers", "-n", "-P", "-X",
		"-j", jobID,
		"--format="+acctFormat,
	)
	if err != nil {
		return JobDetail{}, false, err
	}
	for _, job := range ParseAcctJobs(string(out)) {
		if job.ID != jobID {
			continue
		}
		fields := make(map[string]string, 15)
		set := func(key, value string) {
			if strings.TrimSpace(value) != "" {
				fields[key] = value
			}
		}
		set("JobId", job.ID)
		set("JobName", job.Name)
		set("UserId", job.User)
		set("JobState", job.State)
		set("Partition", job.Partition)
		set("SubmitTime", job.Submit)
		set("StartTime", job.Start)
		set("EndTime", job.End)
		set("RunTime", job.Elapsed)
		set("ExitCode", job.ExitCode)
		set("NodeList", job.NodeList)
		set("NumCPUs", job.NCPUS)
		set("AllocTRES", job.AllocTRES)
		set("StdOut", job.StdOut)
		set("StdErr", job.StdErr)
		return JobDetail{Fields: fields, Source: "sacct"}, true, nil
	}
	return JobDetail{}, false, nil
}

// The sacct reconcile runs once at launch (when the last success predates the
// most recent slot) and then once a night, at a per-user minute inside this
// local-time window. A fixed hour, or a cadence anchored to launch time, has a
// whole cluster's stoei sessions hit slurmdbd within the same slow-tier refresh;
// spreading users across the window keeps the nightly load flat. 01:00–05:00
// is the quiet stretch: after the evening submit burst, before the morning one.
const (
	acctWindowStartHour = 1
	acctWindowMinutes   = 4 * 60
)

// acctSlotMinuteFor returns the user's fixed minute inside the nightly window,
// hashed from the username so every session of one user agrees on the slot
// (they already share the stamp) while different users spread uniformly. A
// hash beats persisted randomness: no extra state file, and no file IO when
// AcctDue needs the slot on the UI's Update path.
func acctSlotMinuteFor(username string) int {
	h := fnv.New32a()
	_, _ = h.Write([]byte(username))
	return int(h.Sum32() % acctWindowMinutes)
}

// nextAcctSlot returns the first nightly slot strictly after t, in t's zone:
// today's when t is still ahead of it, otherwise tomorrow's. It goes through
// time.Date so a month end or DST change cannot shift the slot.
func nextAcctSlot(t time.Time, slotMinute int) time.Time {
	y, m, d := t.Date()
	slot := time.Date(y, m, d, acctWindowStartHour, slotMinute, 0, 0, t.Location())
	if slot.After(t) {
		return slot
	}
	return time.Date(y, m, d+1, acctWindowStartHour, slotMinute, 0, 0, t.Location())
}

// acctDue reports whether the nightly slot following the last attempt has
// passed. A zero last (no attempt yet this session) is due at once: the launch
// reconcile, which the stamp then suppresses when another session already ran
// it. The night is the clock's zone; last is converted into it because a stamp
// mtime arrives from the OS in Local regardless of the injected clock.
func (c *Client) acctDue(last time.Time) bool {
	if last.IsZero() {
		return true
	}
	now := c.now()
	return !now.Before(nextAcctSlot(last.In(now.Location()), c.acctSlotMinute))
}

// reconcileAcct merges sacct's terminal records into the journal, at most once
// per nightly slot across sessions (the stamp file). sacct is authoritative
// for jobs that finished while stoei was not watching (their journal record is
// stuck in a live state) and for jobs stoei never observed; live jobs are
// skipped because the squeue journal query owns them and carries richer data.
// On failure — query or journal write — history degrades to journal-only, a
// warning is recorded edge-triggered per session (I9), and the stamp is left
// untouched so a fresh session during the outage still attempts (and warns)
// once; within a session the in-memory gate retries at the next slot.
func (c *Client) reconcileAcct(ctx context.Context) {
	if c.journal == nil {
		return
	}
	c.mu.Lock()
	if !c.acctDue(c.lastAcct) {
		c.mu.Unlock()
		return
	}
	c.lastAcct = c.now()
	c.mu.Unlock()
	// The stamp file's mtime records the last success by any stoei instance, so
	// frequent restarts cost slurmdbd one query per night, not one per launch.
	// The check-then-touch race between concurrent instances is benign (worst
	// case one extra query), so it is not worth a lock.
	if fi, err := os.Stat(c.acctStampPath()); err == nil && !c.acctDue(fi.ModTime()) {
		// Align the in-memory gate with the stamp so the next attempt fires at
		// the slot after the stamp, not the slot after this session noticed it.
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

// mergeAcct filters sacct records down to terminal states and carries fields
// the journal knows better over from its existing record: the requeue count
// (sacct reports none, and a wholesale replace would silently wipe it from the
// history stats) and the log paths (the squeue journal query stores them fully
// expanded, while sacct leaves %j verbatim for array tasks). The
// read-then-upsert pair is not atomic across processes; the window is benign
// (worst case one merge from a slightly stale record).
func (c *Client) mergeAcct(jobs []ControllerJob) []ControllerJob {
	existing := make(map[string]ControllerJob)
	for _, j := range c.journal.all() {
		existing[j.ID] = j
	}
	terminal := jobs[:0]
	for _, j := range jobs {
		if !IsTerminalState(j.State) {
			continue
		}
		prior := existing[j.ID]
		if j.Restart == "" {
			j.Restart = prior.Restart
		}
		if prior.StdOut != "" {
			j.StdOut = prior.StdOut
		}
		if prior.StdErr != "" {
			j.StdErr = prior.StdErr
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
	return c.acctDue(c.lastAcct)
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
