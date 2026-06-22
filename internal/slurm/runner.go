package slurm

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"strings"
)

// Runner abstracts the execution of an external command. It is the single seam
// between the slurm package and the operating system, which lets tests inject
// canned output instead of spawning real Slurm subprocesses.
type Runner interface {
	// Run executes name with args and returns its standard output. The standard
	// error stream is captured but not returned; on failure it is folded into a
	// *CommandError (see ExecRunner.Run). The context bounds the command's
	// lifetime; callers are expected to pass a context with a timeout so a hung
	// scheduler call can be cancelled.
	Run(ctx context.Context, name string, args ...string) ([]byte, error)
}

// CommandError is returned by a Runner when a command fails. It carries the
// command name and the captured stderr alongside the underlying error so callers
// can classify hard failures (for example a slurmdbd "connection refused") that
// the scheduler writes only to stderr. A command can fail two ways: a non-zero
// exit (Err wraps the *exec.ExitError), or a zero exit that nonetheless printed a
// hard-failure signal to stderr (Err is nil).
type CommandError struct {
	// Name is the command that failed (for example "sacct").
	Name string
	// Stderr is the captured standard error, trimmed of trailing whitespace.
	Stderr string
	// Err is the underlying execution error, or nil when the command exited 0 but
	// printed a hard-failure signal to stderr.
	Err error
}

// Error renders the command name, the underlying error (if any), and the captured
// stderr so the message surfaces in logs and toasts.
func (e *CommandError) Error() string {
	switch {
	case e.Err != nil && e.Stderr != "":
		return fmt.Sprintf("%s: %v: %s", e.Name, e.Err, e.Stderr)
	case e.Err != nil:
		return fmt.Sprintf("%s: %v", e.Name, e.Err)
	default:
		return fmt.Sprintf("%s: %s", e.Name, e.Stderr)
	}
}

// Unwrap exposes the underlying execution error so errors.Is/As keep working
// against the wrapped *exec.ExitError.
func (e *CommandError) Unwrap() error { return e.Err }

// connectionRefusedSignal is the case-insensitive stderr substring that marks a
// non-transient failure (slurmdbd is down). The scheduler prints it to stderr and
// still exits 0, so it must be detected from stderr even on a clean exit.
const connectionRefusedSignal = "connection refused"

// hasHardFailureSignal reports whether stderr carries a non-transient failure
// signal that must be surfaced even when the command exited 0.
func hasHardFailureSignal(stderr string) bool {
	return strings.Contains(strings.ToLower(stderr), connectionRefusedSignal)
}

// ExecRunner is the production Runner. It shells out with exec.CommandContext so
// that cancelling the context kills the underlying process (for example an
// orphaned sacct).
type ExecRunner struct{}

// Run executes the command and returns its stdout. It captures stderr separately
// and uses exec.CommandContext so the process is killed when ctx is cancelled.
// It returns a *CommandError when the command exits non-zero, or when it exits 0
// but printed a hard-failure signal (a "connection refused" from slurmdbd) to
// stderr — that case otherwise looks like an empty-but-successful result.
func (ExecRunner) Run(ctx context.Context, name string, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	trimmed := strings.TrimRight(stderr.String(), "\r\n \t")
	if err != nil {
		return out, &CommandError{Name: name, Stderr: trimmed, Err: err}
	}
	if hasHardFailureSignal(trimmed) {
		return out, &CommandError{Name: name, Stderr: trimmed, Err: nil}
	}
	return out, nil
}

// FakeRunner is a test Runner that returns pre-seeded output keyed by command
// name. It records every invocation so tests can assert on the commands issued.
type FakeRunner struct {
	// Outputs maps a command name to the bytes Run should return for it.
	Outputs map[string][]byte
	// Errs maps a command name to the error Run should return for it.
	Errs map[string]error
	// Calls records each invocation in order.
	Calls []FakeCall
}

// FakeCall captures a single Run invocation.
type FakeCall struct {
	Name string
	Args []string
}

// Run returns the canned output for name, recording the call. If no output is
// registered for name it returns an empty slice and any registered error.
func (f *FakeRunner) Run(_ context.Context, name string, args ...string) ([]byte, error) {
	f.Calls = append(f.Calls, FakeCall{Name: name, Args: args})
	return f.Outputs[name], f.Errs[name]
}

// Compile-time assertions that both runners satisfy Runner.
var (
	_ Runner = ExecRunner{}
	_ Runner = (*FakeRunner)(nil)
)
