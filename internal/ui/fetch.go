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
// handled by the root model's Update in Phase 3.

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

// energyMsg carries an energy-history fetch result.
type energyMsg struct {
	gen     uint64
	records []store.EnergyRecord
	err     error
}

// waitTimeMsg carries a wait-time history fetch result.
type waitTimeMsg struct {
	gen     uint64
	records []store.WaitTimeRecord
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

// fetchRunningJobs returns a Cmd that loads the current user's running jobs and
// reports them as a runningJobsMsg tagged with gen.
func fetchRunningJobs(client store.SlurmClient, gen uint64) tea.Cmd {
	return func() tea.Msg {
		jobs, err := runFetch(client.RunningJobs)
		return runningJobsMsg{gen: gen, jobs: jobs, err: err}
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

// fetchEnergy returns a Cmd that loads energy history over the last months months
// as an energyMsg.
func fetchEnergy(client store.SlurmClient, gen uint64, months int) tea.Cmd {
	return func() tea.Msg {
		records, err := runFetch(func(ctx context.Context) ([]store.EnergyRecord, error) {
			return client.EnergyHistory(ctx, months)
		})
		return energyMsg{gen: gen, records: records, err: err}
	}
}

// fetchWaitTime returns a Cmd that loads wait-time history over the last hours
// hours as a waitTimeMsg.
func fetchWaitTime(client store.SlurmClient, gen uint64, hours int) tea.Cmd {
	return func() tea.Msg {
		records, err := runFetch(func(ctx context.Context) ([]store.WaitTimeRecord, error) {
			return client.WaitTimeHistory(ctx, hours)
		})
		return waitTimeMsg{gen: gen, records: records, err: err}
	}
}
