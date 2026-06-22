package slurm

import (
	"context"
	"errors"
	"os"
	"strings"
	"testing"
	"time"
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

func TestClientJobHistoryCommand(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"sacct": loadFixture(t, "sacct_history.txt")}}
	c := NewClient(r, WithUsername("alice"))

	jobs, stats, err := c.JobHistory(context.Background(), 7)
	if err != nil {
		t.Fatal(err)
	}
	if len(jobs) != 10 || stats.TotalRequeues != 11 || stats.MaxRequeues != 5 {
		t.Errorf("history = %d jobs, stats %+v", len(jobs), stats)
	}
	call := lastCall(r)
	wantFmt := "--format=JobID,JobName,State,Restart,Elapsed,ExitCode,NodeList,Submit,Start,End"
	if !argsContain(call, wantFmt) || !argsContain(call, "now-7days") || !argsContain(call, "-X") || !argsContain(call, "-P") {
		t.Errorf("sacct history command mismatch: %v", call.Args)
	}
}

func TestClientEnergyHistoryCommand(t *testing.T) {
	fixed := time.Date(2025, 6, 22, 12, 0, 0, 0, time.UTC)
	r := &fixtureRunner{outputs: map[string]string{"sacct": loadFixture(t, "sacct_energy.txt")}}
	c := NewClient(r, WithUsername("alice"), WithClock(func() time.Time { return fixed }))

	records, err := c.EnergyHistory(context.Background(), 6)
	if err != nil {
		t.Fatal(err)
	}
	if len(records) != 17 {
		t.Errorf("got %d records, want 17", len(records))
	}
	call := lastCall(r)
	if !argsContain(call, "--allusers") || !argsContain(call, "--format=JobID,User,Elapsed,NCPUS,AllocTRES,State") {
		t.Errorf("energy command mismatch: %v", call.Args)
	}
	// Start date is now - months*30 days, formatted YYYY-MM-DD.
	want := fixed.AddDate(0, 0, -6*30).Format("2006-01-02")
	if !argsContain(call, want) {
		t.Errorf("energy start date = %v, want %s", call.Args, want)
	}
}

