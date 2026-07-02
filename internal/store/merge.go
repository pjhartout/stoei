package store

import (
	"sort"
	"strings"
	"time"

	"github.com/pjhartout/stoei/internal/slurm"
)

// endedHistoryState is the state shown for a history job the journal still
// records as non-terminal but that is no longer in the live queue: its
// completion was never observed (it aged out of the controller, overflowed the
// completion-lookup burst cap, or was running when a prior session ended). Such a
// row would otherwise display a frozen RUNNING. It maps to the neutral color role.
const endedHistoryState = "UNKNOWN"

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
// It first builds the list running-first (tracking a running-id set) so each
// history job whose JobID is already running is deduped away, with Nodes left
// empty and State/Time taken from the journal. The result is then sorted into the
// default display order: status group (pending, then running, then other active
// states, then finished history) and, within each group, newest start first with
// the job id as a deterministic tiebreaker so a refresh never reshuffles equal
// rows. The "o" sort cycle overrides this. This is pure (no IO) and reads only the
// already-fetched RunningJobs and HistoryJobs, so it is safe to call from Refresh
// on every tick and unit-testable in isolation.
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
	// because the journal history view omits it. Once squeue has loaded, a history
	// job the journal still marks non-terminal but that is absent from the live
	// queue has necessarily ended (a genuinely running/pending job is in squeue and
	// was deduped above), so its stale RUNNING is shown as ended rather than frozen.
	for _, job := range s.HistoryJobs {
		if _, running := runningIDs[job.ID]; running {
			continue
		}
		state := job.State
		if s.runningLoaded && !slurm.IsTerminalState(state) {
			state = endedHistoryState
		}
		merged = append(merged, MergedJob{
			ID:         job.ID,
			Name:       job.Name,
			State:      state,
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

	sort.SliceStable(merged, func(i, j int) bool {
		ri, rj := mergedStatusRank(merged[i]), mergedStatusRank(merged[j])
		if ri != rj {
			return ri < rj
		}
		ti, tj := mergedStartKey(merged[i]), mergedStartKey(merged[j])
		if !ti.Equal(tj) {
			return ti.After(tj) // newest start first
		}
		return merged[i].ID < merged[j].ID // deterministic tiebreak so refresh never reshuffles
	})

	return merged
}

// mergedStatusRank groups the default view: pending, running, other active,
// finished. Terminal states rank as finished even while still in squeue (a
// finished job lingers there for MinJobAge), so failed jobs never float above
// pending or running rows.
func mergedStatusRank(j MergedJob) int {
	if !j.Active || slurm.IsTerminalState(j.State) {
		return 3
	}
	s := strings.ToUpper(strings.TrimSpace(j.State))
	if i := strings.IndexByte(s, ' '); i >= 0 {
		s = s[:i]
	}
	switch s {
	case "PENDING", "PD":
		return 0
	case "RUNNING", "R":
		return 1
	default:
		return 2
	}
}

// mergedStartKey is the timestamp the default view sorts by within a status group:
// a job's start time, falling back to its submit time when the start is unknown
// (pending jobs report an N/A start), and the zero time when neither parses (such
// rows sort last under the newest-first order).
func mergedStartKey(j MergedJob) time.Time {
	if t, ok := slurm.ParseSlurmTimestamp(j.StartTime); ok {
		return t
	}
	if t, ok := slurm.ParseSlurmTimestamp(j.SubmitTime); ok {
		return t
	}
	return time.Time{}
}
