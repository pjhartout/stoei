package slurm

import "testing"

func TestParseJobs(t *testing.T) {
	out := "101|train|RUNNING|10:00|1|node001\n102|eval|PENDING|0:00|2|(Priority)\n"
	jobs := parseJobs(out)
	if len(jobs) != 2 {
		t.Fatalf("want 2 jobs, got %d", len(jobs))
	}
	if jobs[0].ID != "101" || jobs[0].State != "RUNNING" || jobs[0].NodeList != "node001" {
		t.Errorf("bad first job: %+v", jobs[0])
	}
	if jobs[1].NodeList != "(Priority)" {
		t.Errorf("bad nodelist: %q", jobs[1].NodeList)
	}
}

func TestParseJobsSkipsJunk(t *testing.T) {
	// blank lines and a too-short line are dropped.
	out := "\n101|train|RUNNING|10:00|1|node001\nbad|line\n\n"
	if got := len(parseJobs(out)); got != 1 {
		t.Fatalf("want 1 job, got %d", got)
	}
}
