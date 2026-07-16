package slurm

import (
	"context"
	"errors"
	"fmt"
	"os/user"
	"regexp"
	"strings"
	"sync"
	"time"
)

// journalFetchThrottle bounds how often the per-user journal query is run;
// within this window the existing journal is reused, so refresh waves and rapid
// tab switching cost the controller at most one query.
const journalFetchThrottle = 20 * time.Second

// safeUsername and safeJobID validate CLI inputs before they reach a command, so
// only an alphanumeric-plus-separators username and a numeric job ID (with an
// optional "_task" suffix) are passed through.
var (
	safeUsername = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
	safeJobID    = regexp.MustCompile(`^[0-9]+(_[0-9]+)?$`)
)

// Client builds Slurm commands and parses their output. It wraps a Runner (the
// only seam to the OS). Job history comes from per-user controller snapshots
// accumulated into a persistent journal, never from slurmdbd/sacct. A zero
// Client is not usable; construct one with NewClient.
type Client struct {
	runner Runner
	// username is the resolved current user, used by the per-user getters.
	username string
	// now returns the current time; it is injectable so the fetch throttle can be
	// unit-tested without sleeping. It defaults to time.Now.
	now func() time.Time

	// journal is the persistent record of observed controller jobs; nil disables
	// it (history then reflects only the latest journal query).
	journal *jobJournal

	mu        sync.Mutex
	lastFetch time.Time // last journal query time, for the throttle
}

// Option configures a Client.
type Option func(*Client)

// WithClock overrides the Client's time source. It is used by tests to drive the
// controller-fetch throttle deterministically.
func WithClock(now func() time.Time) Option {
	return func(c *Client) { c.now = now }
}

// WithJournal enables the persistent job journal at path. An empty path leaves
// the journal disabled.
func WithJournal(path string) Option {
	return func(c *Client) {
		if path != "" {
			c.journal = newJobJournal(path)
		}
	}
}

// WithUsername overrides the resolved current username. It is used by tests to
// avoid depending on the host's real user and by callers that already know the
// user.
func WithUsername(name string) Option {
	return func(c *Client) { c.username = name }
}

// NewClient returns a Client that runs commands through r. The current username
// is resolved from the OS (overridable with WithUsername) and the clock defaults
// to time.Now (overridable with WithClock).
func NewClient(r Runner, opts ...Option) *Client {
	c := &Client{runner: r, now: time.Now}
	for _, opt := range opts {
		opt(c)
	}
	if c.username == "" {
		if u, err := user.Current(); err == nil {
			c.username = u.Username
		}
	}
	return c
}

// Username returns the resolved current user the per-user getters query for.
func (c *Client) Username() string { return c.username }

// requiredCommands are the Slurm binaries Available probes; their absence means
// stoei cannot function.
var requiredCommands = []string{"squeue", "scontrol"}

// Available reports whether the Slurm controller commands are usable by probing
// each required binary with "<cmd> --version" through the Runner. A nil return
// means Slurm is available; a non-nil error describes which command failed and is
// rendered on the full-screen unavailable screen. Going through the Runner seam
// keeps the probe subprocess-free in tests.
func (c *Client) Available(ctx context.Context) error {
	for _, cmd := range requiredCommands {
		if _, err := c.runner.Run(ctx, cmd, "--version"); err != nil {
			return fmt.Errorf("SLURM command %q not available: %w", cmd, err)
		}
	}
	return nil
}

// queryJournalJobs runs the per-user "squeue -t all" journal query; user-scoped
// so the controller never dumps the whole cluster (the old "scontrol show jobs").
func (c *Client) queryJournalJobs(ctx context.Context) ([]ControllerJob, error) {
	out, err := c.runner.Run(ctx, "squeue",
		"-u", c.username,
		"-t", "all",
		"--noheader",
		"-O", JournalSqueueFormat,
	)
	if err != nil {
		return nil, err
	}
	return ParseJournalJobs(string(out)), nil
}

