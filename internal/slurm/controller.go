package slurm

import (
	"sort"
	"strconv"
	"strings"
	"time"
)

// ControllerJob is one job from the controller's live view (the per-user
// "squeue -t all" journal query or a "scontrol show jobid" block); persisted
// into the journal it is the sacct-free source for job history.
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

// JournalSqueueFormat is the fixed-width "squeue -O" layout of the journal
// query; tres-alloc is last so the line remainder absorbs long TRES strings.
const JournalSqueueFormat = "JobId:30,ArrayJobId:20,ArrayTaskId:20,UserName:15," +
	"Name:50,State:20,Partition:15,SubmitTime:25,StartTime:25,EndTime:25," +
	"TimeUsed:15,exit_code:10,RestartCnt:10,NumCPUs:10,NodeList:80,tres-alloc:200"

// journalColEnds are the cumulative column end offsets of JournalSqueueFormat,
// with tres-alloc taking the remainder.
var journalColEnds = []int{30, 50, 70, 85, 135, 155, 170, 195, 220, 245, 260, 270, 280, 290, 370}

// ParseJournalJobs parses fixed-width "squeue -O" journal output into
// ControllerJob records, normalizing ids to the squeue %i array form.
func ParseJournalJobs(raw string) []ControllerJob {
	var jobs []ControllerJob
	for _, line := range strings.Split(strings.TrimSpace(raw), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		f := sliceFixedWidth(line, journalColEnds)
		if f[0] == "" {
			continue
		}
		jobs = append(jobs, ControllerJob{
			ID:        journalJobID(f[0], f[1], f[2]),
			User:      f[3],
			Name:      f[4],
			State:     baseState(f[5]),
			Partition: f[6],
			Submit:    f[7],
			Start:     f[8],
			End:       f[9],
			Elapsed:   f[10],
			ExitCode:  f[11],
			Restart:   f[12],
			NCPUS:     f[13],
			NodeList:  f[14],
			AllocTRES: f[15],
		})
	}
	return jobs
}

// journalJobID rewrites a dispatched array task to "<ArrayJobId>_<ArrayTaskId>"
// (matching squeue %i); plain jobs and pending array leaders keep the raw id.
func journalJobID(jobID, arrayJobID, arrayTaskID string) string {
	if arrayJobID != "" && arrayTaskID != "" {
		if _, err := strconv.Atoi(arrayTaskID); err == nil {
			return arrayJobID + "_" + arrayTaskID
		}
	}
	return jobID
}

// controllerJobFromFields builds a ControllerJob from one parsed scontrol
// Key=Value block. The id is keyed to match squeue %i (controllerJobID) and the
// state is reduced to its base token, so a single "scontrol show jobid" block and
// a block from "scontrol show jobs" yield the same shape.
func controllerJobFromFields(f map[string]string) ControllerJob {
	return ControllerJob{
		ID:        controllerJobID(f),
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
	}
}

// controllerJobID returns the job id keyed to match squeue %i. A dispatched
// array task is reported by scontrol with a distinct per-task JobId (e.g. 12350)
// alongside ArrayJobId/ArrayTaskId, but squeue and the completion overlay key it
// as "<ArrayJobId>_<ArrayTaskId>" (e.g. 12345_3). Using that form keeps the
// journal/history id aligned so the live running row dedups the journal copy and
// a completion supersedes it; otherwise the array task lingers as a frozen,
// duplicate RUNNING row. Only a single numeric ArrayTaskId is rewritten; a
// pending range or list keeps the raw JobId (it is the array-leader id, not the
// frozen-RUNNING case).
func controllerJobID(f map[string]string) string {
	aj, at := f["ArrayJobId"], f["ArrayTaskId"]
	if aj != "" && at != "" {
		if _, err := strconv.Atoi(at); err == nil {
			return aj + "_" + at
		}
	}
	return f["JobId"]
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
// requeue statistics from journal jobs. An empty username returns every job. A
// non-zero cutoff drops jobs whose most recent parseable timestamp (end, else
// start, else submit) lies before it.
func HistoryJobsFor(jobs []ControllerJob, username string, cutoff time.Time) ([]HistoryJob, HistoryStats) {
	var out []HistoryJob
	stats := HistoryStats{}
	for _, j := range jobs {
		if username != "" && j.User != username {
			continue
		}
		if !cutoff.IsZero() && jobBefore(j, cutoff) {
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

// jobBefore reports whether j's most recent parseable timestamp (end, else
// start, else submit) is before cutoff. A job with no parseable timestamp is
// never before: the history window must not hide a live or malformed record.
func jobBefore(j ControllerJob, cutoff time.Time) bool {
	for _, s := range []string{j.End, j.Start, j.Submit} {
		if t, ok := ParseSlurmTimestamp(s); ok {
			return t.Before(cutoff)
		}
	}
	return false
}
