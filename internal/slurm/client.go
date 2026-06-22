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

// sacctRetryCooldown is how long batch sacct calls are suppressed after a
// non-transient ("connection refused") failure. Ports
// commands._SACCT_RETRY_COOLDOWN.
const sacctRetryCooldown = 5 * time.Minute

// safeUsername and safeJobID validate CLI inputs before they reach a command,
// porting validation.SAFE_USERNAME_PATTERN and SAFE_JOBID_PATTERN.
var (
	safeUsername = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
	safeJobID    = regexp.MustCompile(`^[0-9]+(_[0-9]+)?$`)
)

// sacctJobFields are the columns requested for on-demand single-job sacct
// lookups. Ports commands.SACCT_JOB_FIELDS.
var sacctJobFields = []string{
	"JobID", "JobName", "User", "Account", "Partition", "State", "ExitCode",
	"Start", "End", "Elapsed", "TimelimitRaw", "NNodes", "NCPUS", "NTasks",
	"ReqMem", "MaxRSS", "MaxVMSize", "NodeList", "WorkDir", "StdOut", "StdErr",
	"Submit", "Priority", "QOS",
}

// SacctJobFields returns the field list used for single-job sacct queries.
func SacctJobFields() []string { return sacctJobFields }

// Client builds Slurm commands and parses their output. It wraps a Runner (the
// only seam to the OS) and tracks slurmdbd availability so that batch sacct calls
// are skipped during a cooldown after a hard failure. A zero Client is not
// usable; construct one with NewClient.
type Client struct {
	runner Runner
	// username is the resolved current user, used by the per-user getters.
	username string
	// now returns the current time; it is injectable so the sacct cooldown can be
	// unit-tested without sleeping. It defaults to time.Now.
	now func() time.Time

	mu         sync.Mutex
	sacctFailo *time.Time // last hard sacct failure, or nil when healthy
}

// Option configures a Client.
type Option func(*Client)

// WithClock overrides the Client's time source. It is used by tests to drive the
// sacct cooldown deterministically.
func WithClock(now func() time.Time) Option {
	return func(c *Client) { c.now = now }
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
// stoei cannot function. Ports validation.check_slurm_available.
var requiredCommands = []string{"squeue", "scontrol", "sacct"}

// Available reports whether the Slurm controller commands are usable by probing
// each required binary with "<cmd> --version" through the Runner. A nil return
// means Slurm is available; a non-nil error describes which command failed and is
// rendered on the full-screen unavailable screen. It mirrors the Python
// check_slurm_available presence check while going through the Runner seam so it
// stays subprocess-free in tests.
func (c *Client) Available(ctx context.Context) error {
	for _, cmd := range requiredCommands {
		if _, err := c.runner.Run(ctx, cmd, "--version"); err != nil {
			return fmt.Errorf("SLURM command %q not available: %w", cmd, err)
		}
	}
	return nil
}

// errSacctCooldown is returned by the batch sacct getters when slurmdbd is in the
// post-failure cooldown window. Callers can detect it with errors.Is.
var errSacctCooldown = errors.New("sacct unavailable: connection refused (will retry automatically)")

// ErrSacctCooldown reports whether err indicates the sacct cooldown is active.
func ErrSacctCooldown(err error) bool { return errors.Is(err, errSacctCooldown) }

// IsConnectionRefused reports whether err carries a slurmdbd "connection refused"
// signal, exposed so the store/ui layers can classify a history failure for an
// informative toast.
func IsConnectionRefused(err error) bool { return isConnectionRefused(err) }

// sacctAvailable reports whether batch sacct calls may proceed: true when there
// has been no hard failure or when the cooldown has elapsed. Ports
// commands._sacct_is_available.
func (c *Client) sacctAvailable() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.sacctFailo == nil {
		return true
	}
	return c.now().Sub(*c.sacctFailo) >= sacctRetryCooldown
}

// sacctMarkFailure records a non-transient sacct failure and (re)starts the
// cooldown. Ports commands._sacct_mark_failure.
func (c *Client) sacctMarkFailure() {
	c.mu.Lock()
	defer c.mu.Unlock()
	t := c.now()
	c.sacctFailo = &t
}

