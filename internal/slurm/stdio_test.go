package slurm

import "testing"

// TestExpandStdIOPath pins the expansion contract: specifiers whose value the
// record pins down are substituted, everything else stays verbatim so a path
// is never fabricated from a guess.
func TestExpandStdIOPath(t *testing.T) {
	cases := []struct {
		name string
		path string
		want string
	}{
		{"plain job id", "/logs/train_%j.out", "/logs/train_100.out"},
		{"array master and task", "/logs/train_%A_%a.out", "/logs/train_77_3.out"},
		{"user and name", "/logs/%u/%x.out", "/logs/alice/train.out"},
		{"literal percent", "/logs/100%%_%j.out", "/logs/100%_100.out"},
		{"zero pad", "/logs/%5a.out", "/logs/00003.out"},
		{"node specifier left verbatim", "/logs/%N_%j.out", "/logs/%N_100.out"},
		{"trailing percent left verbatim", "/logs/train%", "/logs/train%"},
		{"no patterns untouched", "/logs/train.out", "/logs/train.out"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := expandStdIOPath(tc.path, "100", "77", "3", "alice", "train")
			if got != tc.want {
				t.Errorf("expandStdIOPath(%q) = %q, want %q", tc.path, got, tc.want)
			}
		})
	}
}

// TestExpandStdIOPathUnknownValues asserts the guard rails: a placeholder or
// array-form id must not be substituted into a path (sacct's per-user dump
// does not carry an array task's raw job id, and squeue prints "N/A" for
// non-array jobs' array columns).
func TestExpandStdIOPathUnknownValues(t *testing.T) {
	got := expandStdIOPath("/logs/%j_%A_%a.out", "123_[0-99]", "N/A", "", "alice", "train")
	if got != "/logs/%j_%A_%a.out" {
		t.Errorf("unknown id values must stay verbatim, got %q", got)
	}
}

// TestJobStdIODefaultsStderrToStdout covers the merged-stream default: without
// an explicit -e the scheduler writes stderr into the stdout file, and sacct
// then reports StdErr empty — the record must still open a stderr view.
func TestJobStdIODefaultsStderrToStdout(t *testing.T) {
	out, errPath := jobStdIO("/logs/train_%j.out", "", "100", "", "", "alice", "train")
	if out != "/logs/train_100.out" {
		t.Errorf("stdout = %q", out)
	}
	if errPath != out {
		t.Errorf("empty stderr must default to the stdout file, got %q", errPath)
	}
	// The scheduler's unset placeholders mean "no file", not a literal path.
	out, errPath = jobStdIO("(null)", "N/A", "100", "", "", "alice", "train")
	if out != "" || errPath != "" {
		t.Errorf("placeholders must normalize to empty, got %q / %q", out, errPath)
	}
}
