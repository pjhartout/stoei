package modals

import (
	"context"
	"os/exec"
	"strings"
	"time"
)

// clipboardCmds is the ordered list of clipboard tools tried for a copy, with
// their fixed arguments: xclip and xsel (X11), wl-copy (Wayland), and pbcopy
// (macOS). The first one present on PATH wins.
var clipboardCmds = []struct {
	name string
	args []string
}{
	{"xclip", []string{"-selection", "clipboard"}},
	{"xsel", []string{"--clipboard", "--input"}},
	{"wl-copy", nil},
	{"pbcopy", nil}, // macOS
}

// clipboardTimeout bounds each clipboard command so an unresponsive tool cannot
// hang the copy.
const clipboardTimeout = 2 * time.Second

// copyToClipboard writes text to the system clipboard, trying each tool in
// clipboardCmds in order and returning true on the first success. Tools missing
// from PATH are skipped. It is pure IO with no UI dependency so it runs inside a
// Cmd closure, off the update loop.
func copyToClipboard(text string) bool {
	for _, c := range clipboardCmds {
		if _, err := exec.LookPath(c.name); err != nil {
			continue
		}
		ctx, cancel := context.WithTimeout(context.Background(), clipboardTimeout)
		// #nosec G204 -- name/args come from a fixed hardcoded list, never user input.
		cmd := exec.CommandContext(ctx, c.name, c.args...)
		cmd.Stdin = strings.NewReader(text)
		err := cmd.Run()
		cancel()
		if err == nil {
			return true
		}
	}
	return false
}

// clipboardAvailable reports whether any supported clipboard tool is on PATH, so
// a caller can fall back to a plain "show path" toast when no copy is possible.
func clipboardAvailable() bool {
	for _, c := range clipboardCmds {
		if _, err := exec.LookPath(c.name); err == nil {
			return true
		}
	}
	return false
}