// sacctMarkSuccess clears the sacct failure state after a successful batch call.
// Ports commands._sacct_mark_success.
func (c *Client) sacctMarkSuccess() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.sacctFailo = nil
}

// isConnectionRefused reports whether err carries a "connection refused" signal,
// the non-transient error that trips the cooldown. It first inspects a
// *CommandError's captured stderr (the slurmdbd-down case prints "connection
// refused" only to stderr and still exits 0), then falls back to the error text
// so plain errors are still classified.
func isConnectionRefused(err error) bool {
	if err == nil {
		return false
	}
	var ce *CommandError
	if errors.As(err, &ce) && hasHardFailureSignal(ce.Stderr) {
		return true
	}
	return strings.Contains(strings.ToLower(err.Error()), connectionRefusedSignal)
}

// RunningJobs returns the current user's running and pending jobs via the
// pipe-delimited "squeue -o" command. It matches get_running_jobs's format
// string "%.30i|%.50j|%.8T|%.10M|%.4D|%.12R|%.19V|%.19S".
func (c *Client) RunningJobs(ctx context.Context) ([]RunningJob, error) {
	if err := validateUsername(c.username); err != nil {
		return nil, err
	}
	out, err := c.runner.Run(ctx, "squeue",
		"-u", c.username,
		"-o", "%.30i|%.50j|%.8T|%.10M|%.4D|%.12R|%.19V|%.19S",
	)
	if err != nil {
		return nil, err
	}
	return ParseRunningJobs(string(out)), nil
}

// AllUsersJobs returns every RUNNING and PENDING job across all users via the
// fixed-width "squeue -O" command. It matches get_all_running_jobs's format
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
// "squeue -O" command without the UserName column. It matches get_user_jobs's
// format "JobID:30,Name:50,Partition:15,StateCompact:10,TimeUsed:12,NumNodes:6,
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

// JobHistory returns the current user's job history for the last days days via
// sacct, plus aggregate requeue statistics. It honors the sacct cooldown: when
// slurmdbd recently refused a connection the call is skipped and ErrSacctCooldown
// is returned. The format matches get_job_history:
// "JobID,JobName,State,Restart,Elapsed,ExitCode,NodeList,Submit,Start,End".
func (c *Client) JobHistory(ctx context.Context, days int) ([]HistoryJob, HistoryStats, error) {
	if !c.sacctAvailable() {
		return nil, HistoryStats{}, errSacctCooldown
	}
	if err := validateUsername(c.username); err != nil {
		return nil, HistoryStats{}, err
	}
	out, err := c.runner.Run(ctx, "sacct",
		"-u", c.username,
		"--format=JobID,JobName,State,Restart,Elapsed,ExitCode,NodeList,Submit,Start,End",
		"-S", fmt.Sprintf("now-%ddays", days),
		"-X",
		"-P",
	)
	if err != nil {
		if isConnectionRefused(err) {
			c.sacctMarkFailure()
		}
		return nil, HistoryStats{}, err
	}
	c.sacctMarkSuccess()
	jobs, stats := ParseHistory(string(out))
	return jobs, stats, nil
}

// EnergyHistory returns completed jobs for all users over the last months months
// for energy estimation, via sacct. It honors the sacct cooldown. The format
// matches get_energy_job_history ("JobID,User,Elapsed,NCPUS,AllocTRES,State")
// with the start date computed as now - months*30 days, formatted YYYY-MM-DD, to
// match the Python getter which avoids the unreliable "now-Xmonths" syntax.
func (c *Client) EnergyHistory(ctx context.Context, months int) ([]EnergyRecord, error) {
	if !c.sacctAvailable() {
		return nil, errSacctCooldown
	}
	start := c.now().AddDate(0, 0, -months*30).Format("2006-01-02")
	out, err := c.runner.Run(ctx, "sacct",
		"--allusers",
		"--format=JobID,User,Elapsed,NCPUS,AllocTRES,State",
		"-S", start,
		"-X",
		"-P",
		"--noheader",
	)
	if err != nil {
		if isConnectionRefused(err) {
			c.sacctMarkFailure()
		}
		return nil, err
	}
	c.sacctMarkSuccess()
	return ParseEnergyRecords(string(out)), nil
}