// refreshJournalJobs merges the latest journal query into the persistent
// journal, throttled and serialized under mu so a refresh wave queries the
// controller at most once. No-op when the journal is disabled.
func (c *Client) refreshJournalJobs(ctx context.Context) error {
	if c.journal == nil {
		return nil
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.lastFetch.IsZero() && c.now().Sub(c.lastFetch) < journalFetchThrottle {
		return nil
	}
	jobs, err := c.queryJournalJobs(ctx)
	if err != nil {
		return err
	}
	c.lastFetch = c.now()
	return c.journal.upsert(jobs)
}

// journalJobs returns the accumulated controller jobs: the journal when enabled,
// otherwise just the latest journal query.
func (c *Client) journalJobs(ctx context.Context) ([]ControllerJob, error) {
	if err := c.refreshJournalJobs(ctx); err != nil {
		return nil, err
	}
	if c.journal != nil {
		return c.journal.all(), nil
	}
	return c.queryJournalJobs(ctx)
}

// RunningJobs returns the current user's running and pending jobs via
// pipe-delimited "squeue -o". Fields are unpadded because squeue truncates a
// field to its width (%.8T turned "COMPLETED" into "COMPLETE", breaking
// terminal-state detection).
func (c *Client) RunningJobs(ctx context.Context) ([]RunningJob, error) {
	if err := validateUsername(c.username); err != nil {
		return nil, err
	}
	out, err := c.runner.Run(ctx, "squeue",
		"-u", c.username,
		"-o", "%i|%j|%T|%M|%D|%R|%V|%S",
	)
	if err != nil {
		return nil, err
	}
	return ParseRunningJobs(string(out)), nil
}

// AllUsersJobs returns every RUNNING and PENDING job across all users via the
// fixed-width "squeue -O" command with the format
// "JobID:30,Name:50,UserName:15,Partition:15,StateCompact:10,TimeUsed:12,
// NumNodes:6,NodeList:80,tres:80".
func (c *Client) AllUsersJobs(ctx context.Context) ([]AllUsersJob, error) {
	out, err := c.runner.Run(ctx, "squeue",
		"-O", "JobID:30,Name:50,UserName:15,Partition:15,StateCompact:10,TimeUsed:12,NumNodes:6,NodeList:80,tres:80",
		"-a",
		"-t", "RUNNING,PENDING",
		"--noheader",
	)
	if err != nil {
		return nil, err
	}
	return ParseAllUsersJobs(string(out)), nil
}

// JobHistory returns the current user's job history and requeue statistics from
// the journal (never sacct), windowed to the last days days: a job whose most
// recent parseable timestamp is older is excluded. days <= 0 disables the
// window.
func (c *Client) JobHistory(ctx context.Context, days int) ([]HistoryJob, HistoryStats, error) {
	if err := validateUsername(c.username); err != nil {
		return nil, HistoryStats{}, err
	}
	jobs, err := c.journalJobs(ctx)
	if err != nil {
		return nil, HistoryStats{}, err
	}
	var cutoff time.Time
	if days > 0 {
		cutoff = c.now().AddDate(0, 0, -days)
	}
	history, stats := HistoryJobsFor(jobs, c.username, cutoff)
	return history, stats, nil
}

// ClusterNodes returns every cluster node via "scontrol show nodes".
func (c *Client) ClusterNodes(ctx context.Context) ([]Node, error) {
	out, err := c.runner.Run(ctx, "scontrol", "show", "nodes")
	if err != nil {
		return nil, err
	}
	return ParseNodes(string(out)), nil
}

// FairShare returns fair-share priority data for all users and accounts via
// "sshare" with the format
// "Account,User,RawShares,NormShares,RawUsage,NormUsage,EffectvUsage,FairShare".
func (c *Client) FairShare(ctx context.Context) ([]FairShareEntry, error) {
	out, err := c.runner.Run(ctx, "sshare",
		"-a",
		"-P",
		"--noheader",
		"--format=Account,User,RawShares,NormShares,RawUsage,NormUsage,EffectvUsage,FairShare",
	)
	if err != nil {
		return nil, err
	}
	return ParseFairShare(string(out)), nil
}

// PendingPriority returns the priority breakdown for all pending jobs via
// "sprio" with the custom format
// "%.15i|%.15u|%.15a|%.10Y|%.10A|%.10F|%.10J|%.10P|%.10Q".
func (c *Client) PendingPriority(ctx context.Context) ([]PriorityEntry, error) {
	out, err := c.runner.Run(ctx, "sprio",
		"-o", "%.15i|%.15u|%.15a|%.10Y|%.10A|%.10F|%.10J|%.10P|%.10Q",
		"--noheader",
	)
	if err != nil {
		return nil, err
	}
	return ParsePriority(string(out)), nil
}

// JobDetail returns the parsed Key=Value detail for a single job via "scontrol
// show jobid". The controller retains a finished job only briefly, so a job that
// has aged out is reported as not found (there is no sacct fallback). The job ID
// is validated and array-range notation is normalized away before it reaches a
// command.
func (c *Client) JobDetail(ctx context.Context, jobID string) (JobDetail, error) {
	normalized := NormalizeArrayJobID(jobID)
	if err := validateJobID(normalized); err != nil {
		return JobDetail{}, err
	}

	out, err := c.runner.Run(ctx, "scontrol", "show", "jobid", normalized)
	if err != nil {
		// Only scontrol's own "Invalid job id" reads as not-found; a timeout or
		// unreachable controller must not masquerade as the job not existing.
		var ce *CommandError
		if errors.As(err, &ce) && strings.Contains(strings.ToLower(ce.Stderr), "invalid job id") {
			return JobDetail{}, fmt.Errorf("job %s not found: %w", jobID, err)
		}
		return JobDetail{}, fmt.Errorf("job %s: %w", jobID, err)
	}
	records := ParseScontrolJobRecords(strings.TrimSpace(string(out)))
	if len(records) == 0 {
		return JobDetail{}, fmt.Errorf("job %s: could not parse scontrol output", jobID)
	}
	return JobDetail{Fields: pickActiveJobRecord(records), Source: "scontrol"}, nil
}

// pickActiveJobRecord returns the first non-terminal record of a (possibly
// multi-record) scontrol job lookup. An array job lists one record per task and
// the controller retains finished tasks for MinJobAge, so flattening would let
// a recently finished task's state mask a still-active array. When every record
// is terminal the first one stands for the job.
func pickActiveJobRecord(records []map[string]string) map[string]string {
	for _, f := range records {
		if !IsTerminalState(f["JobState"]) {
			return f
		}
	}
	return records[0]
}

// terminalJobStates are the SLURM base job states that mean a job has finished.
// A job in any other state (PENDING, RUNNING, SUSPENDED, COMPLETING, …) is still
// active. The base state is the first whitespace-delimited token of JobState, so
// "CANCELLED by 1001" matches "CANCELLED".
var terminalJobStates = map[string]bool{
	"COMPLETED": true, "FAILED": true, "CANCELLED": true, "TIMEOUT": true,
	"OUT_OF_MEMORY": true, "NODE_FAIL": true, "BOOT_FAIL": true, "DEADLINE": true,
	"PREEMPTED": true, "REVOKED": true, "SPECIAL_EXIT": true,
}

// IsTerminalState reports whether a JobState string denotes a finished job. The
// base state is the first token, so "CANCELLED by 1001" classifies as terminal.
func IsTerminalState(state string) bool {
	base, _, _ := strings.Cut(strings.TrimSpace(state), " ")
	return terminalJobStates[base]
}

// CompletedJobRecord returns a history record for a just-finished job, sourced
// from "scontrol show jobid" (the controller) rather than sacct (slurmdbd), so a
// job that completes mid-session can be merged into the history view without a
// head-node sacct query. The controller retains a finished job only briefly
// (MinJobAge), so the caller must look it up promptly on completion. found is
// false — with a nil error — when the controller no longer has the job or it is
// not yet in a terminal state. It never falls back to sacct.
func (c *Client) CompletedJobRecord(ctx context.Context, jobID string) (HistoryJob, bool, error) {
	normalized := NormalizeArrayJobID(jobID)
	if err := validateJobID(normalized); err != nil {
		return HistoryJob{}, false, err
	}
	out, err := c.runner.Run(ctx, "scontrol", "show", "jobid", normalized)
	if err != nil {
		return HistoryJob{}, false, err
	}
	records := ParseScontrolJobRecords(strings.TrimSpace(string(out)))
	if len(records) == 0 {
		return HistoryJob{}, false, nil
	}
	// The pick is the first non-terminal record, so an array counts as finished
	// only once every retained task record is terminal.
	f := pickActiveJobRecord(records)
	if f["JobId"] == "" || !IsTerminalState(f["JobState"]) {
		return HistoryJob{}, false, nil
	}
	// Persist the terminal record to the journal so the final state survives a
	// restart. The in-memory completion overlay does not, and "scontrol show jobs"
	// may never observe this job again once the controller ages it out (MinJobAge),
	// so without this the journal keeps its last RUNNING snapshot. Best-effort: a
	// journal write must not fail the lookup.
	if c.journal != nil {
		_ = c.journal.upsert([]ControllerJob{controllerJobFromFields(f)})
	}
	return HistoryJob{
		ID:       jobID,
		Name:     f["JobName"],
		State:    f["JobState"],
		Restart:  f["Restarts"],
		Elapsed:  f["RunTime"],
		ExitCode: f["ExitCode"],
		NodeList: f["NodeList"],
		Submit:   f["SubmitTime"],
		Start:    f["StartTime"],
		End:      f["EndTime"],
	}, true, nil
}

// safeNodeName validates a node name before it reaches a command. Node names are
// the same safe character class as usernames (alphanumerics, plus separators).
var safeNodeName = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)

