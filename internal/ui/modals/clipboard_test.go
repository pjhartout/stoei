package modals

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"testing"
)

// sandboxPATH builds a temp dir, symlinks the host's sh and cat into it (so fake
// shell-script tools can run), points PATH at it exclusively, and returns the
// dir. This isolates the clipboard probe from any real clipboard tools on the
// host so the tests are deterministic.
func sandboxPATH(t *testing.T) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("shell-script fake tools are POSIX-only")
	}
	dir := t.TempDir()
	for _, util := range []string{"sh", "cat"} {
		hostPath, err := exec.LookPath(util)
		if err != nil {
			t.Skipf("host %s unavailable: %v", util, err)
		}
		if err := os.Symlink(hostPath, filepath.Join(dir, util)); err != nil {
			t.Fatalf("symlink %s: %v", util, err)
		}
	}
	t.Setenv("PATH", dir)
	return dir
}

// installFakeTool writes a fake clipboard tool named toolName into dir. The
// script copies its stdin to outFile (relative to dir) and exits exit.
func installFakeTool(t *testing.T, dir, toolName string, exit int) string {
	t.Helper()
	out := filepath.Join(dir, toolName+".out")
	script := "#!/bin/sh\ncat > " + out + "\nexit " + strconv.Itoa(exit) + "\n"
	if err := os.WriteFile(filepath.Join(dir, toolName), []byte(script), 0o755); err != nil { //nolint:gosec
		t.Fatalf("write fake tool: %v", err)
	}
	return out
}

func TestCopyToClipboardSuccess(t *testing.T) {
	dir := sandboxPATH(t)
	out := installFakeTool(t, dir, "xclip", 0)
	if !copyToClipboard("/var/log/job.out") {
		t.Fatal("copyToClipboard returned false; want true")
	}
	got, err := os.ReadFile(out)
	if err != nil {
		t.Fatalf("read copied file: %v", err)
	}
	if string(got) != "/var/log/job.out" {
		t.Errorf("copied = %q; want %q", got, "/var/log/job.out")
	}
}

func TestCopyToClipboardTriesNextOnFailure(t *testing.T) {
	dir := sandboxPATH(t)
	// First tool (xclip) fails; the next available tool (xsel) succeeds.
	installFakeTool(t, dir, "xclip", 1)
	out := installFakeTool(t, dir, "xsel", 0)
	if !copyToClipboard("data") {
		t.Fatal("copyToClipboard returned false; want true via fallback tool")
	}
	got, _ := os.ReadFile(out)
	if string(got) != "data" {
		t.Errorf("fallback tool copied = %q; want %q", got, "data")
	}
}

func TestCopyToClipboardAllFail(t *testing.T) {
	dir := sandboxPATH(t)
	for _, c := range clipboardCmds {
		installFakeTool(t, dir, c.name, 1)
	}
	if copyToClipboard("x") {
		t.Error("copyToClipboard returned true; want false when all tools fail")
	}
}

func TestCopyToClipboardNoTool(t *testing.T) {
	sandboxPATH(t) // sh+cat only, no clipboard tools
	if clipboardAvailable() {
		t.Fatal("clipboardAvailable = true with no clipboard tool; want false")
	}
	if copyToClipboard("x") {
		t.Error("copyToClipboard = true with no tool; want false")
	}
}

// TestLogViewerCopyPathFallsBack verifies the viewer toasts the plain path when
// no clipboard tool is available (the copy-path affordance still surfaces the
// path).
func TestLogViewerCopyPathFallsBack(t *testing.T) {
	sandboxPATH(t)
	v := NewLogViewer(testStyles(), "/var/log/job.out", "stdout", 0)
	cmd := v.copyPath()
	if cmd == nil {
		t.Fatal("copyPath returned nil cmd")
	}
	msg := cmd()
	toastMsg, ok := msg.(LogToastMsg)
	if !ok {
		t.Fatalf("copyPath msg = %T; want LogToastMsg", msg)
	}
	if toastMsg.Text != "Path: /var/log/job.out" {
		t.Errorf("fallback toast = %q; want %q", toastMsg.Text, "Path: /var/log/job.out")
	}
}

// TestLogViewerCopyPathSucceeds verifies the success toast when a clipboard tool
// is present.
func TestLogViewerCopyPathSucceeds(t *testing.T) {
	dir := sandboxPATH(t)
	installFakeTool(t, dir, "xclip", 0)
	v := NewLogViewer(testStyles(), "/var/log/job.out", "stdout", 0)
	cmd := v.copyPath()
	if cmd == nil {
		t.Fatal("copyPath returned nil cmd")
	}
	msg, ok := cmd().(LogToastMsg)
	if !ok {
		t.Fatalf("copyPath msg = %T; want LogToastMsg", cmd())
	}
	if msg.Text != "Copied path to clipboard" {
		t.Errorf("success toast = %q; want %q", msg.Text, "Copied path to clipboard")
	}
}
