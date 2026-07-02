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
	// JobHistory returns the current user's job history for the last days days
	// plus aggregate requeue statistics.
	JobHistory(ctx context.Context, days int) ([]slurm.HistoryJob, slurm.HistoryStats, error)
	// ClusterNodes returns every cluster node.
	ClusterNodes(ctx context.Context) ([]slurm.Node, error)
	// FairShare returns fair-share priority data for all users and accounts.
	FairShare(ctx context.Context) ([]slurm.FairShareEntry, error)
	// PendingPriority returns the priority breakdown for all pending jobs.
	PendingPriority(ctx context.Context) ([]slurm.PriorityEntry, error)
	// JobDetail returns the parsed Key=Value detail for a single job.
	JobDetail(ctx context.Context, jobID string) (slurm.JobDetail, error)
	// NodeDetail returns the parsed Key=Value detail for a single node.
	NodeDetail(ctx context.Context, nodeName string) (slurm.JobDetail, error)
	// CancelJob cancels a job via scancel.
	CancelJob(ctx context.Context, jobID string) error
	// CompletedJobRecord returns a history record for a just-finished job sourced
	// from the controller (scontrol), not slurmdbd, so a job that finishes during a
	// session can be merged into history without a sacct query. found is false when
	// the controller no longer has the job or it is not yet in a terminal state.
	CompletedJobRecord(ctx context.Context, jobID string) (slurm.HistoryJob, bool, error)
}

// Compile-time assertion that the concrete client satisfies the interface.
var _ SlurmClient = (*slurm.Client)(nil)
