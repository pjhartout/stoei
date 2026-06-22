package store

import (
	"context"

	"github.com/pjhartout/stoei/internal/slurm"
)

// SlurmClient is the consumer-side interface the data layer needs from the
// Slurm command layer. It is defined here (not in package slurm) so that the
// store owns the contract it depends on and can be exercised against a
// FakeClient with no real scheduler. The concrete *slurm.Client satisfies it.
//
// Every method takes a context so the caller (a tea.Cmd in the ui layer) can
// impose a timeout and cancel a superseded fetch.
type SlurmClient interface {
	// Available reports whether the Slurm controller commands are usable; a
	// non-nil error means the UI should show the full-screen unavailable screen.
	Available(ctx context.Context) error
	// Username returns the resolved current user the per-user getters query for.
	Username() string
	// RunningJobs returns the current user's running and pending jobs.
	RunningJobs(ctx context.Context) ([]slurm.RunningJob, error)
	// AllUsersJobs returns every RUNNING and PENDING job across all users.
	AllUsersJobs(ctx context.Context) ([]slurm.AllUsersJob, error)
	// UserJobs returns the RUNNING and PENDING jobs for a single user.
	UserJobs(ctx context.Context, username string) ([]slurm.UserJob, error)
	// JobHistory returns the current user's job history for the last days days
	// plus aggregate requeue statistics.
	JobHistory(ctx context.Context, days int) ([]slurm.HistoryJob, slurm.HistoryStats, error)
	// ClusterNodes returns every cluster node.
	ClusterNodes(ctx context.Context) ([]slurm.Node, error)
	// FairShare returns fair-share priority data for all users and accounts.
	FairShare(ctx context.Context) ([]slurm.FairShareEntry, error)
	// PendingPriority returns the priority breakdown for all pending jobs.
	PendingPriority(ctx context.Context) ([]slurm.PriorityEntry, error)
	// EnergyHistory returns completed jobs across all users over the last months
	// months for energy estimation.
	EnergyHistory(ctx context.Context, months int) ([]slurm.EnergyRecord, error)
	// WaitTimeHistory returns all-users jobs that started within the last hours
	// hours, for wait-time analysis.
	WaitTimeHistory(ctx context.Context, hours int) ([]slurm.WaitTimeRecord, error)
	// JobDetail returns the parsed Key=Value detail for a single job.
	JobDetail(ctx context.Context, jobID string) (slurm.JobDetail, error)
	// NodeDetail returns the parsed Key=Value detail for a single node.
	NodeDetail(ctx context.Context, nodeName string) (slurm.JobDetail, error)
	// CancelJob cancels a job via scancel.
	CancelJob(ctx context.Context, jobID string) error
}

// Compile-time assertion that the concrete client satisfies the interface.
var _ SlurmClient = (*slurm.Client)(nil)

// IsSacctUnavailable reports whether err indicates the sacct history backend
// (slurmdbd) is unreachable: either the active retry cooldown after a hard
// failure, or a fresh "connection refused" failure. The ui layer uses it to
// surface an informative toast without importing internal/slurm directly.
func IsSacctUnavailable(err error) bool {
	if err == nil {
		return false
	}
	return slurm.ErrSacctCooldown(err) || slurm.IsConnectionRefused(err)
}

// ErrSacctConnectionRefused is a ready-made connection-refused error in the exact
// shape ExecRunner produces (a *slurm.CommandError whose stderr carries the
// signal). It lets ui tests exercise the informative-toast path without importing
// internal/slurm directly. IsSacctUnavailable reports true for it.
var ErrSacctConnectionRefused error = &slurm.CommandError{
	Name:   "sacct",
	Stderr: "sacct: error: slurmdbd: Connection refused",
}
