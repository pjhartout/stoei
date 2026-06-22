// Package keys defines the application's keybindings. KeyMap is a struct of
// key.Binding values that satisfies bubbles/help.KeyMap so the help bar renders
// itself from the active bindings.
package keys

import "charm.land/bubbles/v2/key"

// KeyMap is the set of global keybindings. It implements help.KeyMap.
type KeyMap struct {
	// Up moves the selection up.
	Up key.Binding
	// Down moves the selection down.
	Down key.Binding
	// Help toggles the full help view.
	Help key.Binding
	// Refresh forces a data refresh.
	Refresh key.Binding
	// Quit exits the application.
	Quit key.Binding
}

// Default returns the default (vim-flavored) keybindings.
func Default() KeyMap {
	return KeyMap{
		Up: key.NewBinding(
			key.WithKeys("up", "k"),
			key.WithHelp("↑/k", "up"),
		),
		Down: key.NewBinding(
			key.WithKeys("down", "j"),
			key.WithHelp("↓/j", "down"),
		),
		Help: key.NewBinding(
			key.WithKeys("?"),
			key.WithHelp("?", "help"),
		),
		Refresh: key.NewBinding(
			key.WithKeys("r"),
			key.WithHelp("r", "refresh"),
		),
		Quit: key.NewBinding(
			key.WithKeys("q", "ctrl+c"),
			key.WithHelp("q", "quit"),
		),
	}
}

// ShortHelp returns the bindings shown in the condensed help bar.
func (k KeyMap) ShortHelp() []key.Binding {
	return []key.Binding{k.Help, k.Quit}
}

// FullHelp returns the bindings shown in the expanded help view, grouped by
// column.
func (k KeyMap) FullHelp() [][]key.Binding {
	return [][]key.Binding{
		{k.Up, k.Down},
		{k.Refresh, k.Help, k.Quit},
	}
}
