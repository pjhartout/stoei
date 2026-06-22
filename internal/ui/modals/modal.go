package modals

import (
	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/ui/theme"
)

// Modal is the interface every overlay screen in this package implements. It
// mirrors the ui.Component contract but is defined here so the modals package
// does not import the ui package (which would be a cycle: ui imports modals).
// The ui package adapts a Modal into a ui.Component with a thin wrapper.
//
// Update returns the modal as a Modal so the owner can reassign it (I3). A modal
// whose Update returns done==true asks the root to pop it off the stack.
type Modal interface {
	// Init returns the Cmd the modal needs after it is pushed (for example a
	// fetch and a spinner tick). Modals with nothing to start return nil.
	Init() tea.Cmd
	// Update handles a message and returns the updated modal, any Cmd, and
	// whether the modal has finished (the root should pop it).
	Update(msg tea.Msg) (Modal, tea.Cmd, bool)
	// View renders the modal to a string.
	View() string
	// SetSize informs the modal of the available terminal width and height.
	SetSize(width, height int)
	// SetStyles re-themes the modal after a background/theme change.
	SetStyles(styles theme.Styles)
	// ShortHelp returns the condensed help bindings for the modal.
	ShortHelp() []key.Binding
	// FullHelp returns the expanded help bindings for the modal.
	FullHelp() [][]key.Binding
}

// closeKeys are the keys that dismiss a simple modal (esc and q). Search-aware
// modals (the log viewer) handle esc specially and do not use this directly.
func isCloseKey(msg tea.KeyPressMsg) bool {
	switch msg.String() {
	case "esc", "q":
		return true
	default:
		return false
	}
}
