package store

import "github.com/pjhartout/stoei/internal/slurm"

// Re-exported Slurm data types. The ui layer must not import internal/slurm
// directly (the depguard ui->store->slurm rule), so the store re-exports the
// plain data types that flow up to the ui in fetch-result messages. These are
// type aliases, so a store.RunningJob is identical to a slurm.RunningJob and no
// conversion is needed at the seam.
type (
	// RunningJob is one of the current user's running/pending jobs.
	RunningJob = slurm.RunningJob
	// AllUsersJob is one running/pending job across all users.
	AllUsersJob = slurm.AllUsersJob
	// HistoryJob is one job from the journal-backed history.
	HistoryJob = slurm.HistoryJob
	// HistoryStats are the aggregate requeue counters from a history query.
	HistoryStats = slurm.HistoryStats
	// Node is one cluster node from "scontrol show nodes".
	Node = slurm.Node
	// FairShareEntry is one row of sshare output.
	FairShareEntry = slurm.FairShareEntry
	// PriorityEntry is one pending job's priority breakdown from sprio.
	PriorityEntry = slurm.PriorityEntry
	// JobDetail is the parsed key/value detail for a single job.
	JobDetail = slurm.JobDetail
	// GPUEntry is a single GPU allocation parsed from a TRES or Gres string.
	GPUEntry = slurm.GPUEntry
)
