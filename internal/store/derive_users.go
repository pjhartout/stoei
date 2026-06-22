package store

import (
	"sort"
	"strings"

	"github.com/pjhartout/stoei/internal/slurm"
)

// isPendingState reports whether a job state is pending, recognizing both the
// long form "PENDING" and squeue's "PD" abbreviation.
func isPendingState(state string) bool {
	s := strings.ToUpper(strings.TrimSpace(state))
	return s == "PENDING" || s == "PD"
}

// RunningUserJobs returns the all-users jobs filtered to running (non-pending)
// states, the input expected by the running-job aggregation.
func RunningUserJobs(jobs []slurm.AllUsersJob) []slurm.AllUsersJob {
	out := make([]slurm.AllUsersJob, 0, len(jobs))
	for _, j := range jobs {
		if isPendingState(j.State) {
			continue
		}
		out = append(out, j)
	}
	return out
}

// UserPendingStats is per-user pending-job resource usage, array-expanded.
type UserPendingStats struct {
	Username        string
	PendingJobCount int
	PendingCPUs     int
	PendingMemoryGB float64
	PendingGPUs     int
	PendingGPUTypes string
}

// pendingAccumulator collects per-user pending data before conversion.
type pendingAccumulator struct {
	pendingJobCount int
	pendingCPUs     int
	pendingMemoryGB float64
	pendingGPUs     int
	gpuTypes        map[string]int
}

// AggregatePendingUserStats aggregates pending jobs into per-user statistics,
// expanding array jobs so each task counts once, sorted by pending CPUs
// descending (ties broken by username for determinism).
func AggregatePendingUserStats(jobs []slurm.AllUsersJob) []UserPendingStats {
	byUser := map[string]*pendingAccumulator{}

	for _, job := range jobs {
		if !isPendingState(job.State) {
			continue
		}
		username := strings.TrimSpace(job.User)
		if username == "" {
			continue
		}

		acc := byUser[username]
		if acc == nil {
			acc = &pendingAccumulator{gpuTypes: map[string]int{}}
			byUser[username] = acc
		}

		arraySize := slurm.ParseArraySize(strings.TrimSpace(job.ID))
		acc.pendingJobCount += arraySize

		tres := strings.TrimSpace(job.TRES)
		if tres == "" {
			continue
		}

		res := slurm.ParseTRESResources(tres)
		acc.pendingCPUs += res.CPUs * arraySize
		acc.pendingMemoryGB += res.MemoryGB * float64(arraySize)
		for _, e := range res.GPUs {
			scaled := e.Count * arraySize
			acc.pendingGPUs += scaled
			acc.gpuTypes[e.Type] += scaled
		}
	}

	out := make([]UserPendingStats, 0, len(byUser))
	for username, acc := range byUser {
		out = append(out, UserPendingStats{
			Username:        username,
			PendingJobCount: acc.pendingJobCount,
			PendingCPUs:     acc.pendingCPUs,
			PendingMemoryGB: acc.pendingMemoryGB,
			PendingGPUs:     acc.pendingGPUs,
			PendingGPUTypes: slurm.FormatGPUTypes(acc.gpuTypes),
		})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].PendingCPUs != out[j].PendingCPUs {
			return out[i].PendingCPUs > out[j].PendingCPUs
		}
		return out[i].Username < out[j].Username
	})
	return out
}

// PendingUserStats returns the per-user pending-job summary derived from the
// all-users jobs.
func (s *Store) PendingUserStats() []UserPendingStats {
	return AggregatePendingUserStats(s.AllUsersJobs)
}
