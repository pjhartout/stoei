package slurm

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// fixtureRunner is a Runner that returns the contents of a testdata fixture per
// command name and records the exact args of every call so tests can assert on
// the command line built by the Client.
type fixtureRunner struct {
	outputs map[string]string
	calls   []FakeCall
}

func (r *fixtureRunner) Run(_ context.Context, name string, args ...string) ([]byte, error) {
	r.calls = append(r.calls, FakeCall{Name: name, Args: args})
	out, ok := r.outputs[name]
	if !ok {
		return nil, errors.New("no fixture for " + name)
	}
	return []byte(out), nil
}

func loadFixture(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile("testdata/" + name)
	if err != nil {
		t.Fatalf("read %s: %v", name, err)
	}
	return string(b)
}

// argsContain reports whether the call's args include the exact value v.
func argsContain(c FakeCall, v string) bool {
	for _, a := range c.Args {
		if a == v {
			return true
		}
	}
	return false
}

func lastCall(r *fixtureRunner) FakeCall { return r.calls[len(r.calls)-1] }

func TestClientRunningJobsCommand(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"squeue": loadFixture(t, "squeue_running.txt")}}
	c := NewClient(r, WithUsername("alice"))

	jobs, err := c.RunningJobs(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(jobs) != 3 {
		t.Errorf("got %d jobs, want 3", len(jobs))
	}
	call := lastCall(r)
	// Exact flags and format string must match get_running_jobs in commands.py.
	if !argsContain(call, "-u") || !argsContain(call, "alice") {
		t.Errorf("squeue args missing -u alice: %v", call.Args)
	}
	if !argsContain(call, "%.30i|%.50j|%.8T|%.10M|%.4D|%.12R|%.19V|%.19S") {
		t.Errorf("squeue format string mismatch: %v", call.Args)
	}
}

func TestClientAllUsersJobsCommand(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"squeue": loadFixture(t, "squeue_all_users.txt")}}
	c := NewClient(r, WithUsername("alice"))

	jobs, err := c.AllUsersJobs(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(jobs) != 10 {
		t.Errorf("got %d jobs, want 10", len(jobs))
	}
	call := lastCall(r)
	wantFmt := "JobID:30,Name:50,UserName:15,Partition:15,StateCompact:10,TimeUsed:12,NumNodes:6,NodeList:80,tres:80"
	if !argsContain(call, wantFmt) {
		t.Errorf("squeue -O format mismatch: %v", call.Args)
	}
	if !argsContain(call, "-a") || !argsContain(call, "RUNNING,PENDING") || !argsContain(call, "--noheader") {
		t.Errorf("squeue all-users flags mismatch: %v", call.Args)
	}
}

func TestClientUserJobsCommand(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"squeue": loadFixture(t, "squeue_user.txt")}}
	c := NewClient(r, WithUsername("alice"))

	jobs, err := c.UserJobs(context.Background(), "bob")
	if err != nil {
		t.Fatal(err)
	}
	if len(jobs) != 4 {
		t.Errorf("got %d jobs, want 4", len(jobs))
	}
	call := lastCall(r)
	wantFmt := "JobID:30,Name:50,Partition:15,StateCompact:10,TimeUsed:12,NumNodes:6,NodeList:80,tres:80"
	if !argsContain(call, wantFmt) || !argsContain(call, "bob") {
		t.Errorf("user jobs command mismatch: %v", call.Args)
	}
}

func TestClientUserJobsRejectsBadUsername(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{}}
	c := NewClient(r, WithUsername("alice"))
	if _, err := c.UserJobs(context.Background(), "bad;rm -rf"); err == nil {
		t.Error("expected validation error for unsafe username")
	}
	if len(r.calls) != 0 {
		t.Errorf("runner was called despite invalid username: %v", r.calls)
	}
}

