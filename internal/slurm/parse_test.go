package slurm

import (
	"fmt"
	"os"
	"testing"
)

// readFixture reads a golden fixture from testdata, failing the test on error.
func readFixture(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile("testdata/" + name)
	if err != nil {
		t.Fatalf("read fixture %s: %v", name, err)
	}
	return string(b)
}

func TestParseScontrolFields(t *testing.T) {
	fields := ParseScontrolFields(readFixture(t, "scontrol_job_12345.txt"))

	if fields["JobId"] != "12345" {
		t.Errorf("JobId = %q, want 12345", fields["JobId"])
	}
	if fields["JobState"] != "RUNNING" {
		t.Errorf("JobState = %q, want RUNNING", fields["JobState"])
	}
	// A value that itself contains "=" is preserved (non-space run).
	if got := fields["TRES"]; got != "cpu=32,mem=256G,node=4,gres/gpu=16" {
		t.Errorf("TRES = %q, want the full TRES string", got)
	}
	// A key containing ":" captures only its final \w+ segment, matching Python.
	if got, ok := fields["T"]; !ok || got != "0:0:*:*" {
		t.Errorf("ReqB:S:C:T parsed as T=%q (ok=%v), want 0:0:*:*", got, ok)
	}
	// An empty value before another key stays empty.
	if got, ok := fields["Power"]; !ok || got != "" {
		t.Errorf("Power = %q (ok=%v), want empty", got, ok)
	}
	if fields["StdOut"] != "/home/testuser/projects/ml/logs/train_%j.out" {
		t.Errorf("StdOut = %q", fields["StdOut"])
	}
}

func TestParseScontrolFieldsEmpty(t *testing.T) {
	if got := ParseScontrolFields(""); len(got) != 0 {
		t.Errorf("ParseScontrolFields(empty) = %v, want empty", got)
	}
}

// TestParseScontrolJobRecords verifies multi-record array output is split into
// per-task maps instead of flattened into one (where the last record's
// JobState would clobber the rest).
func TestParseScontrolJobRecords(t *testing.T) {
	records := ParseScontrolJobRecords(readFixture(t, "scontrol_job_array.txt"))
	if len(records) != 3 {
		t.Fatalf("got %d records, want 3", len(records))
	}
	wantStates := []string{"PENDING", "RUNNING", "COMPLETED"}
	for i, want := range wantStates {
		if got := records[i]["JobState"]; got != want {
			t.Errorf("record %d JobState = %q, want %q", i, got, want)
		}
	}
	if records[0]["ArrayTaskId"] != "50-99%10" || records[1]["ArrayTaskId"] != "48" {
		t.Errorf("ArrayTaskId split wrong: %q, %q", records[0]["ArrayTaskId"], records[1]["ArrayTaskId"])
	}
}

func TestParseScontrolJobRecordsSingleJob(t *testing.T) {
	records := ParseScontrolJobRecords(readFixture(t, "scontrol_job_12345.txt"))
	if len(records) != 1 {
		t.Fatalf("got %d records, want 1", len(records))
	}
	if records[0]["JobId"] != "12345" || records[0]["JobState"] != "RUNNING" {
		t.Errorf("record = %+v", records[0])
	}
}

func TestParseNodes(t *testing.T) {
	nodes := ParseNodes(readFixture(t, "scontrol_nodes.txt"))
	if len(nodes) != 6 {
		t.Fatalf("got %d nodes, want 6", len(nodes))
	}
	n := nodes[0]
	if n.Name != "gpu-node-01" {
		t.Errorf("Name = %q, want gpu-node-01", n.Name)
	}
	if n.State != "MIXED+PLANNED" {
		t.Errorf("State = %q, want MIXED+PLANNED", n.State)
	}
	if n.CPUAlloc != "144" || n.CPUTot != "192" {
		t.Errorf("CPUAlloc/CPUTot = %q/%q, want 144/192", n.CPUAlloc, n.CPUTot)
	}
	if n.AllocMem != "650000" || n.RealMem != "2000000" {
		t.Errorf("AllocMem/RealMem = %q/%q", n.AllocMem, n.RealMem)
	}
	if n.Gres != "gpu:h200:8(S:0-1)" {
		t.Errorf("Gres = %q", n.Gres)
	}
	// The CfgTRES/AllocTRES values embed "=" inside their comma-separated TRES;
	// they must still be captured whole so the store can read real allocated GPU
	// counts instead of estimating from node state.
	if n.CfgTRES != "cpu=192,mem=2000000M,billing=192,gres/gpu=8,gres/gpu:h200=8" {
		t.Errorf("CfgTRES = %q", n.CfgTRES)
	}
	if n.AllocTRES != "cpu=144,mem=650000M,gres/gpu=6,gres/gpu:h200=6" {
		t.Errorf("AllocTRES = %q", n.AllocTRES)
	}
}