// NodeDetail returns the parsed Key=Value detail for a single node via "scontrol
// show node <name>". The node name is validated, the command run through the
// Runner, and the output parsed into a Key=Value map. The returned
// JobDetail.Fields carries the scontrol fields (Source is "scontrol").
func (c *Client) NodeDetail(ctx context.Context, nodeName string) (JobDetail, error) {
	nodeName = strings.TrimSpace(nodeName)
	if nodeName == "" {
		return JobDetail{}, errors.New("node name cannot be empty")
	}
	if !safeNodeName.MatchString(nodeName) {
		return JobDetail{}, fmt.Errorf("unsafe characters detected in node name: %q", nodeName)
	}
	out, err := c.runner.Run(ctx, "scontrol", "show", "node", nodeName)
	if err != nil {
		return JobDetail{}, fmt.Errorf("scontrol show node %s: %w", nodeName, err)
	}
	fields := ParseScontrolFields(strings.TrimSpace(string(out)))
	if len(fields) == 0 {
		return JobDetail{}, fmt.Errorf("node %s: no information available", nodeName)
	}
	return JobDetail{Fields: fields, Source: "scontrol"}, nil
}

// CancelJob cancels a job via "scancel". A pending array leader ("123_[0-99]")
// is normalized to its base id, which cancels the whole array.
func (c *Client) CancelJob(ctx context.Context, jobID string) error {
	jobID = NormalizeArrayJobID(jobID)
	if err := validateJobID(jobID); err != nil {
		return err
	}
	if _, err := c.runner.Run(ctx, "scancel", jobID); err != nil {
		return fmt.Errorf("scancel error: %w", err)
	}
	return nil
}

