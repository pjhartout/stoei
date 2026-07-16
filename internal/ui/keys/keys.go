// Package keys defines the application's keybindings as a struct of
// key.Binding values. Two presets are available: vim (default) and emacs.
// BuildKeyMap returns a fresh KeyMap for a mode so the footer/help reflect the
// active preset automatically.
package keys

import "charm.land/bubbles/v2/key"

// Available keybinding modes.
const (
	// Vim is the default preset.
	Vim = "vim"
	// Emacs is the alternate preset.
	Emacs = "emacs"
)

// KeyMap is the set of global keybindings. It implements help.KeyMap. The keys
// for each binding depend on the active preset (vim vs emacs); the help text is
// shared so the footer reads the same regardless of mode.
type KeyMap struct {
	// Up moves the selection up.
	Up key.Binding
	// Down moves the selection down.
	Down key.Binding
	// Help toggles the full help view.
	Help key.Binding
	// Refresh forces a data refresh.
	Refresh key.Binding
	// Settings opens the settings modal.
	Settings key.Binding
	// Quit exits the application.
	Quit key.Binding
}

// BuildKeyMap returns a fresh KeyMap for the given preset. Unknown modes fall
// back to the vim preset.
func BuildKeyMap(mode string) KeyMap {
	if mode == Emacs {
		return emacsKeyMap()
	}
	return vimKeyMap()
}

// Default returns the default (vim) keybindings. Retained for callers that want
// the default preset without naming a mode.
func Default() KeyMap { return vimKeyMap() }

// vimKeyMap builds the vim preset's global and navigation bindings. Navigation
// adds arrow keys alongside the vim j/k so both work, matching the tabs which
// already accept arrows.
func vimKeyMap() KeyMap {
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
		Settings: key.NewBinding(
			key.WithKeys("s"),
			key.WithHelp("s", "settings"),
		),
		Quit: key.NewBinding(
			key.WithKeys("q", "ctrl+c"),
			key.WithHelp("q", "quit"),
		),
	}
}

// emacsKeyMap builds the emacs preset's global and navigation bindings (ctrl+p/n
// navigation, ctrl-prefixed globals, ctrl+comma settings). ctrl+c is kept on
// Quit so the program is always interruptible.
func emacsKeyMap() KeyMap {
	return KeyMap{
		Up: key.NewBinding(
			key.WithKeys("up", "ctrl+p"),
			key.WithHelp("↑/C-p", "up"),
		),
		Down: key.NewBinding(
			key.WithKeys("down", "ctrl+n"),
			key.WithHelp("↓/C-n", "down"),
		),
		Help: key.NewBinding(
			key.WithKeys("ctrl+h"),
			key.WithHelp("C-h", "help"),
		),
		Refresh: key.NewBinding(
			key.WithKeys("ctrl+r"),
			key.WithHelp("C-r", "refresh"),
		),
		Settings: key.NewBinding(
			key.WithKeys("ctrl+,"),
			key.WithHelp("C-,", "settings"),
		),
		Quit: key.NewBinding(
			key.WithKeys("ctrl+q", "ctrl+c"),
			key.WithHelp("C-q", "quit"),
		),
	}
}
