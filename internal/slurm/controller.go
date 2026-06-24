package slurm

import (
	"sort"
	"strconv"
	"strings"
)

// ControllerJob is one job as reported by "scontrol show jobs": the controller's
// live view, covering running, pending, and recently finished jobs (the
// controller retains a finished job only briefly). It is the sacct-free source
// for job history; persisted into the on-disk journal it
// accumulates across runs into a durable record.
type ControllerJob struct {
	ID        string
	User      string
	Name      string
	State     string
	Partition string
	Submit    string
	Start     string
	End       string
	Elapsed   string
	ExitCode  string
	Restart   string
	NodeList  string
	NCPUS     string
	AllocTRES string
}

// ParseControllerJobs parses "scontrol show jobs" output into one ControllerJob
// per job block. scontrol separates job blocks with a blank line, and each block
// is the same Key=Value format as "scontrol show jobid", so ParseScontrolFields
// handles a single block.
func ParseControllerJobs(raw string) []ControllerJob {
	var jobs []ControllerJob
	for _, block := range strings.Split(strings.TrimSpace(raw), "\n\n") {
		f := ParseScontrolFields(strings.TrimSpace(block))
		if f["JobId"] == "" {
			continue
		}
		jobs = append(jobs, ControllerJob{
			ID:        f["JobId"],
			User:      userName(f["UserId"]),
			Name:      f["JobName"],
			State:     baseState(f["JobState"]),
			Partition: f["Partition"],
			Submit:    f["SubmitTime"],
			Start:     f["StartTime"],
			End:       f["EndTime"],
			Elapsed:   f["RunTime"],
			ExitCode:  f["ExitCode"],
			Restart:   f["Restarts"],
			NodeList:  f["NodeList"],
			NCPUS:     f["NumCPUs"],
			AllocTRES: f["TRES"],
		})
	}
	return jobs
}

// userName extracts the login name from a scontrol "UserId=name(uid)" value.
func userName(userID string) string {
	if i := strings.IndexByte(userID, '('); i >= 0 {
		return userID[:i]
	}
	return userID
}

// baseState returns the first token of a JobState, so "CANCELLED by 1001"
// classifies as "CANCELLED".
func baseState(state string) string {
	base, _, _ := strings.Cut(strings.TrimSpace(state), " ")
	return base
}

// HistoryJobsFor derives the current user's job-history rows (newest first) and
// requeue statistics from journal jobs. An empty username returns every job.
func HistoryJobsFor(jobs []ControllerJob, username string) ([]HistoryJob, HistoryStats) {
	var out []HistoryJob
	stats := HistoryStats{}
	for _, j := range jobs {
		if username != "" && j.User != username {
			continue
		}
		out = append(out, HistoryJob{
			ID: j.ID, Name: j.Name, State: j.State, Restart: j.Restart,
			Elapsed: j.Elapsed, ExitCode: j.ExitCode, NodeList: j.NodeList,
			Submit: j.Submit, Start: j.Start, End: j.End,
		})
		if n, err := strconv.Atoi(j.Restart); err == nil {
			stats.TotalRequeues += n
			if n > stats.MaxRequeues {
				stats.MaxRequeues = n
			}
		}
	}
	stats.TotalJobs = len(out)
	sort.SliceStable(out, func(a, b int) bool { return out[a].Submit > out[b].Submit })
	return out, stats
}
