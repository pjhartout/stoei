package modals

import (
	"strings"

	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/ui/keys"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// helpBinding is one (key, description) row in the help modal.
type helpBinding struct {
	key  string
	desc string
}

// helpSection is a titled group of keybindings in the help modal.
type helpSection struct {
	title    string
	bindings []helpBinding
}

// Help is the scrollable keybindings modal opened with "?". It lists the
// bindings grouped by context (navigation, filter/sort, columns, sidebar, jobs,
// nodes, details, log viewer, general), porting help_screen.HelpScreen. It is
// dismissed with esc, q, or ?.
type Help struct {
	box scrollBox
}

// NewHelp builds the help modal from the global KeyMap so the displayed keys
// reflect the active bindings. Ports HelpScreen._get_help_content.
func NewHelp(km keys.KeyMap, styles theme.Styles) *Help {
	h := &Help{box: newScrollBox(styles)}
	h.box.SetTitle("Keyboard Shortcuts")
	h.box.SetFooter("? / Esc to close   ↑/↓ scroll")
	h.box.SetContent(renderHelpSections(helpSections(km), styles))
	return h
}

// helpSections returns the grouped bindings, driven where possible by the
// KeyMap so a rebinding is reflected here. Ports the section list in
// HelpScreen._get_help_content.
func helpSections(km keys.KeyMap) []helpSection {
	return []helpSection{
		{"Navigation", []helpBinding{
			{"1", "Switch to Jobs tab"},
			{"2", "Switch to Nodes tab"},
			{"3", "Switch to Users tab"},
			{"4", "Switch to Priority tab"},
			{"5", "Switch to Logs tab"},
			{"Tab", "Next tab"},
			{"Shift+Tab", "Previous tab"},
		}},
		{"Table Filtering & Sorting", []helpBinding{
			{"/", "Show filter bar"},
			{"Esc", "Hide filter / Clear"},
			{"o", "Cycle sort order"},
			{"", "Filter syntax: 'state:RUNNING'"},
			{"", "or general search terms"},
		}},
		{"Jobs Tab", []helpBinding{
			{"↑/↓", "Navigate jobs list"},
			{"Enter", "View selected job details"},
			{"i", "Input job ID to view"},
			{"c", "Cancel selected job"},
		}},
		{"Nodes / Users / Priority", []helpBinding{
			{"↑/↓", "Navigate list"},
			{"Enter", "View selected row details"},
		}},
		{"Detail Modals", []helpBinding{
			{"o", "Open stdout log (jobs)"},
			{"e", "Open stderr log (jobs)"},
			{"↑/↓", "Scroll content"},
			{"Esc/q", "Close dialog"},
		}},
		{"Log Viewer", []helpBinding{
			{"g", "Go to top"},
			{"G", "Go to bottom"},
			{"l", "Toggle line numbers"},
			{"r", "Reload file"},
			{"e", "Open in $EDITOR"},
			{"c", "Show path"},
			{"/", "Search"},
			{"n / N", "Next / Previous match"},
			{"Esc/q", "Close viewer"},
		}},
		{"General", []helpBinding{
			{bindingKey(km.Refresh, "r"), "Refresh data now"},
			{bindingKey(km.Help, "?"), "Show this help screen"},
			{bindingKey(km.Quit, "q"), "Quit application"},
		}},
	}
}

// bindingKey returns the first key of a binding for display, falling back to def.
func bindingKey(b key.Binding, def string) string {
	if ks := b.Keys(); len(ks) > 0 {
		return ks[0]
	}
	return def
}

// renderHelpSections renders the sections into a single scrollable string. Ports
// HelpScreen._format_section (title, rule, right-aligned key, description).
func renderHelpSections(sections []helpSection, styles theme.Styles) string {
	var blocks []string
	for _, s := range sections {
		lines := []string{
			styles.Title.Render(s.title),
			styles.Subtle.Render(strings.Repeat("─", 40)),
		}
		for _, b := range s.bindings {
			keyCell := padLeft(b.key, 12)
			lines = append(lines, "  "+styles.Text.Bold(true).Render(keyCell)+"  "+styles.Text.Render(b.desc))
		}
		blocks = append(blocks, strings.Join(lines, "\n"))
	}
	return strings.Join(blocks, "\n\n")
}

// padLeft right-aligns s within width.
func padLeft(s string, width int) string {
	if len(s) >= width {
		return s
	}
	return strings.Repeat(" ", width-len(s)) + s
}

// Init has nothing to start for the help modal.
func (h *Help) Init() tea.Cmd { return nil }

// Update handles scrolling and dismissal. Ports HelpScreen.action_close (esc/q/?).
func (h *Help) Update(msg tea.Msg) (Modal, tea.Cmd, bool) {
	if km, ok := msg.(tea.KeyPressMsg); ok {
		if isCloseKey(km) || km.String() == "?" {
			return h, nil, true
		}
	}
	cmd := h.box.ScrollUpdate(msg)
	return h, cmd, false
}

// View renders the help box.
func (h *Help) View() string { return h.box.View() }

// SetSize lays out the help box.
func (h *Help) SetSize(w, height int) { h.box.SetSize(w, height) }

// SetStyles re-themes the help box and re-renders its content.
func (h *Help) SetStyles(styles theme.Styles) {
	h.box.SetStyles(styles)
	h.box.SetContent(renderHelpSections(helpSections(keys.Default()), styles))
}

// ShortHelp returns the help modal's own dismissal binding.
func (h *Help) ShortHelp() []key.Binding {
	return []key.Binding{key.NewBinding(key.WithKeys("esc"), key.WithHelp("esc", "close"))}
}

// FullHelp returns the expanded bindings.
func (h *Help) FullHelp() [][]key.Binding { return [][]key.Binding{h.ShortHelp()} }

// Compile-time assertion that Help satisfies Modal.
var _ Modal = (*Help)(nil)
