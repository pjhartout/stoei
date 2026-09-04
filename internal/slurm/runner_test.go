package slurm

import (
	"context"
	"errors"
	"os/exec"
	"strings"
	"testing"
	"time"
)

func TestFakeRunnerReturnsCannedOutput(t *testing.T) {
	fr := &FakeRunner{Outputs: map[string][]byte{"squeue": []byte("job1\n")}}

	out, err := fr.Run(context.Background(), "squeue", "-u", "alice")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(out) != "job1\n" {
		t.Fatalf("got %q, want %q", out, "job1\n")
	}

	if len(fr.Calls) != 1 {
		t.Fatalf("got %d calls, want 1", len(fr.Calls))
	}
	if fr.Calls[0].Name != "squeue" {
		t.Errorf("call name = %q, want squeue", fr.Calls[0].Name)
	}
	if got := fr.Calls[0].Args; len(got) != 2 || got[0] != "-u" || got[1] != "alice" {
		t.Errorf("call args = %v, want [-u alice]", got)
	}
}

func TestFakeRunnerReturnsCannedError(t *testing.T) {
	want := errors.New("connection refused")
	fr := &FakeRunner{Errs: map[string]error{"sacct": want}}

	if _, err := fr.Run(context.Background(), "sacct"); !errors.Is(err, want) {
		t.Fatalf("got %v, want %v", err, want)
	}
}

// TestExecRunnerConnectionRefusedOnExitZero is the slurmdbd-down case: sacct
// prints "connection refused" only to stderr yet exits 0 with empty stdout. The
// runner must surface this as a *CommandError so the cooldown can trip, instead
// of silently returning success. Run against a tiny shell command to avoid a real
// scheduler.
func TestExecRunnerConnectionRefusedOnExitZero(t *testing.T) {
	out, err := ExecRunner{}.Run(context.Background(),
		"sh", "-c", `echo "sacct: error: slurmdbd: Connection refused" 1>&2; exit 0`)
	if err == nil {
		t.Fatal("expected a CommandError, got nil")
	}
	if len(out) != 0 {
		t.Errorf("stdout = %q, want empty", out)
	}
	var ce *CommandError
	if !errors.As(err, &ce) {
		t.Fatalf("err = %T (%v), want *CommandError", err, err)
	}
	if ce.Err != nil {
		t.Errorf("CommandError.Err = %v, want nil (exit 0)", ce.Err)
	}
	if !hasHardFailureSignal(ce.Stderr) {
		t.Errorf("hasHardFailureSignal(%q) = false, want true", ce.Stderr)
	}
}

// TestExecRunnerNonZeroExitWrapsExitError verifies a non-zero exit yields a
// *CommandError that wraps the *exec.ExitError and carries the captured stderr.
func TestExecRunnerNonZeroExitWrapsExitError(t *testing.T) {
	_, err := ExecRunner{}.Run(context.Background(),
		"sh", "-c", `echo "boom" 1>&2; exit 3`)
	if err == nil {
		t.Fatal("expected a CommandError, got nil")
	}
	var ce *CommandError
	if !errors.As(err, &ce) {
		t.Fatalf("err = %T (%v), want *CommandError", err, err)
	}
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		t.Errorf("err does not unwrap to *exec.ExitError: %v", err)
	}
	if ce.Stderr != "boom" {
		t.Errorf("CommandError.Stderr = %q, want %q", ce.Stderr, "boom")
	}
}

// TestExecRunnerReturnsAfterContextCancelDespiteHeldPipe is the wedged-refresh
// case: the fetch timeout kills a hung scheduler command, but a process still
// holding the stdout pipe (a descendant, or the command itself stuck in D-state)
// would keep Run blocked past the cancel — the fetch message then never arrives
// and the section's dispatch guard never releases, freezing every later refresh.
// Run must return within the WaitDelay grace instead of blocking until the pipe
// closes on its own (here, a backgrounded sleep holding it for 5s). The test
// shrinks WaitDelay so the pass path stays fast; a broken grace blocks ~5s and
// trips the elapsed check.
func TestExecRunnerReturnsAfterContextCancelDespiteHeldPipe(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	start := time.Now()
	_, err := ExecRunner{WaitDelay: 150 * time.Millisecond}.Run(ctx, "sh", "-c", `sleep 5 & exec sleep 5`)
	if err == nil {
		t.Fatal("expected an error from the cancelled command, got nil")
	}
	if elapsed := time.Since(start); elapsed > 2*time.Second {
		t.Fatalf("Run blocked %v past context cancel; want return within the WaitDelay grace", elapsed)
	}
}

// TestExecRunnerCleanSuccessHasNoError verifies a clean exit-0 command with no
// hard-failure stderr returns its stdout and a nil error.
func TestExecRunnerCleanSuccessHasNoError(t *testing.T) {
	out, err := ExecRunner{}.Run(context.Background(), "sh", "-c", `echo ok`)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(out) != "ok\n" {
		t.Errorf("stdout = %q, want %q", out, "ok\n")
	}
}

// TestLoggedRunnerReportsEachCommand asserts the decorator passes output and
// errors through untouched while logging a readable line per call: DEBUG with
// size and duration on success, ERROR with the cause on failure, and long
// format arguments elided so the command stays legible.
func TestLoggedRunnerReportsEachCommand(t *testing.T) {
	longFmt := strings.Repeat("%i|", 40)
	inner := &FakeRunner{
		Outputs: map[string][]byte{"squeue": []byte(strings.Repeat("x", 2048))},
		Errs:    map[string]error{"sacct": errors.New("connection refused")},
	}
	var lines []string
	clock := time.Unix(0, 0)
	r := LoggedRunner{
		Inner: inner,
		Log:   func(level, msg string) { lines = append(lines, level+" "+msg) },
		Now: func() time.Time {
			clock = clock.Add(250 * time.Millisecond)
			return clock
		},
	}

	out, err := r.Run(context.Background(), "squeue", "-u", "alice", "-o", longFmt)
	if err != nil || len(out) != 2048 {
		t.Fatalf("Run = %d bytes, %v; want passthrough of 2048 bytes", len(out), err)
	}
	if _, err := r.Run(context.Background(), "sacct", "-n"); err == nil || err.Error() != "connection refused" {
		t.Fatalf("failure not passed through: %v", err)
	}
	if len(lines) != 2 {
		t.Fatalf("logged %d lines, want 2: %q", len(lines), lines)
	}
	success := lines[0]
	if !strings.HasPrefix(success, "DEBUG squeue -u alice -o ") || !strings.HasSuffix(success, " → 2.0 KB in 250ms") ||
		strings.Contains(success, longFmt) || !strings.Contains(success, "…") || len(success) > 100 {
		t.Errorf("success line = %q; want DEBUG line with the long format elided, size and duration", success)
	}
	if want := "ERROR sacct -n failed after 250ms: connection refused"; lines[1] != want {
		t.Errorf("failure line = %q, want %q", lines[1], want)
	}
}