func TestClientJobHistoryFromJournal(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"scontrol": loadFixture(t, "scontrol_jobs.txt")}}
	c := NewClient(r, WithUsername("alice"), WithJournal(filepath.Join(t.TempDir(), "jobs.jsonl")))

	jobs, stats, err := c.JobHistory(context.Background(), 7)
	if err != nil {
		t.Fatal(err)
	}
	// alice owns 1001, 1002, 1004 (bob's 1003 is excluded). Requeues: 2+0+0.
	if len(jobs) != 3 || stats.TotalJobs != 3 || stats.TotalRequeues != 2 || stats.MaxRequeues != 2 {
		t.Errorf("history = %d jobs, stats %+v", len(jobs), stats)
	}
	call := lastCall(r)
	if call.Name != "scontrol" || !argsContain(call, "show") || !argsContain(call, "jobs") {
		t.Errorf("expected 'scontrol show jobs', got %s %v", call.Name, call.Args)
	}
}

func TestClientEnergyHistoryFromJournal(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"scontrol": loadFixture(t, "scontrol_jobs.txt")}}
	c := NewClient(r, WithJournal(filepath.Join(t.TempDir(), "jobs.jsonl")))

	records, err := c.EnergyHistory(context.Background(), 6)
	if err != nil {
		t.Fatal(err)
	}
	// Energy covers finished jobs across users: 1001 and 1003 (COMPLETED).
	if len(records) != 2 {
		t.Errorf("got %d records, want 2 (terminal jobs)", len(records))
	}
}

func TestClientWaitTimeHistoryFromJournal(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"scontrol": loadFixture(t, "scontrol_jobs.txt")}}
	c := NewClient(r, WithJournal(filepath.Join(t.TempDir(), "jobs.jsonl")))

	records, err := c.WaitTimeHistory(context.Background(), 1)
	if err != nil {
		t.Fatal(err)
	}
	// Wait-time covers jobs that started: 1001, 1002, 1003 (1004 is still pending).
	if len(records) != 3 {
		t.Errorf("got %d records, want 3 (started jobs)", len(records))
	}
}

func TestClientClusterNodesCommand(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"scontrol": loadFixture(t, "scontrol_nodes.txt")}}
	c := NewClient(r, WithUsername("alice"))

	nodes, err := c.ClusterNodes(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(nodes) != 6 {
		t.Errorf("got %d nodes, want 6", len(nodes))
	}
	call := lastCall(r)
	if call.Name != "scontrol" || !argsContain(call, "show") || !argsContain(call, "nodes") {
		t.Errorf("nodes command mismatch: %v %v", call.Name, call.Args)
	}
}

func TestClientFairShareCommand(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"sshare": loadFixture(t, "sshare.txt")}}
	c := NewClient(r, WithUsername("alice"))

	entries, err := c.FairShare(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 13 {
		t.Errorf("got %d entries, want 13", len(entries))
	}
	call := lastCall(r)
	wantFmt := "--format=Account,User,RawShares,NormShares,RawUsage,NormUsage,EffectvUsage,FairShare"
	if !argsContain(call, "-a") || !argsContain(call, "-P") || !argsContain(call, wantFmt) {
		t.Errorf("sshare command mismatch: %v", call.Args)
	}
}

func TestClientPendingPriorityCommand(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"sprio": loadFixture(t, "sprio.txt")}}
	c := NewClient(r, WithUsername("alice"))

	entries, err := c.PendingPriority(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 7 {
		t.Errorf("got %d entries, want 7", len(entries))
	}
	call := lastCall(r)
	if !argsContain(call, "%.15i|%.15u|%.15a|%.10Y|%.10A|%.10F|%.10J|%.10P|%.10Q") {
		t.Errorf("sprio format mismatch: %v", call.Args)
	}
}

