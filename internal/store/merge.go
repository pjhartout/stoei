package store

// MergedJob is one row of the Jobs tab's unified job list: the current user's
// running/pending jobs followed by their completed/failed history jobs. It is the
// display shape the Jobs tab renders (JobID, Name, State, Time, Nodes, NodeList),
// mirroring cache.Job.as_row in the Python port.
type MergedJob struct {
	// ID is the job id, the stable key used for filtering, sorting and cursor
	// restoration (I6).
	ID string
	// Name is the job name.
	Name string
	// State is the scheduler state (for running jobs from squeue, for completed
	// jobs from sacct).
	State string
	// Time is the running/elapsed time: squeue %M for active jobs, sacct Elapsed
	// for history jobs.
	Time string
	// Nodes is the node count for active jobs; it is always empty for history jobs
	// because sacct's history format does not carry it (cache.py sets nodes="").
	Nodes string
	// NodeList is the allocated node list.
	NodeList string
	// Active is true for running/pending jobs and false for history jobs.
	Active bool
}

// MergedJobs returns the unified running-plus-history job list for the Jobs tab.
// It mirrors stoei/slurm/cache.py JobCache._build_from_data exactly (cache.py
// lines 182-238): the current user's running/pending jobs come first, tracked in
// a running-id set; then each history job whose JobID is not already running is
// appended (dedup) with Nodes left empty and State/Time taken from sacct. This is
// pure (no IO) and reads only the already-fetched RunningJobs and HistoryJobs, so
// it is safe to call from Refresh on every tick and unit-testable in isolation.
func (s *Store) MergedJobs() []MergedJob {
	merged := make([]MergedJob, 0, len(s.RunningJobs)+len(s.HistoryJobs))
	runningIDs := make(map[string]struct{}, len(s.RunningJobs))

	// Running/pending jobs first (cache.py lines 186-212).
	for _, job := range s.RunningJobs {
		runningIDs[job.ID] = struct{}{}
		merged = append(merged, MergedJob{
			ID:       job.ID,
			Name:     job.Name,
			State:    job.State,
			Time:     job.Time,
			Nodes:    job.Nodes,
			NodeList: job.NodeList,
			Active:   true,
		})
	}

	// History jobs, skipping any already present as a running job (cache.py lines
	// 214-238). Nodes is empty because sacct's history format omits it.
	for _, job := range s.HistoryJobs {
		if _, running := runningIDs[job.ID]; running {
			continue
		}
		merged = append(merged, MergedJob{
			ID:       job.ID,
			Name:     job.Name,
			State:    job.State,
			Time:     job.Elapsed,
			Nodes:    "",
			NodeList: job.NodeList,
			Active:   false,
		})
	}

	return merged
}