// TestParseNodesBlankLineReason covers Python commit 2ff0fd5: SLURM can emit a
// blank line inside one node's block (here before Reason), and the multi-line
// Reason must attach to that node rather than starting a new record.
func TestParseNodesBlankLineReason(t *testing.T) {
	nodes := ParseNodes(readFixture(t, "scontrol_nodes_blank_reason.txt"))
	if len(nodes) != 2 {
		t.Fatalf("got %d nodes, want 2 (blank line must not split a node)", len(nodes))
	}
	if nodes[0].Name != "hpcl8010" {
		t.Errorf("node[0].Name = %q, want hpcl8010", nodes[0].Name)
	}
	if nodes[0].State != "IDLE+DRAIN" {
		t.Errorf("node[0].State = %q, want IDLE+DRAIN", nodes[0].State)
	}
	// Reason appears after the blank line but belongs to node[0].
	if got := nodes[0].Reason; got == "" || got[:6] != "bbusch" {
		t.Errorf("node[0].Reason = %q, want it to start with bbusch", got)
	}
	if nodes[1].Name != "node02" || nodes[1].CPUAlloc != "8" {
		t.Errorf("node[1] = %+v, want node02 with CPUAlloc=8", nodes[1])
	}
}

func TestParseNodesEmpty(t *testing.T) {
	for _, in := range []string{"", "   \n\n   "} {
		if got := ParseNodes(in); len(got) != 0 {
			t.Errorf("ParseNodes(%q) = %v, want empty", in, got)
		}
	}
}

func TestParseRunningJobs(t *testing.T) {
	jobs := ParseRunningJobs(readFixture(t, "squeue_running.txt"))
	if len(jobs) != 3 {
		t.Fatalf("got %d jobs, want 3 (header skipped)", len(jobs))
	}
	if jobs[0].ID != "12345" || jobs[0].State != "RUNNING" || jobs[0].NodeList != "gpu-node-[01-04]" {
		t.Errorf("job[0] = %+v", jobs[0])
	}
	if jobs[2].State != "PENDING" || jobs[2].StartTime != "Unknown" {
		t.Errorf("job[2] = %+v, want pending with Unknown start", jobs[2])
	}
}

// TestParseRunningJobsTrimsFixedWidthPadding asserts the squeue -o fixed-width
// padding (%.30i, %.50j, …) is stripped from each field, so values are the bare
// content. Untrimmed, the padding hides short values (truncated to a default
// column width they are all spaces) and inflates the rendered column widths. The
// golden fixture is hand-written without padding, so this covers the real format.
func TestParseRunningJobsTrimsFixedWidthPadding(t *testing.T) {
	raw := "JOBID|JOBNAME|STATE|TIME|NODES|NODELIST|SUBMIT|START\n" +
		fmt.Sprintf("%30s|%50s|%8s|%10s|%4s|%12s|%19s|%19s",
			"5098105", "train", "RUNNING", "1:23:00", "2", "node[01-02]", "2024-01-15T10:00", "2024-01-15T10:05")
	jobs := ParseRunningJobs(raw)
	if len(jobs) != 1 {
		t.Fatalf("got %d jobs, want 1", len(jobs))
	}
	j := jobs[0]
	if j.ID != "5098105" || j.Name != "train" || j.State != "RUNNING" || j.Nodes != "2" || j.NodeList != "node[01-02]" {
		t.Errorf("fixed-width padding not trimmed: %+v", j)
	}
}

