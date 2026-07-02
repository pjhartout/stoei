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

// controllerFetchThrottle bounds how often "scontrol show jobs" is run to refresh
// the job journal. Job history derives from the journal; within this window the
// existing
// journal is reused so the controller is queried at most once per refresh wave.
const controllerFetchThrottle = 3 * time.Second

// safeUsername and safeJobID validate CLI inputs before they reach a command, so
// only an alphanumeric-plus-separators username and a numeric job ID (with an
// optional "_task" suffix) are passed through.
var (
	safeUsername = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
	safeJobID    = regexp.MustCompile(`^[0-9]+(_[0-9]+)?$`)
)

// Client builds Slurm commands and parses their output. It wraps a Runner (the
// only seam to the OS). Job history comes from the controller ("scontrol show
// jobs") accumulated into a persistent journal, never from slurmdbd/sacct. A
// zero Client is not usable; construct one with NewClient.
type Client struct {
	runner Runner
	// username is the resolved current user, used by the per-user getters.
	username string
	// now returns the current time; it is injectable so the fetch throttle can be
	// unit-tested without sleeping. It defaults to time.Now.
	now func() time.Time

	// journal is the persistent record of observed controller jobs; nil disables
	// it (history then reflects only the latest controller fetch).
	journal *jobJournal

	mu        sync.Mutex
	lastFetch time.Time // last "scontrol show jobs" time, for the throttle
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

// refreshControllerJobs runs "scontrol show jobs" and merges the result into the
// persistent journal, throttled so rapid history fetches (e.g. a manual refresh)
// query the controller at most once. It is a no-op when the
// journal is disabled. Holding mu across the run serializes the wave: the first
// caller fetches, the rest fall inside the throttle window and reuse the journal.
func (c *Client) refreshControllerJobs(ctx context.Context) error {
	if c.journal == nil {
		return nil
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.lastFetch.IsZero() && c.now().Sub(c.lastFetch) < controllerFetchThrottle {
		return nil
	}
	out, err := c.runner.Run(ctx, "scontrol", "show", "jobs")
	if err != nil {
		return err
	}
	c.lastFetch = c.now()
	return c.journal.upsert(ParseControllerJobs(string(out)))
}

// journalJobs returns the accumulated controller jobs: the journal when enabled,
// otherwise just the latest controller fetch.
func (c *Client) journalJobs(ctx context.Context) ([]ControllerJob, error) {
	if err := c.refreshControllerJobs(ctx); err != nil {
		return nil, err
	}
	if c.journal != nil {
		return c.journal.all(), nil
	}
	out, err := c.runner.Run(ctx, "scontrol", "show", "jobs")
	if err != nil {
		return nil, err
	}
	return ParseControllerJobs(string(out)), nil
}

// RunningJobs returns the current user's running and pending jobs via the
// pipe-delimited "squeue -o" command with the format string
// "%i|%j|%T|%M|%D|%R|%V|%S". The fields are deliberately unpadded: squeue
// truncates a field to its width (a %.8T state renders "COMPLETED" as
// "COMPLETE"), which broke terminal-state detection for jobs lingering in the
// queue after finishing; pipe-delimited parsing needs no widths at all.
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

// UserJobs returns the RUNNING and PENDING jobs for username via the fixed-width
// "squeue -O" command without the UserName column, using the format
// "JobID:30,Name:50,Partition:15,StateCompact:10,TimeUsed:12,NumNodes:6,
// NodeList:80,tres:80".
func (c *Client) UserJobs(ctx context.Context, username string) ([]UserJob, error) {
	username = strings.TrimSpace(username)
	if err := validateUsername(username); err != nil {
		return nil, err
	}
	out, err := c.runner.Run(ctx, "squeue",
		"-u", username,
		"-O", "JobID:30,Name:50,Partition:15,StateCompact:10,TimeUsed:12,NumNodes:6,NodeList:80,tres:80",
		"-t", "RUNNING,PENDING",
		"--noheader",
	)
	if err != nil {
		return nil, err
	}
	return ParseUserJobs(string(out)), nil
}

// JobHistory returns the current user's job history plus aggregate requeue
// statistics, derived from the controller-jobs journal rather than sacct. The
// days argument is accepted for API compatibility but no longer bounds the
// window: history is whatever the journal has accumulated, since the controller
// has no historical query.
func (c *Client) JobHistory(ctx context.Context, _ int) ([]HistoryJob, HistoryStats, error) {
	if err := validateUsername(c.username); err != nil {
		return nil, HistoryStats{}, err
	}
	jobs, err := c.journalJobs(ctx)
	if err != nil {
		return nil, HistoryStats{}, err
	}
	history, stats := HistoryJobsFor(jobs, c.username)
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
		return JobDetail{}, fmt.Errorf("job %s not found: %w", jobID, err)
	}
	fields := ParseScontrolFields(strings.TrimSpace(string(out)))
	if len(fields) == 0 {
		return JobDetail{}, fmt.Errorf("job %s: could not parse scontrol output", jobID)
	}
	return JobDetail{Fields: fields, Source: "scontrol"}, nil
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
	f := ParseScontrolFields(strings.TrimSpace(string(out)))
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

// CancelJob cancels a job via "scancel". The job ID is validated first. A nil
// error means scancel reported success.
func (c *Client) CancelJob(ctx context.Context, jobID string) error {
	if err := validateJobID(jobID); err != nil {
		return err
	}
	if _, err := c.runner.Run(ctx, "scancel", jobID); err != nil {
		return fmt.Errorf("scancel error: %w", err)
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
