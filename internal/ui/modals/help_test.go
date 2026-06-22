package modals

import (
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/ui/keys"
)

// TestHelpRendersGroupedBindings asserts the full grouped help content carries
// every context section and a representative binding. The content is checked
// directly (not the clipped viewport) so a small test terminal does not hide the
// lower sections.
func TestHelpRendersGroupedBindings(t *testing.T) {
	content := renderHelpSections(helpSections(keys.Default()), testStyles())

	wantSections := []string{
		"Navigation", "Table Filtering & Sorting", "Jobs Tab",
		"Nodes / Users / Priority", "Detail Modals", "Log Viewer", "General",
	}
	for _, s := range wantSections {
		if !strings.Contains(content, s) {
			t.Errorf("help content missing section %q", s)
		}
	}
	for _, b := range []string{"View selected job details", "Open in $EDITOR", "Cancel selected job"} {
		if !strings.Contains(content, b) {
			t.Errorf("help content missing binding %q", b)
		}
	}

	// The modal itself renders without panicking and shows its title.
	h := NewHelp(keys.Default(), testStyles())
	h.SetSize(100, 30)
	if !strings.Contains(h.View(), "Keyboard Shortcuts") {
		t.Error("help modal view missing title")
	}
}

// TestHelpClosesOnQuestionMark asserts ?, esc, and q all close the help modal.
func TestHelpClosesOnQuestionMark(t *testing.T) {
	for _, k := range []tea.KeyPressMsg{
		{Code: '?', Text: "?"},
		{Code: tea.KeyEscape},
		{Code: 'q', Text: "q"},
	} {
		h := NewHelp(keys.Default(), testStyles())
		h.SetSize(100, 30)
		_, _, done := h.Update(k)
		if !done {
			t.Errorf("key %v should close the help modal", k)
		}
	}
}
