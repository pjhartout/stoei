// Package slurm runs Slurm commands and parses their output.
package slurm

import (
	"os/exec"
	"os/user"
	"strings"
)

// Job is a single row from squeue.
type Job struct {
	ID       string
	Name     string
	State    string
	Time     string
	Nodes    string
	NodeList string
}

// squeueFormat is a pipe-delimited squeue -o format: id|name|state|time|nodes|nodelist.
const squeueFormat = "%i|%j|%T|%M|%D|%R"

// RunningJobs returns the current user's jobs via squeue.
func RunningJobs() ([]Job, error) {
	u, err := user.Current()
	if err != nil {
		return nil, err
	}
	out, err := exec.Command("squeue", "-u", u.Username, "-h", "-o", squeueFormat).Output()
	if err != nil {
		return nil, err
	}
	return parseJobs(string(out)), nil
}

// parseJobs parses pipe-delimited squeue output into Jobs. Short/blank lines are skipped.
func parseJobs(out string) []Job {
	var jobs []Job
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if line == "" {
			continue
		}
		f := strings.Split(line, "|")
		if len(f) < 6 {
			continue
		}
		jobs = append(jobs, Job{
			ID: f[0], Name: f[1], State: f[2],
			Time: f[3], Nodes: f[4], NodeList: f[5],
		})
	}
	return jobs
}