func TestClientWaitTimeHistoryCommand(t *testing.T) {
	r := &fixtureRunner{outputs: map[string]string{"sacct": loadFixture(t, "sacct_wait_time.txt")}}
	c := NewClient(r, WithUsername("alice"))

	records, err := c.WaitTimeHistory(context.Background(), 1)
	if err != nil {
		t.Fatal(err)
	}
	if len(records) != 7 {
		t.Errorf("got %d records, want 7", len(records))
	}
	call := lastCall(r)
	if !argsContain(call, "--format=JobID,Partition,State,Submit,Start") || !argsContain(call, "now-1hours") {
		t.Errorf("wait-time command mismatch: %v", call.Args)
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

// programmableRunner returns a queued error/success per command name so the
// cooldown state machine can be driven deterministically without a real sacct.
type programmableRunner struct {
	// behavior[name] is consumed front-to-back; the last entry repeats.
	behavior map[string][]result
	calls    map[string]int
}

type result struct {
	out []byte
	err error
}

func (r *programmableRunner) Run(_ context.Context, name string, _ ...string) ([]byte, error) {
	if r.calls == nil {
		r.calls = map[string]int{}
	}
	seq := r.behavior[name]
	i := r.calls[name]
	r.calls[name]++
	if i >= len(seq) {
		i = len(seq) - 1
	}
	return seq[i].out, seq[i].err
}

// TestSacctCooldownSuppressesBatchCalls drives the 5-minute cooldown with an
// injected clock (no sleeping). A hard "connection refused" failure suppresses
// subsequent batch sacct calls until the cooldown elapses, then a successful call
// clears the failure state. This ports the commands.py cooldown logic.
func TestSacctCooldownSuppressesBatchCalls(t *testing.T) {
	now := time.Date(2025, 6, 22, 12, 0, 0, 0, time.UTC)
	clock := func() time.Time { return now }

	r := &programmableRunner{behavior: map[string][]result{
		"sacct": {
			{err: errors.New("sacct failed: connection refused")}, // first call: hard failure
			{out: []byte("JobID|JobName|State|Restart|Elapsed|ExitCode|NodeList|Submit|Start|End\n" +
				"1|t|COMPLETED|0|1:00:00|0:0|n01|2024-01-15T10:00:00|2024-01-15T10:01:00|2024-01-15T11:01:00")},
		},
	}}
	c := NewClient(r, WithUsername("alice"), WithClock(func() time.Time { return clock() }))
	ctx := context.Background()

	// 1. First call fails with connection refused and trips the cooldown.
	if _, _, err := c.JobHistory(ctx, 7); err == nil || !isConnectionRefused(err) {
		t.Fatalf("first call err = %v, want connection refused", err)
	}
	callsAfterFail := r.calls["sacct"]
	if callsAfterFail != 1 {
		t.Fatalf("sacct called %d times, want 1", callsAfterFail)
	}

	// 2. While in cooldown, batch calls are suppressed entirely (no new sacct).
	_, _, err := c.JobHistory(ctx, 7)
	if !ErrSacctCooldown(err) {
		t.Fatalf("during cooldown err = %v, want ErrSacctCooldown", err)
	}
	if _, e := c.EnergyHistory(ctx, 6); !ErrSacctCooldown(e) {
		t.Fatalf("energy during cooldown err = %v, want ErrSacctCooldown", e)
	}
	if _, e := c.WaitTimeHistory(ctx, 1); !ErrSacctCooldown(e) {
		t.Fatalf("wait during cooldown err = %v, want ErrSacctCooldown", e)
	}
	if r.calls["sacct"] != callsAfterFail {
		t.Errorf("sacct was invoked during cooldown: %d calls", r.calls["sacct"])
	}

	// 3. Just before the cooldown elapses, still suppressed.
	now = now.Add(5*time.Minute - time.Second)
	if _, _, e := c.JobHistory(ctx, 7); !ErrSacctCooldown(e) {
		t.Fatalf("just before cooldown end err = %v, want ErrSacctCooldown", e)
	}

	// 4. After the cooldown elapses, the call proceeds and succeeds, clearing state.
	now = now.Add(time.Second)
	jobs, _, err := c.JobHistory(ctx, 7)
	if err != nil {
		t.Fatalf("post-cooldown call err = %v, want success", err)
	}
	if len(jobs) != 1 {
		t.Errorf("post-cooldown jobs = %d, want 1", len(jobs))
	}

	// 5. A subsequent call proceeds immediately (state was cleared by success).
	if _, _, err := c.JobHistory(ctx, 7); err != nil {
		t.Errorf("after recovery err = %v, want success", err)
	}
}

// TestSacctTransientErrorDoesNotTripCooldown verifies that a non-"connection
// refused" failure does not suppress later batch calls.
func TestSacctTransientErrorDoesNotTripCooldown(t *testing.T) {
	r := &programmableRunner{behavior: map[string][]result{
		"sacct": {
			{err: errors.New("sacct: some transient glitch")},
			{out: []byte("JobID|JobName|State|Restart|Elapsed|ExitCode|NodeList|Submit|Start|End\n" +
				"1|t|COMPLETED|0|1:00:00|0:0|n01|2024-01-15T10:00:00|2024-01-15T10:01:00|2024-01-15T11:01:00")},
		},
	}}
	c := NewClient(r, WithUsername("alice"))
	ctx := context.Background()

	if _, _, err := c.JobHistory(ctx, 7); err == nil {
		t.Fatal("expected transient error")
	}
	// The next call must NOT be suppressed by a cooldown.
	if _, _, err := c.JobHistory(ctx, 7); err != nil {
		t.Errorf("transient error tripped cooldown: %v", err)
	}
}

// TestJobDetailSacctFallbackBypassesCooldown verifies that on-demand single-job
// sacct lookups run even while the batch cooldown is active (Python commit
// c7a240f).
func TestJobDetailSacctFallbackBypassesCooldown(t *testing.T) {
	sacctOut := "12345|test_job|alice|acct|gpu|COMPLETED|0:0|2024-01-15T10:00:00|" +
		"2024-01-15T11:00:00|1:00:00|60|1|8|1|64G|||n01|/home/x|/home/x/o|/home/x/e|" +
		"2024-01-15T09:00:00|1000|normal"
	r := &programmableRunner{behavior: map[string][]result{
		// scontrol fails so the detail path falls through to sacct.
		"scontrol": {{err: errors.New("scontrol: Invalid job id")}},
		"sacct":    {{out: []byte(sacctOut)}},
	}}
	c := NewClient(r, WithUsername("alice"))
	ctx := context.Background()

	// Force the batch cooldown active.
	c.sacctMarkFailure()
	if c.sacctAvailable() {
		t.Fatal("expected cooldown to be active")
	}

	detail, err := c.JobDetail(ctx, "12345")
	if err != nil {
		t.Fatalf("job detail during cooldown err = %v, want it to bypass cooldown", err)
	}
	if detail.Source != "sacct" {
		t.Errorf("Source = %q, want sacct", detail.Source)
	}
	if detail.Fields["JobID"] != "12345" || detail.Fields["State"] != "COMPLETED" {
		t.Errorf("detail = %+v", detail.Fields)
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
