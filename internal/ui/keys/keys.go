// Package keys defines the application's keybindings. KeyMap is a struct of
// key.Binding values that satisfies bubbles/help.KeyMap so the help bar renders
// itself from the active bindings. Two presets are ported from the Python
// keybindings module: vim (default) and emacs. BuildKeyMap returns a fresh
// KeyMap for a mode so the footer/help reflect the active preset automatically.
package keys

import "charm.land/bubbles/v2/key"

// Mode identifies a keybinding preset. Ported from keybindings.KeybindMode.
type Mode = string

// Keybinding modes, ported from keybindings.KEYBIND_MODES.
const (
	// Vim is the default preset (keybindings.DEFAULT_PRESET).
	Vim Mode = "vim"
	// Emacs is the alternate preset.
	Emacs Mode = "emacs"
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
// back to vim (keybindings.DEFAULT_PRESET). Ports _create_vim_preset /
// _create_emacs_preset for the global + navigation actions the Go app uses.
func BuildKeyMap(mode Mode) KeyMap {
	if mode == Emacs {
		return emacsKeyMap()
	}
	return vimKeyMap()
}

// Default returns the default (vim) keybindings. Retained for callers that want
// the default preset without naming a mode.
func Default() KeyMap { return vimKeyMap() }

// vimKeyMap ports the vim preset's global + navigation bindings. Navigation adds
// arrow keys alongside the vim j/k so both work, matching the Go tabs which
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

// emacsKeyMap ports the emacs preset's global + navigation bindings (ctrl+p/n
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

// ShortHelp returns the bindings shown in the condensed help bar.
func (k KeyMap) ShortHelp() []key.Binding {
	return []key.Binding{k.Help, k.Settings, k.Quit}
}

// FullHelp returns the bindings shown in the expanded help view, grouped by
// column.
func (k KeyMap) FullHelp() [][]key.Binding {
	return [][]key.Binding{
		{k.Up, k.Down},
		{k.Refresh, k.Settings, k.Help, k.Quit},
	}
}
