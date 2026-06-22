package slurm

import (
	"context"
	"errors"
	"os/exec"
	"testing"
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
	if !isConnectionRefused(err) {
		t.Errorf("isConnectionRefused(%v) = false, want true", err)
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
