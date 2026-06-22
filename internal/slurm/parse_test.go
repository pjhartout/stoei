package slurm

import (
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
	// The CfgTRES/AllocTRES lines embed "=" inside comma values; matching Python,
	// the named CfgTRES/AllocTRES keys are NOT captured and only the final
	// gres/gpu:h200 token survives. Assert the documented quirk explicitly.
	if got := n.Fields["gres/gpu:h200"]; got != "6" {
		t.Errorf("gres/gpu:h200 = %q, want 6", got)
	}
	if _, ok := n.Fields["CfgTRES"]; ok {
		t.Errorf("CfgTRES unexpectedly captured: %q", n.Fields["CfgTRES"])
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
}

func TestParseHistory(t *testing.T) {
	jobs, stats := ParseHistory(readFixture(t, "sacct_history.txt"))
	if stats.TotalJobs != 10 || len(jobs) != 10 {
		t.Fatalf("TotalJobs = %d / len = %d, want 10", stats.TotalJobs, len(jobs))
	}
	// Requeues: 0+2+0+3+0+0+1+0+0+5 = 11, max 5.
	if stats.TotalRequeues != 11 {
		t.Errorf("TotalRequeues = %d, want 11", stats.TotalRequeues)
	}
	if stats.MaxRequeues != 5 {
		t.Errorf("MaxRequeues = %d, want 5", stats.MaxRequeues)
	}
	// Sorted by numeric base job ID descending.
	prev := historySortKey(jobs[0].ID)
	for _, j := range jobs[1:] {
		k := historySortKey(j.ID)
		if k > prev {
			t.Errorf("history not sorted descending: %d after %d", k, prev)
		}
		prev = k
	}
}

func TestParseHistoryEdgeCases(t *testing.T) {
	if jobs, stats := ParseHistory(""); jobs != nil || stats != (HistoryStats{}) {
		t.Errorf("empty = %v / %+v, want nil / zero", jobs, stats)
	}
	header := "JobID|JobName|State|Restart|Elapsed|ExitCode|NodeList|Submit|Start|End"
	if jobs, _ := ParseHistory(header); jobs != nil {
		t.Errorf("header-only = %v, want nil", jobs)
	}
	// A non-numeric restart count is ignored without crashing.
	in := header + "\n12345|t|RUNNING|invalid|01:00:00|0:0|n01|2024-01-15T10:00:00|2024-01-15T10:01:00|Unknown"
	jobs, stats := ParseHistory(in)
	if len(jobs) != 1 || stats.TotalRequeues != 0 || stats.MaxRequeues != 0 {
		t.Errorf("invalid restart not handled: jobs=%d stats=%+v", len(jobs), stats)
	}
	// A non-numeric job ID sorts as zero rather than crashing.
	in2 := header +
		"\nabc123|t1|RUNNING|0|01:00:00|0:0|n01|2024-01-15T10:00:00|2024-01-15T10:01:00|Unknown" +
		"\n12345|t2|RUNNING|0|01:00:00|0:0|n02|2024-01-15T10:00:00|2024-01-15T10:01:00|Unknown"
	if jobs, _ := ParseHistory(in2); len(jobs) != 2 {
		t.Errorf("non-numeric job ID: got %d jobs, want 2", len(jobs))
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

func TestParseUserJobs(t *testing.T) {
	jobs := ParseUserJobs(readFixture(t, "squeue_user.txt"))
	if len(jobs) != 4 {
		t.Fatalf("got %d jobs, want 4", len(jobs))
	}
	if jobs[0].ID != "12345" || jobs[0].Partition != "gpu" || jobs[0].State != "RUNNING" {
		t.Errorf("job[0] = %+v", jobs[0])
	}
	if jobs[2].State != "PENDING" || jobs[2].NodeList != "(Priority)" {
		t.Errorf("job[2] = %+v", jobs[2])
	}
}

func TestParseJobDetail(t *testing.T) {
	tests := []struct {
		name   string
		raw    string
		fields []string
		want   map[string]string
	}{
		{
			name:   "basic",
			raw:    "12345|test_job|COMPLETED|0:0",
			fields: []string{"JobID", "JobName", "State", "ExitCode"},
			want:   map[string]string{"JobID": "12345", "JobName": "test_job", "State": "COMPLETED", "ExitCode": "0:0"},
		},
		{
			name:   "empty",
			raw:    "",
			fields: []string{"JobID"},
			want:   map[string]string{},
		},
		{
			name:   "skips dot substeps",
			raw:    "12345.batch|main|COMPLETED\n12345|main|COMPLETED",
			fields: []string{"JobID", "JobName", "State"},
			want:   map[string]string{"JobID": "12345", "JobName": "main", "State": "COMPLETED"},
		},
		{
			name:   "skips numeric substeps",
			raw:    "12345.0|step|COMPLETED\n12345|main|COMPLETED",
			fields: []string{"JobID", "JobName", "State"},
			want:   map[string]string{"JobID": "12345", "JobName": "main", "State": "COMPLETED"},
		},
		{
			name:   "fallback first line",
			raw:    "12345.batch|batch|COMPLETED",
			fields: []string{"JobID", "JobName", "State"},
			want:   map[string]string{"JobID": "12345.batch", "JobName": "batch", "State": "COMPLETED"},
		},
		{
			name:   "empty values dropped",
			raw:    "12345|test||0:0",
			fields: []string{"JobID", "JobName", "State", "ExitCode"},
			want:   map[string]string{"JobID": "12345", "JobName": "test", "ExitCode": "0:0"},
		},
		{
			name:   "fewer values than fields",
			raw:    "12345|test|COMPLETED",
			fields: []string{"JobID", "JobName", "State", "ExitCode", "NodeList"},
			want:   map[string]string{"JobID": "12345", "JobName": "test", "State": "COMPLETED"},
		},
		{
			name:   "picks main among many substeps",
			raw:    "12345.extern|t|COMPLETED|00:01:00\n12345.0|t|COMPLETED|00:30:00\n12345|t|COMPLETED|00:31:00\n12345.batch|t|COMPLETED|00:30:00",
			fields: []string{"JobID", "JobName", "State", "Elapsed"},
			want:   map[string]string{"JobID": "12345", "JobName": "t", "State": "COMPLETED", "Elapsed": "00:31:00"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := ParseJobDetail(tt.raw, tt.fields)
			if len(got) != len(tt.want) {
				t.Fatalf("got %v, want %v", got, tt.want)
			}
			for k, v := range tt.want {
				if got[k] != v {
					t.Errorf("field %s = %q, want %q", k, got[k], v)
				}
			}
		})
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

func TestParseEnergyRecords(t *testing.T) {
	records := ParseEnergyRecords(readFixture(t, "sacct_energy.txt"))
	// The energy fixture has 17 COMPLETED rows; all are valid states.
	if len(records) != 17 {
		t.Fatalf("got %d records, want 17", len(records))
	}
	if records[0].JobID != "50001" || records[0].User != "user1" {
		t.Errorf("record[0] = %+v", records[0])
	}
	if got := ParseTRESResources(records[0].AllocTRES); got.CPUs != 64 || CalculateTotalGPUs(got.GPUs, true) != 32 {
		t.Errorf("record[0] TRES parse = %+v", got)
	}
}

func TestParseEnergyRecordsStateFilter(t *testing.T) {
	// RUNNING/PENDING are excluded; "CANCELLED by 123" matches CANCELLED by base.
	in := "1|u|1:00:00|8|cpu=8|RUNNING\n" +
		"2|u|1:00:00|8|cpu=8|COMPLETED\n" +
		"3|u|1:00:00|8|cpu=8|CANCELLED by 12345\n" +
		"4|u|1:00:00|8|cpu=8|PENDING"
	records := ParseEnergyRecords(in)
	if len(records) != 2 {
		t.Fatalf("got %d records, want 2 (COMPLETED + CANCELLED)", len(records))
	}
	if records[0].JobID != "2" || records[1].JobID != "3" {
		t.Errorf("kept wrong records: %+v", records)
	}
}

func TestParseWaitTimeRecords(t *testing.T) {
	records := ParseWaitTimeRecords(readFixture(t, "sacct_wait_time.txt"))
	// The fixture has 8 rows; one is PENDING with Unknown start and is dropped.
	if len(records) != 7 {
		t.Fatalf("got %d records, want 7 (pending dropped)", len(records))
	}
	for _, r := range records {
		if isUnknownTimestamp(r.Start) {
			t.Errorf("record with unknown start was not dropped: %+v", r)
		}
	}
	// A kept record yields a sensible wait time.
	if secs, ok := WaitTimeSeconds(records[0].Submit, records[0].Start); !ok || secs != 300 {
		t.Errorf("record[0] wait = %v (ok=%v), want 300", secs, ok)
	}
}

func TestParseWaitTimeRecordsDropsPending(t *testing.T) {
	in := "1|gpu|RUNNING|2024-01-15T10:00:00|2024-01-15T10:05:00\n" +
		"2|gpu|PENDING|2024-01-15T10:50:00|Unknown\n" +
		"3|gpu|PENDING|2024-01-15T10:50:00|\n" +
		"4|gpu|RUNNING|2024-01-15T10:00:00|None"
	records := ParseWaitTimeRecords(in)
	if len(records) != 1 || records[0].JobID != "1" {
		t.Errorf("got %+v, want only job 1", records)
	}
}
