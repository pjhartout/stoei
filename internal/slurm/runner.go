package slurm

import (
	"context"
	"os/exec"
)

// Runner abstracts the execution of an external command. It is the single seam
// between the slurm package and the operating system, which lets tests inject
// canned output instead of spawning real Slurm subprocesses.
type Runner interface {
	// Run executes name with args and returns its combined standard output.
	// The context bounds the command's lifetime; callers are expected to pass a
	// context with a timeout so a hung scheduler call can be cancelled.
	Run(ctx context.Context, name string, args ...string) ([]byte, error)
}

// ExecRunner is the production Runner. It shells out with exec.CommandContext so
// that cancelling the context kills the underlying process (for example an
// orphaned sacct).
type ExecRunner struct{}

// Run executes the command and returns its stdout. It uses exec.CommandContext
// so the process is killed when ctx is cancelled.
func (ExecRunner) Run(ctx context.Context, name string, args ...string) ([]byte, error) {
	return exec.CommandContext(ctx, name, args...).Output()
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
