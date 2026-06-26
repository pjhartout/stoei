package store

// MergedJob is one row of the Jobs tab's unified job list: the current user's
// running/pending jobs followed by their completed/failed history jobs. It is the
// display shape the Jobs tab renders (JobID, Name, State, Time, Nodes, NodeList,
// Timeline).
type MergedJob struct {
	// ID is the job id, the stable key used for filtering, sorting and cursor
	// restoration (I6).
	ID string
	// Name is the job name.
	Name string
	// State is the scheduler state (for running jobs from squeue, for completed
	// jobs from the controller journal).
	State string
	// Time is the running/elapsed time: squeue %M for active jobs, the journal's
	// RunTime for history jobs.
	Time string
	// Nodes is the node count for active jobs; it is always empty for history jobs
	// because the journal history view does not carry it.
	Nodes string
	// NodeList is the allocated node list.
	NodeList string
	// Active is true for running/pending jobs and false for history jobs.
	Active bool

	// SubmitTime, StartTime, and EndTime are the raw SLURM timestamps used to
	// render the compact Timeline cell. Active jobs (from squeue) carry submit and
	// start but no end; history jobs (from the journal) carry all three.
	SubmitTime string
	StartTime  string
	EndTime    string
	// Restarts is the requeue count, parsed from the journal's Restart field for
	// history jobs (active jobs report 0).
	Restarts int
}

// MergedJobs returns the unified running-plus-history job list for the Jobs tab.
// The current user's running/pending jobs come first, tracked in a running-id
// set; then each history job whose JobID is not already running is appended
// (dedup) with Nodes left empty and State/Time taken from the journal. This is pure (no
// IO) and reads only the already-fetched RunningJobs and HistoryJobs, so it is
// safe to call from Refresh on every tick and unit-testable in isolation.
func (s *Store) MergedJobs() []MergedJob {
	merged := make([]MergedJob, 0, len(s.RunningJobs)+len(s.HistoryJobs))
	runningIDs := make(map[string]struct{}, len(s.RunningJobs))

	// Running/pending jobs first.
	for _, job := range s.RunningJobs {
		runningIDs[job.ID] = struct{}{}
		merged = append(merged, MergedJob{
			ID:         job.ID,
			Name:       job.Name,
			State:      job.State,
			Time:       job.Time,
			Nodes:      job.Nodes,
			NodeList:   job.NodeList,
			Active:     true,
			SubmitTime: job.SubmitTime,
			StartTime:  job.StartTime,
		})
	}

	// History jobs, skipping any already present as a running job. Nodes is empty
	// because the journal history view omits it.
	for _, job := range s.HistoryJobs {
		if _, running := runningIDs[job.ID]; running {
			continue
		}
		merged = append(merged, MergedJob{
			ID:         job.ID,
			Name:       job.Name,
			State:      job.State,
			Time:       job.Elapsed,
			Nodes:      "",
			NodeList:   job.NodeList,
			Active:     false,
			SubmitTime: job.Submit,
			StartTime:  job.Start,
			EndTime:    job.End,
			Restarts:   parseRestarts(job.Restart),
		})
	}

	return merged
}