// safeUpdateKey validates a "scontrol update" field name before it reaches a
// command.
var safeUpdateKey = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9]*$`)

// UpdateJob modifies one field of a job via "scontrol update JobId=<id>
// Key=Value". The key is validated here; the value is passed through as a single
// argv element (no shell parsing) and scontrol itself validates it, so a refusal
// (e.g. a non-admin raising TimeLimit) surfaces via the wrapped stderr.
func (c *Client) UpdateJob(ctx context.Context, jobID, key, value string) error {
	jobID = NormalizeArrayJobID(jobID)
	if err := validateJobID(jobID); err != nil {
		return err
	}
	key = strings.TrimSpace(key)
	if !safeUpdateKey.MatchString(key) {
		return fmt.Errorf("invalid scontrol field name: %q", key)
	}
	// A JobId field would silently retarget the update to a different job than
	// the one the caller displays and reports on.
	if strings.EqualFold(key, "jobid") {
		return fmt.Errorf("field %q cannot be set via update", key)
	}
	value = strings.TrimSpace(value)
	if value == "" {
		return errors.New("value cannot be empty")
	}
	if _, err := c.runner.Run(ctx, "scontrol", "update", "JobId="+jobID, key+"="+value); err != nil {
		return fmt.Errorf("scontrol update error: %w", err)
	}
	return nil
}

// HoldJob holds (hold=true) or releases (hold=false) a job via "scontrol
// hold|release". A pending array leader is normalized to its base id, which
// holds or releases the whole array.
func (c *Client) HoldJob(ctx context.Context, jobID string, hold bool) error {
	jobID = NormalizeArrayJobID(jobID)
	if err := validateJobID(jobID); err != nil {
		return err
	}
	verb := "release"
	if hold {
		verb = "hold"
	}
	if _, err := c.runner.Run(ctx, "scontrol", verb, jobID); err != nil {
		return fmt.Errorf("scontrol %s error: %w", verb, err)
	}
	return nil
}

// validateUsername enforces the safe-username pattern, rejecting empty or
// unsafe-character usernames before they reach a command.
func validateUsername(username string) error {
	if username == "" {
		return errors.New("username cannot be empty")
	}
	if !safeUsername.MatchString(username) {
		return fmt.Errorf("unsafe characters detected in username: %q", username)
	}
	return nil
}

// validateJobID enforces the safe-job-ID pattern (a number, optionally with a
// single "_task" suffix).
func validateJobID(jobID string) error {
	if jobID == "" {
		return errors.New("job ID cannot be empty")
	}
	if !safeJobID.MatchString(jobID) {
		return fmt.Errorf("invalid job ID format: %q (expected 12345 or 12345_0)", jobID)
	}
	return nil
}