func TestParseRunningJobsEdgeCases(t *testing.T) {
	if got := ParseRunningJobs(""); got != nil {
		t.Errorf("empty input = %v, want nil", got)
	}
	header := "JOBID|JOBNAME|STATE|TIME|NODES|NODELIST|SUBMIT_TIME|START_TIME"
	if got := ParseRunningJobs(header); got != nil {
		t.Errorf("header-only = %v, want nil", got)
	}
	// A short (<8 field) row is dropped even when other rows are valid.
	in := header + "\nbad|row\n101|t|RUNNING|1:00|1|n01|2024-01-15T10:00:00|2024-01-15T10:01:00"
	if got := ParseRunningJobs(in); len(got) != 1 {
		t.Errorf("got %d jobs, want 1 (short row dropped)", len(got))
	}
	// A job name containing the delimiter (sbatch -J 'train|eval|v2') must not
	// shift the fixed fields behind it.
	in = header + "\n102|train|eval|v2|RUNNING|2:00|1|n02|2024-01-15T10:00:00|2024-01-15T10:01:00"
	got := ParseRunningJobs(in)
	if len(got) != 1 {
		t.Fatalf("got %d jobs, want 1", len(got))
	}
	if got[0].Name != "train|eval|v2" || got[0].State != "RUNNING" || got[0].StartTime != "2024-01-15T10:01:00" {
		t.Errorf("pipe-in-name row parsed as %+v", got[0])
	}
}

func TestParseAllUsersJobs(t *testing.T) {
	jobs := ParseAllUsersJobs(readFixture(t, "squeue_all_users.txt"))
	if len(jobs) != 10 {
		t.Fatalf("got %d jobs, want 10", len(jobs))
	}
	if jobs[0].ID != "47441" || jobs[0].User != "user1" || jobs[0].State != "PENDING" {
		t.Errorf("job[0] = %+v", jobs[0])
	}
	if jobs[0].NodeList != "(Priority)" || jobs[0].TRES != "cpu=64,mem=512G,node=8,gres/gpu=32" {
		t.Errorf("job[0] nodelist/tres = %q / %q", jobs[0].NodeList, jobs[0].TRES)
	}
	// A pending array row with throttle notation survives fixed-width parsing.
	var throttled *AllUsersJob
	for i := range jobs {
		if jobs[i].ID == "47701_[0-99%10]" {
			throttled = &jobs[i]
		}
	}
	if throttled == nil {
		t.Fatal("throttled array job 47701_[0-99%10] not found")
	}
	if ParseArraySize(throttled.ID) != 100 {
		t.Errorf("array size of %q = %d, want 100", throttled.ID, ParseArraySize(throttled.ID))
	}
	if got := ParseTRESResources(throttled.TRES); got.CPUs != 4 || CalculateTotalGPUs(got.GPUs, true) != 2 {
		t.Errorf("throttled TRES parse = %+v", got)
	}
	// A multi-node running job's NodeList still expands.
	for _, j := range jobs {
		if j.ID == "46043" {
			if got := len(ExpandNodeList(j.NodeList)); got != 4 {
				t.Errorf("46043 node count = %d, want 4", got)
			}
		}
	}
}

func TestParseAllUsersJobsEdgeCases(t *testing.T) {
	if got := ParseAllUsersJobs(""); got != nil {
		t.Errorf("empty = %v, want nil", got)
	}
	// A line shorter than the JobID column is skipped.
	if got := ParseAllUsersJobs("short"); got != nil {
		t.Errorf("short line = %v, want nil", got)
	}
}

func TestParseFairShare(t *testing.T) {
	entries := ParseFairShare(readFixture(t, "sshare.txt"))
	if len(entries) != 13 {
		t.Fatalf("got %d entries, want 13", len(entries))
	}
	var accounts, users int
	for _, e := range entries {
		if e.IsAccount() {
			accounts++
		} else {
			users++
		}
	}
	// 5 account-level (root + 4) and 8 user-level entries.
	if accounts != 5 || users != 8 {
		t.Errorf("accounts/users = %d/%d, want 5/8", accounts, users)
	}
	// The trailing "|" from sshare's parsable mode must not corrupt the 8 columns.
	if entries[0].Account != "root" || entries[0].FairShare != "1.000000" {
		t.Errorf("entry[0] = %+v", entries[0])
	}
}

func TestParsePriority(t *testing.T) {
	entries := ParsePriority(readFixture(t, "sprio.txt"))
	if len(entries) != 7 {
		t.Fatalf("got %d entries, want 7", len(entries))
	}
	// Sorted by numeric Priority descending: first is the 1500 entry.
	if entries[0].Priority != "1500" || entries[0].JobID != "47441" {
		t.Errorf("entry[0] = %+v, want highest priority first", entries[0])
	}
	prev := priorityValue(entries[0].Priority)
	for _, e := range entries[1:] {
		v := priorityValue(e.Priority)
		if v > prev {
			t.Errorf("priority not descending: %v after %v", v, prev)
		}
		prev = v
	}
}