func TestClientJobDetailScontrol(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"scontrol": loadFixture(t, "scontrol_job_12345.txt")}}
	c := NewClient(r, WithUsername("alice"))

	detail, err := c.JobDetail(context.Background(), "12345")
	if err != nil {
		t.Fatal(err)
	}
	if detail.Source != "scontrol" {
		t.Errorf("Source = %q, want scontrol", detail.Source)
	}
	if detail.Fields["JobId"] != "12345" || detail.Fields["JobState"] != "RUNNING" {
		t.Errorf("detail fields = %+v", detail.Fields)
	}
	call := lastCall(r)
	if !argsContain(call, "jobid") || !argsContain(call, "12345") {
		t.Errorf("job detail command mismatch: %v", call.Args)
	}
}

// TestClientJobDetailNormalizesArrayID verifies the array range is stripped
// before the job ID reaches scontrol, which cannot accept bracket notation.
func TestClientJobDetailNormalizesArrayID(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"scontrol": loadFixture(t, "scontrol_job_12345.txt")}}
	c := NewClient(r, WithUsername("alice"))

	if _, err := c.JobDetail(context.Background(), "12345_[0-99]"); err != nil {
		t.Fatal(err)
	}
	call := lastCall(r)
	if !argsContain(call, "12345") || argsContain(call, "12345_[0-99]") {
		t.Errorf("array ID not normalized before scontrol: %v", call.Args)
	}
}

// TestClientNodeDetail verifies NodeDetail runs "scontrol show node <name>" and
// parses the Key=Value fields.
func TestClientNodeDetail(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{
		"scontrol": "NodeName=node01 State=IDLE CPUTot=64 RealMemory=256000",
	}}
	c := NewClient(r, WithUsername("alice"))

	detail, err := c.NodeDetail(context.Background(), "node01")
	if err != nil {
		t.Fatal(err)
	}
	if detail.Source != "scontrol" {
		t.Errorf("Source = %q, want scontrol", detail.Source)
	}
	if detail.Fields["NodeName"] != "node01" || detail.Fields["State"] != "IDLE" {
		t.Errorf("node detail fields = %+v", detail.Fields)
	}
	call := lastCall(r)
	if !argsContain(call, "node") || !argsContain(call, "node01") {
		t.Errorf("node detail command mismatch: %v", call.Args)
	}
}

// TestClientNodeDetailRejectsBadName verifies an unsafe node name is rejected
// before reaching scontrol.
func TestClientNodeDetailRejectsBadName(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{}}
	c := NewClient(r, WithUsername("alice"))
	if _, err := c.NodeDetail(context.Background(), "bad name; rm -rf"); err == nil {
		t.Error("expected validation error for unsafe node name")
	}
	if len(r.calls) != 0 {
		t.Errorf("runner called despite invalid node name: %v", r.calls)
	}
}

func TestClientJobDetailRejectsBadID(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{}}
	c := NewClient(r, WithUsername("alice"))
	if _, err := c.JobDetail(context.Background(), "not-a-job"); err == nil {
		t.Error("expected validation error")
	}
	if len(r.calls) != 0 {
		t.Errorf("runner called despite invalid job ID: %v", r.calls)
	}
}

func TestClientCancelJob(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"scancel": ""}}
	c := NewClient(r, WithUsername("alice"))

	if err := c.CancelJob(context.Background(), "12345"); err != nil {
		t.Fatal(err)
	}
	call := lastCall(r)
	if call.Name != "scancel" || !argsContain(call, "12345") {
		t.Errorf("scancel command mismatch: %v %v", call.Name, call.Args)
	}
}

func TestClientCancelJobRejectsBadID(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{}}
	c := NewClient(r, WithUsername("alice"))
	if err := c.CancelJob(context.Background(), "bad id"); err == nil {
		t.Error("expected validation error")
	}
	if len(r.calls) != 0 {
		t.Errorf("scancel called despite invalid ID: %v", r.calls)
	}
}

// TestClientErrorsPropagate verifies a runner error surfaces from a getter.
func TestClientErrorsPropagate(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{}} // no fixture -> error
	c := NewClient(r, WithUsername("alice"))
	if _, err := c.AllUsersJobs(context.Background()); err == nil || !strings.Contains(err.Error(), "no fixture") {
		t.Errorf("err = %v, want runner error to propagate", err)
	}
}