// WaitTimeHistory returns all-users jobs that started within the last hours hours
// via sacct, for wait-time analysis. It honors the sacct cooldown. The format
// matches get_wait_time_job_history ("JobID,Partition,State,Submit,Start") with
// the "now-Nhours" start window.
func (c *Client) WaitTimeHistory(ctx context.Context, hours int) ([]WaitTimeRecord, error) {
	if !c.sacctAvailable() {
		return nil, errSacctCooldown
	}
	out, err := c.runner.Run(ctx, "sacct",
		"--allusers",
		"--format=JobID,Partition,State,Submit,Start",
		"-S", fmt.Sprintf("now-%dhours", hours),
		"-X",
		"-P",
		"--noheader",
	)
	if err != nil {
		if isConnectionRefused(err) {
			c.sacctMarkFailure()
		}
		return nil, err
	}
	c.sacctMarkSuccess()
	return ParseWaitTimeRecords(string(out)), nil
}

// ClusterNodes returns every cluster node via "scontrol show nodes". It matches
// get_cluster_nodes.
func (c *Client) ClusterNodes(ctx context.Context) ([]Node, error) {
	out, err := c.runner.Run(ctx, "scontrol", "show", "nodes")
	if err != nil {
		return nil, err
	}
	return ParseNodes(string(out)), nil
}

// FairShare returns fair-share priority data for all users and accounts via
// "sshare". It matches get_fair_share_priority's format
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
// "sprio". It matches get_pending_job_priority's custom format
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

// JobDetail returns the parsed Key=Value detail for a single job. It first tries
// "scontrol show jobid" (best for active jobs) and falls back to a single-job
// sacct lookup for completed jobs. The sacct fallback is on-demand and therefore
// bypasses the batch cooldown, matching get_job_info_parsed and Python commit
// c7a240f. The job ID is validated and array-range notation is normalized away
// before it reaches a command.
func (c *Client) JobDetail(ctx context.Context, jobID string) (JobDetail, error) {
	normalized := NormalizeArrayJobID(jobID)
	if err := validateJobID(normalized); err != nil {
		return JobDetail{}, err
	}

	out, err := c.runner.Run(ctx, "scontrol", "show", "jobid", normalized)
	if err == nil {
		fields := ParseScontrolFields(strings.TrimSpace(string(out)))
		if len(fields) > 0 {
			return JobDetail{Fields: fields, Source: "scontrol"}, nil
		}
	}

	// Fall back to sacct (on-demand: bypasses the cooldown).
	sacctOut, sacctErr := c.runner.Run(ctx, "sacct",
		"-j", normalized,
		"--format="+strings.Join(sacctJobFields, ","),
		"-P",
		"--noheader",
	)
	if sacctErr != nil {
		return JobDetail{}, fmt.Errorf("job %s not found: scontrol err=%v sacct err=%w", jobID, err, sacctErr)
	}
	fields := ParseJobDetail(string(sacctOut), sacctJobFields)
	if len(fields) == 0 {
		return JobDetail{}, fmt.Errorf("job %s: could not parse sacct output", jobID)
	}
	return JobDetail{Fields: fields, Source: "sacct"}, nil
}

// CancelJob cancels a job via "scancel". The job ID is validated first. A nil
// error means scancel reported success. Ports cancel_job.
func (c *Client) CancelJob(ctx context.Context, jobID string) error {
	if err := validateJobID(jobID); err != nil {
		return err
	}
	if _, err := c.runner.Run(ctx, "scancel", jobID); err != nil {
		return fmt.Errorf("scancel error: %w", err)
	}
	return nil
}

// validateUsername enforces the safe-username pattern. Ports validate_username.
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
// single "_task" suffix). Ports validate_job_id.
func validateJobID(jobID string) error {
	if jobID == "" {
		return errors.New("job ID cannot be empty")
	}
	if !safeJobID.MatchString(jobID) {
		return fmt.Errorf("invalid job ID format: %q (expected 12345 or 12345_0)", jobID)
	}
	return nil
}
