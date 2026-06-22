package ui

import (
	"bytes"
	"io"
	"strings"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/charmbracelet/x/exp/teatest/v2"
)

// TestSmokeAppRendersAndQuits drives the Phase 0 smoke model through the v2
// program loop: it sends a window size, opens the modal with "m", then quits
// with "q" and asserts on the final output. This locks the v2 teatest API
// (NewTestModel / Send(tea.KeyPressMsg) / WaitFinished / FinalOutput) and proves
// the model satisfies tea.Model end to end.
func TestSmokeAppRendersAndQuits(t *testing.T) {
	tm := teatest.NewTestModel(
		t, New(),
		teatest.WithInitialTermSize(80, 24),
	)

	// Open the modal and wait for the composited box to appear.
	tm.Send(tea.KeyPressMsg{Code: 'm', Text: "m"})
	teatest.WaitFor(t, tm.Output(), func(out []byte) bool {
		return bytes.Contains(out, []byte("composited over the base"))
	}, teatest.WithDuration(3*time.Second), teatest.WithCheckInterval(10*time.Millisecond))

	// Quit and confirm the program drains to the farewell view.
	tm.Send(tea.KeyPressMsg{Code: 'q', Text: "q"})
	tm.WaitFinished(t, teatest.WithFinalTimeout(3*time.Second))

	out := readAll(t, tm.FinalOutput(t, teatest.WithFinalTimeout(time.Second)))
	if !bytes.Contains(out, []byte("bye")) {
		t.Fatalf("final output missing farewell, got:\n%s", out)
	}
}

// TestSmokeAppQuitsOnCtrlC confirms ctrl+c also quits via the Quit binding.
func TestSmokeAppQuitsOnCtrlC(t *testing.T) {
	tm := teatest.NewTestModel(
		t, New(),
		teatest.WithInitialTermSize(80, 24),
	)

	tm.Send(tea.KeyPressMsg{Mod: tea.ModCtrl, Code: 'c'})
	tm.WaitFinished(t, teatest.WithFinalTimeout(3*time.Second))
}

// TestOverlayModalCompositesBox checks the lipgloss v2 Canvas/Layer compositor
// directly (no program loop): the rendered overlay must contain the modal's
// rounded border and its label, proving a centered box is drawn over the base.
func TestOverlayModalCompositesBox(t *testing.T) {
	a := New()
	a.width, a.height = 80, 24

	out := a.overlayModal("base-content")

	// Rounded border corner from lipgloss.RoundedBorder.
	if !strings.Contains(out, "╮") {
		t.Errorf("overlay missing rounded border corner, got:\n%s", out)
	}
	if !strings.Contains(out, "composited over the base") {
		t.Errorf("overlay missing modal body text, got:\n%s", out)
	}
}

func readAll(tb testing.TB, r io.Reader) []byte {
	tb.Helper()
	b, err := io.ReadAll(r)
	if err != nil {
		tb.Fatal(err)
	}
	return b
}
