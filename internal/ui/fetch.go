package ui

import (
	"context"
	"fmt"
	"time"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
)

// fetchTimeout bounds every Slurm command issued from a fetch Cmd. A superseded
// fetch is additionally dropped by generation in the store (I4); this timeout
// guards against a single command hanging (I5 minus the per-refresh cancel, which
// the Runner owns via exec.CommandContext).
const fetchTimeout = 30 * time.Second

// Result messages. There is one per dataset; each carries the request generation
// it was dispatched with (so the store can drop stale results, I4) and an error
// (so a failure is delivered as data, never a panic, I8). These are tea.Msgs
// handled by the root model's Update.

// availabilityMsg carries the result of the one-shot Slurm-availability check
// fired at startup. A non-nil err means the controller commands are missing and
// the root model renders the full-screen unavailable screen.
type availabilityMsg struct {
	err error
}

// runningJobsMsg carries a running-jobs fetch result.
type runningJobsMsg struct {
	gen  uint64
	jobs []store.RunningJob
	err  error
}

// historyMsg carries a job-history fetch result.
type historyMsg struct {
	gen   uint64
	jobs  []store.HistoryJob
	stats store.HistoryStats
	err   error
}

// completedJobMsg carries the scontrol-sourced final record for a job that just
// left the running queue (found is false when the controller no longer has it or
// it is not yet terminal). It is merged into history without a sacct query.
type completedJobMsg struct {
	job   store.HistoryJob
	found bool
}

// nodesMsg carries a cluster-nodes fetch result.
type nodesMsg struct {
	gen   uint64
	nodes []store.Node
	err   error
}

// allUsersJobsMsg carries an all-users-jobs fetch result.
type allUsersJobsMsg struct {
	gen  uint64
	jobs []store.AllUsersJob
	err  error
}

// fairShareMsg carries a fair-share fetch result.
type fairShareMsg struct {
	gen     uint64
	entries []store.FairShareEntry
	err     error
}

// pendingPrioMsg carries a pending-priority fetch result.
type pendingPrioMsg struct {
	gen     uint64
	entries []store.PriorityEntry
	err     error
}

// runFetch executes fn under a fresh timeout context and recovers from any panic,
// converting it into an error so a fetch Cmd never crashes the program (I8). All
// Slurm IO happens here, inside the Cmd closure goroutine (I1).
func runFetch[T any](fn func(ctx context.Context) (T, error)) (data T, err error) {
	defer func() {
		if r := recover(); r != nil {
			var zero T
			data = zero
			err = fmt.Errorf("panic in fetch: %v", r)
		}
	}()
	ctx, cancel := context.WithTimeout(context.Background(), fetchTimeout)
	defer cancel()
	return fn(ctx)
}

// checkAvailability returns a Cmd that probes Slurm availability once at startup
// and reports the outcome as an availabilityMsg. It is part of the
// minimal-critical first wave so the unavailable screen appears immediately when
// Slurm is missing.
func checkAvailability(client store.SlurmClient) tea.Cmd {
	return func() tea.Msg {
		err := runFetchErr(client.Available)
		return availabilityMsg{err: err}
	}
}

// runFetchErr is the error-only analogue of runFetch for Cmds that return no
// data; it applies the same timeout and panic-recovery guarantees (I8).
func runFetchErr(fn func(ctx context.Context) error) (err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("panic in fetch: %v", r)
		}
	}()
	ctx, cancel := context.WithTimeout(context.Background(), fetchTimeout)
	defer cancel()
	return fn(ctx)
}

// fetchRunningJobs returns a Cmd that loads the current user's running jobs and
// reports them as a runningJobsMsg tagged with gen.
func fetchRunningJobs(client store.SlurmClient, gen uint64) tea.Cmd {
	return func() tea.Msg {
		jobs, err := runFetch(client.RunningJobs)
		return runningJobsMsg{gen: gen, jobs: jobs, err: err}
	}
}

// fetchCompletedJob returns a Cmd that asks the controller (scontrol) for the
// final record of a job that just left the running queue, reporting it as a
// completedJobMsg. A lookup error or a non-terminal/expired job yields found
// false and is silently dropped.
func fetchCompletedJob(client store.SlurmClient, id string) tea.Cmd {
	return func() tea.Msg {
		var found bool
		job, err := runFetch(func(ctx context.Context) (store.HistoryJob, error) {
			j, ok, e := client.CompletedJobRecord(ctx, id)
			found = ok
			return j, e
		})
		if err != nil {
			return completedJobMsg{found: false}
		}
		return completedJobMsg{job: job, found: found}
	}
}

// fetchHistory returns a Cmd that loads the current user's job history for the
// last days days, reporting it as a historyMsg tagged with gen.
func fetchHistory(client store.SlurmClient, gen uint64, days int) tea.Cmd {
	return func() tea.Msg {
		var stats store.HistoryStats
		jobs, err := runFetch(func(ctx context.Context) ([]store.HistoryJob, error) {
			j, s, e := client.JobHistory(ctx, days)
			stats = s
			return j, e
		})
		return historyMsg{gen: gen, jobs: jobs, stats: stats, err: err}
	}
}

// fetchNodes returns a Cmd that loads the cluster node list as a nodesMsg.
func fetchNodes(client store.SlurmClient, gen uint64) tea.Cmd {
	return func() tea.Msg {
		nodes, err := runFetch(client.ClusterNodes)
		return nodesMsg{gen: gen, nodes: nodes, err: err}
	}
}

// fetchAllUsersJobs returns a Cmd that loads all-users jobs as an allUsersJobsMsg.
func fetchAllUsersJobs(client store.SlurmClient, gen uint64) tea.Cmd {
	return func() tea.Msg {
		jobs, err := runFetch(client.AllUsersJobs)
		return allUsersJobsMsg{gen: gen, jobs: jobs, err: err}
	}
}

// fetchFairShare returns a Cmd that loads fair-share data as a fairShareMsg.
func fetchFairShare(client store.SlurmClient, gen uint64) tea.Cmd {
	return func() tea.Msg {
		entries, err := runFetch(client.FairShare)
		return fairShareMsg{gen: gen, entries: entries, err: err}
	}
}

// fetchPendingPrio returns a Cmd that loads pending-priority data as a
// pendingPrioMsg.
func fetchPendingPrio(client store.SlurmClient, gen uint64) tea.Cmd {
	return func() tea.Msg {
		entries, err := runFetch(client.PendingPriority)
		return pendingPrioMsg{gen: gen, entries: entries, err: err}
	}
}
