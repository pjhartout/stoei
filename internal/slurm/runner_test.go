package slurm

import (
	"context"
	"errors"
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
