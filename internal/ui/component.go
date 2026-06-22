package ui

import (
	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/ui/theme"
)

// Component is the screen interface every tab and modal implements. It is the
// third interface seam (alongside slurm.Runner and store.SlurmClient): the root
// model drives components through it without knowing their concrete type, which
// keeps the modal stack and tab switching uniform.
//
// Update returns the component as a Component (not a value receiver result) so
// the root can reassign it (I3). View renders to a string the root composes into
// the frame. SetSize is fanned out to every component on a WindowSizeMsg (I7).
// ShortHelp/FullHelp feed the help bar with the component's own bindings.
type Component interface {
	// Update handles a message and returns the updated component plus any Cmd.
	Update(msg tea.Msg) (Component, tea.Cmd)
	// View renders the component to a string.
	View() string
	// SetSize informs the component of the available width and height.
	SetSize(width, height int)
	// SetStyles re-themes the component after a background/theme change.
	SetStyles(styles theme.Styles)
	// ShortHelp returns the condensed help bindings for this component.
	ShortHelp() []key.Binding
	// FullHelp returns the expanded help bindings for this component.
	FullHelp() [][]key.Binding
}
