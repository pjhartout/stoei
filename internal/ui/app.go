// Package ui contains the Bubble Tea v2 application: the root model, chrome, and
// the wiring of tabs, modals, and components. Only this layer (and its
// subpackages) imports Bubble Tea and lipgloss.
//
// This file is the Phase 0 smoke model. It deliberately exercises every v2 API
// delta that the later phases depend on so those signatures are locked and
// compile-checked: the tea.Model interface (Init/Update/View with a tea.View
// return), v2 key messages (tea.KeyPressMsg), window-size caching, background
// color detection (tea.RequestBackgroundColor -> tea.BackgroundColorMsg), a
// bubbles/v2 component (spinner), and a modal overlay composited with the
// lipgloss v2 Canvas/Layer API.
package ui

import (
	"fmt"

	"charm.land/bubbles/v2/help"
	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/spinner"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/ui/keys"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// App is the root Bubble Tea model for the Phase 0 smoke build.
type App struct {
	keys    keys.KeyMap
	help    help.Model
	spinner spinner.Model

	theme  theme.Theme
	styles theme.Styles

	width  int
	height int

	// dark records the detected terminal background; styles are rebuilt when it
	// changes (see I10 / theme rebuild-on-change).
	dark bool
	// showModal toggles the centered overlay box.
	showModal bool
	// quitting marks that the program is exiting; View renders a short message.
	quitting bool
}

// New returns a fully initialized smoke App.
func New() App {
	t := theme.Charm()
	sp := spinner.New(spinner.WithSpinner(spinner.Dot))
	return App{
		keys:    keys.Default(),
		help:    help.New(),
		spinner: sp,
		theme:   t,
		// Default to dark until the terminal reports its background.
		dark:   true,
		styles: theme.BuildStyles(t, true),
	}
}

// Init starts the spinner and requests the terminal background color so the
// theme can pick light or dark styles. In v2 Init returns only a Cmd.
func (a App) Init() tea.Cmd {
	return tea.Batch(a.spinner.Tick, tea.RequestBackgroundColor)
}

// Update handles messages. It demonstrates the v2 message types the later
// phases rely on and always reassigns the returned sub-models (I3).
func (a App) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		// I7: the root caches size and would fan it out to sub-models.
		a.width = msg.Width
		a.height = msg.Height
		return a, nil

	case tea.BackgroundColorMsg:
		// v2 background detection: rebuild styles only when the mode flips.
		if dark := msg.IsDark(); dark != a.dark {
			a.dark = dark
			a.styles = theme.BuildStyles(a.theme, dark)
		}
		return a, nil

	case tea.KeyPressMsg:
		switch {
		case key.Matches(msg, a.keys.Quit):
			a.quitting = true
			return a, tea.Quit
		case key.Matches(msg, a.keys.Help):
			a.help.ShowAll = !a.help.ShowAll
			return a, nil
		case msg.String() == "m":
			a.showModal = !a.showModal
			return a, nil
		}
		return a, nil

	case spinner.TickMsg:
		var cmd tea.Cmd
		a.spinner, cmd = a.spinner.Update(msg)
		return a, cmd
	}

	return a, nil
}

// View renders the UI. In v2 View returns a tea.View (not a string); content is
// built with tea.NewView and AltScreen is a field on the view rather than a
// program option. The modal overlay is composited with the lipgloss Canvas and
// Layer API.
func (a App) View() tea.View {
	if a.quitting {
		return tea.NewView("bye\n")
	}

	base := a.baseView()

	content := base
	if a.showModal {
		content = a.overlayModal(base)
	}

	v := tea.NewView(content)
	v.AltScreen = true
	return v
}

// baseView renders the non-modal chrome: title, spinner, help, and a hint.
func (a App) baseView() string {
	title := a.styles.Title.Render("stoei")
	status := fmt.Sprintf("%s loading… (%dx%d)", a.spinner.View(), a.width, a.height)
	hint := a.styles.Subtle.Render("press m for modal · ? for help · q to quit")
	helpBar := a.help.View(a.keys)

	body := lipgloss.JoinVertical(
		lipgloss.Left,
		title,
		"",
		a.styles.Text.Render(status),
		hint,
		"",
		helpBar,
	)
	return body
}

// overlayModal composites a centered modal box over base using the lipgloss v2
// Canvas/Layer compositor. The base is the background layer; the modal is a
// second layer positioned at its centered (x, y).
func (a App) overlayModal(base string) string {
	w, h := a.size()

	modal := a.styles.Modal.Render(
		lipgloss.JoinVertical(
			lipgloss.Center,
			a.styles.Title.Render("Modal"),
			"",
			a.styles.Text.Render("This box is composited over the base."),
			a.styles.Subtle.Render("press m to close"),
		),
	)

	mw := lipgloss.Width(modal)
	mh := lipgloss.Height(modal)
	x := max((w-mw)/2, 0)
	y := max((h-mh)/2, 0)

	// NewCanvas takes an explicit size; layers are composited in order, so the
	// base is drawn first and the modal (higher Z) on top.
	canvas := lipgloss.NewCanvas(w, h).
		Compose(lipgloss.NewLayer(base)).
		Compose(lipgloss.NewLayer(modal).X(x).Y(y).Z(1))
	return canvas.Render()
}

// size returns the cached terminal size, falling back to a sane default before
// the first WindowSizeMsg arrives.
func (a App) size() (int, int) {
	w, h := a.width, a.height
	if w == 0 {
		w = 80
	}
	if h == 0 {
		h = 24
	}
	return w, h
}
