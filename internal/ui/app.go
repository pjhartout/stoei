// Package ui contains the Bubble Tea v2 application: the root model, chrome, and
// the wiring of tabs, modals, and components. Only this layer (and its
// subpackages) imports Bubble Tea and lipgloss.
//
// This file holds the real root model (Phase 3). It owns the Store, the
// SlurmClient, the tab sub-models, a modal stack, the two refresh tickers, the
// help bar, a toast list fed by the health notifier, and the theme/styles. The
// Store is mutated only here, on the main loop goroutine, and never inside a
// fetch Cmd or View.
package ui

import (
	"fmt"
	"strings"

	"charm.land/bubbles/v2/help"
	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/keys"
	"github.com/pjhartout/stoei/internal/ui/tabs"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// tabIndex identifies the active top-level tab.
type tabIndex int

const (
	tabJobs tabIndex = iota
	tabNodes
	tabUsers
	tabPriority
	tabLogs
	numTabs
)

// tabTitles are the labels shown in the tab bar, in tabIndex order.
var tabTitles = [numTabs]string{"Jobs", "Nodes", "Users", "Priority", "Logs"}

// maxToasts caps how many toast lines are shown at once.
const maxToasts = 3

// App is the root Bubble Tea model. It is a value type (Bubble Tea copies models
// between Update calls); the Store and SlurmClient are pointers/interfaces so the
// shared mutable state lives behind them.
type App struct {
	store  *store.Store
	client store.SlurmClient

	keys      keys.KeyMap
	help      help.Model
	theme     theme.Theme
	styles    theme.Styles
	intervals Intervals

	notifier *healthNotifier
	toasts   []string

	// Tabs held concretely; the active tab receives routed input.
	jobs   *tabs.Jobs
	others [numTabs]*tabs.Placeholder // indexed by tabIndex; tabJobs slot unused
	active tabIndex

	// modals is the modal stack. It is empty in Phase 3 but the type and the
	// push/pop helpers exist so later phases composite over the base.
	modals []Component

	// runningInFlight guards the fast tier: while a running-jobs fetch is
	// outstanding a fast tick skips dispatching another (but still re-arms).
	runningInFlight bool
	// heavyInFlight guards the slow tier the same way for the heavy batch.
	heavyInFlight bool

	// unavailable holds the Slurm-availability error; non-nil renders the
	// full-screen unavailable screen.
	unavailable error
	// availChecked records that the one-shot availability probe has completed.
	availChecked bool

	width  int
	height int
	dark   bool

	// frame memoizes the base render so an unchanged fast tick reuses it (I10).
	// It is a pointer so the value-receiver View can update the cache; the model
	// itself stays a value type for the rest of its fields.
	frame    *frameCache
	quitting bool
}

// frameCache memoizes the rendered base frame behind a dirty flag (I10). View
// rebuilds only when dirty is set; Update sets dirty whenever model state that
// affects the frame changes, so an unchanged fast tick reuses the cached string.
type frameCache struct {
	dirty bool
	base  string
}

// New constructs the root model wired to s and client. Styles default to dark
// until the terminal reports its background.
func New(s *store.Store, client store.SlurmClient) App {
	t := theme.Charm()
	styles := theme.BuildStyles(t, true)

	username := client.Username()
	a := App{
		store:     s,
		client:    client,
		keys:      keys.Default(),
		help:      help.New(),
		theme:     t,
		styles:    styles,
		intervals: DefaultIntervals(),
		notifier:  newHealthNotifier(),
		dark:      true,
		frame:     &frameCache{dirty: true},
		jobs:      tabs.NewJobs(s, username, styles),
	}
	for i := tabIndex(0); i < numTabs; i++ {
		if i == tabJobs {
			continue
		}
		a.others[i] = tabs.NewPlaceholder(tabTitles[i], styles)
	}
	return a
}

// Init fires the minimal-critical first wave (availability + running jobs +
// history), then a batched dispatch of the heavy sections, and starts both
// tickers. Each fetch bumps its section generation and marks it loading (I4).
func (a App) Init() tea.Cmd {
	critical := tea.Batch(
		checkAvailability(a.client),
		a.dispatchRunning(),
		a.dispatchHistory(),
	)
	heavy := a.dispatchHeavy()

	return tea.Batch(
		tea.RequestBackgroundColor,
		critical,
		heavy,
		fastTick(a.intervals.Fast),
		slowTick(a.intervals.Slow),
	)
}

// dispatchRunning bumps the running-jobs generation, marks it loading, sets the
// in-flight guard, and returns the fetch Cmd.
func (a *App) dispatchRunning() tea.Cmd {
	gen := a.store.NextGen(store.SectionRunningJobs)
	a.store.SetLoading(store.SectionRunningJobs, gen)
	a.runningInFlight = true
	return fetchRunningJobs(a.client, gen)
}

// dispatchHistory bumps the history generation, marks it loading, and returns the
// fetch Cmd.
func (a *App) dispatchHistory() tea.Cmd {
	gen := a.store.NextGen(store.SectionHistory)
	a.store.SetLoading(store.SectionHistory, gen)
	return fetchHistory(a.client, gen, historyDays)
}

// dispatchHeavy bumps every heavy section's generation, marks each loading, sets
// the in-flight guard, and returns a batched Cmd for the whole wave.
func (a *App) dispatchHeavy() tea.Cmd {
	a.heavyInFlight = true

	gNodes := a.store.NextGen(store.SectionNodes)
	a.store.SetLoading(store.SectionNodes, gNodes)
	gAll := a.store.NextGen(store.SectionAllUsersJobs)
	a.store.SetLoading(store.SectionAllUsersJobs, gAll)
	gFair := a.store.NextGen(store.SectionFairShare)
	a.store.SetLoading(store.SectionFairShare, gFair)
	gPend := a.store.NextGen(store.SectionPendingPrio)
	a.store.SetLoading(store.SectionPendingPrio, gPend)
	gEnergy := a.store.NextGen(store.SectionEnergy)
	a.store.SetLoading(store.SectionEnergy, gEnergy)
	gWait := a.store.NextGen(store.SectionWaitTime)
	a.store.SetLoading(store.SectionWaitTime, gWait)

	return tea.Batch(
		fetchNodes(a.client, gNodes),
		fetchAllUsersJobs(a.client, gAll),
		fetchFairShare(a.client, gFair),
		fetchPendingPrio(a.client, gPend),
		fetchEnergy(a.client, gEnergy, energyMonths),
		fetchWaitTime(a.client, gWait, waitTimeHours),
	)
}

// Default fetch windows. Phase 6 sources these from config.
const (
	historyDays   = 7
	energyMonths  = 1
	waitTimeHours = 1
)

// Update is the heart of the model: it wires window-size fanout, background
// detection, global keys, the two tick handlers, and the async result handlers.
func (a App) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		a.width = msg.Width
		a.height = msg.Height
		a.fanoutSize()
		a.frame.dirty = true
		return a, nil

	case tea.BackgroundColorMsg:
		if dark := msg.IsDark(); dark != a.dark {
			a.dark = dark
			a.rebuildStyles()
			a.frame.dirty = true
		}
		return a, nil

	case tea.KeyPressMsg:
		return a.handleKey(msg)

	case availabilityMsg:
		a.availChecked = true
		a.unavailable = msg.err
		a.frame.dirty = true
		return a, nil

	case fastTickMsg:
		return a.handleFastTick()

	case slowTickMsg:
		return a.handleSlowTick()

	case runningJobsMsg:
		a.runningInFlight = false
		a.store.SetRunningJobs(msg.jobs, msg.gen, msg.err)
		a.observe(store.SectionRunningJobs, msg.err)
		a.jobs.Refresh()
		a.frame.dirty = true
		return a, nil

	case historyMsg:
		a.store.SetHistory(msg.jobs, msg.stats, msg.gen, msg.err)
		a.observe(store.SectionHistory, msg.err)
		a.frame.dirty = true
		return a, nil

	case nodesMsg:
		a.store.SetNodes(msg.nodes, msg.gen, msg.err)
		a.observe(store.SectionNodes, msg.err)
		a.frame.dirty = true
		return a, nil

	case allUsersJobsMsg:
		a.store.SetAllUsersJobs(msg.jobs, msg.gen, msg.err)
		a.observe(store.SectionAllUsersJobs, msg.err)
		a.jobs.Refresh() // My-Usage banner derives from all-users jobs.
		a.frame.dirty = true
		return a, nil

	case fairShareMsg:
		a.store.SetFairShare(msg.entries, msg.gen, msg.err)
		a.observe(store.SectionFairShare, msg.err)
		a.frame.dirty = true
		return a, nil

	case pendingPrioMsg:
		a.store.SetPendingPrio(msg.entries, msg.gen, msg.err)
		a.observe(store.SectionPendingPrio, msg.err)
		a.frame.dirty = true
		return a, nil

	case energyMsg:
		a.store.SetEnergy(msg.records, msg.gen, msg.err)
		a.observe(store.SectionEnergy, msg.err)
		a.frame.dirty = true
		return a, nil

	case waitTimeMsg:
		a.heavyInFlight = false
		a.store.SetWaitTime(msg.records, msg.gen, msg.err)
		a.observe(store.SectionWaitTime, msg.err)
		a.frame.dirty = true
		return a, nil
	}

	return a.routeToActive(msg)
}

// handleKey processes global keys, then routes the remainder to the modal stack
// (if any) or the active tab. A modal consumes input first.
func (a App) handleKey(msg tea.KeyPressMsg) (tea.Model, tea.Cmd) {
	if len(a.modals) > 0 {
		return a.routeToActive(msg)
	}

	// When the active tab is capturing text (e.g. the Jobs filter bar), route raw
	// keys to it so they are typed rather than triggering global shortcuts.
	if a.active == tabJobs && a.jobs.CapturesInput() {
		return a.routeToActive(msg)
	}

	switch {
	case key.Matches(msg, a.keys.Quit):
		a.quitting = true
		return a, tea.Quit
	case key.Matches(msg, a.keys.Help):
		a.help.ShowAll = !a.help.ShowAll
		a.frame.dirty = true
		return a, nil
	case key.Matches(msg, a.keys.Refresh):
		return a, a.manualRefresh()
	}

	if idx, ok := tabForKey(msg); ok {
		a.active = idx
		a.frame.dirty = true
		return a, nil
	}
	switch msg.String() {
	case "tab":
		a.active = (a.active + 1) % numTabs
		a.frame.dirty = true
		return a, nil
	case "shift+tab":
		a.active = (a.active + numTabs - 1) % numTabs
		a.frame.dirty = true
		return a, nil
	}

	return a.routeToActive(msg)
}

// tabForKey maps the number keys 1-5 to their tab, returning ok=false otherwise.
func tabForKey(msg tea.KeyPressMsg) (tabIndex, bool) {
	switch msg.String() {
	case "1":
		return tabJobs, true
	case "2":
		return tabNodes, true
	case "3":
		return tabUsers, true
	case "4":
		return tabPriority, true
	case "5":
		return tabLogs, true
	}
	return 0, false
}

// manualRefresh re-dispatches the minimal-critical and heavy waves on the user's
// 'r' press, bumping every generation so superseded in-flight results are dropped
// (I4). It always provides feedback by re-fetching regardless of in-flight state.
func (a *App) manualRefresh() tea.Cmd {
	a.frame.dirty = true
	return tea.Batch(
		a.dispatchRunning(),
		a.dispatchHistory(),
		a.dispatchHeavy(),
	)
}

// handleFastTick dispatches a running-jobs refresh when none is in flight and
// always re-arms exactly the fast tier (I2).
func (a App) handleFastTick() (tea.Model, tea.Cmd) {
	cmds := []tea.Cmd{fastTick(a.intervals.Fast)}
	if !a.runningInFlight {
		cmds = append(cmds, a.dispatchRunning())
	}
	return a, tea.Batch(cmds...)
}

// handleSlowTick dispatches the heavy batch when none is in flight and always
// re-arms exactly the slow tier (I2).
func (a App) handleSlowTick() (tea.Model, tea.Cmd) {
	cmds := []tea.Cmd{slowTick(a.intervals.Slow)}
	if !a.heavyInFlight {
		cmds = append(cmds, a.dispatchHeavy())
	}
	return a, tea.Batch(cmds...)
}

// routeToActive forwards a message to the top modal (if any) or the active tab,
// reassigning the returned sub-model and batching its Cmd (I3).
func (a App) routeToActive(msg tea.Msg) (tea.Model, tea.Cmd) {
	if n := len(a.modals); n > 0 {
		top, cmd := a.modals[n-1].Update(msg)
		a.modals[n-1] = top
		a.frame.dirty = true
		return a, cmd
	}

	if a.active == tabJobs {
		var cmd tea.Cmd
		a.jobs, cmd = a.jobs.Update(msg)
		a.frame.dirty = true
		return a, cmd
	}

	var cmd tea.Cmd
	a.others[a.active], cmd = a.others[a.active].Update(msg)
	return a, cmd
}

// observe feeds a fetch outcome to the health notifier and appends/clears a toast
// on an edge transition (I9).
func (a *App) observe(section store.Section, err error) {
	if t, ok := a.notifier.Observe(section.String(), err == nil); ok {
		a.pushToast(t.Message)
	}
}

// pushToast appends a toast message, keeping at most maxToasts most-recent lines.
func (a *App) pushToast(msg string) {
	a.toasts = append(a.toasts, msg)
	if len(a.toasts) > maxToasts {
		a.toasts = a.toasts[len(a.toasts)-maxToasts:]
	}
	a.frame.dirty = true
}

// fanoutSize fans the cached size out to every tab and modal (I7). Tabs reserve
// space for the chrome (tab bar + footer).
func (a *App) fanoutSize() {
	w, h := a.size()
	innerH := h - chromeReservedRows
	if innerH < 1 {
		innerH = 1
	}
	a.jobs.SetSize(w, innerH)
	for i := tabIndex(0); i < numTabs; i++ {
		if i == tabJobs || a.others[i] == nil {
			continue
		}
		a.others[i].SetSize(w, innerH)
	}
	for _, m := range a.modals {
		m.SetSize(w, h)
	}
}

// chromeReservedRows is the vertical space the tab bar and footer occupy.
const chromeReservedRows = 4

// rebuildStyles rebuilds the styles for the current background and re-themes
// every tab and modal.
func (a *App) rebuildStyles() {
	a.styles = theme.BuildStyles(a.theme, a.dark)
	a.jobs.SetStyles(a.styles)
	for i := tabIndex(0); i < numTabs; i++ {
		if i == tabJobs || a.others[i] == nil {
			continue
		}
		a.others[i].SetStyles(a.styles)
	}
	for _, m := range a.modals {
		m.SetStyles(a.styles)
	}
}

// pushModal pushes a modal onto the stack and sizes it. It is unused in Phase 3
// but defines the seam Phase 5 builds on.
func (a *App) pushModal(m Component) {
	w, h := a.size()
	m.SetSize(w, h)
	a.modals = append(a.modals, m)
	a.frame.dirty = true
}

// popModal pops the top modal, if any.
func (a *App) popModal() {
	if n := len(a.modals); n > 0 {
		a.modals = a.modals[:n-1]
		a.frame.dirty = true
	}
}

// View composes the frame: the full-screen unavailable screen takes over when
// the availability check failed; otherwise the tab bar, active tab, footer, and
// toasts are composed, with the base render memoized behind dirty (I10) and the
// top modal composited over it via the lipgloss Canvas/Layer compositor.
func (a App) View() tea.View {
	if a.quitting {
		return tea.NewView("")
	}

	if a.availChecked && a.unavailable != nil {
		v := tea.NewView(a.unavailableView())
		v.AltScreen = true
		return v
	}

	base := a.frame.base
	if a.frame.dirty || base == "" {
		base = a.baseView()
		a.frame.base = base
		a.frame.dirty = false
	}

	content := base
	if len(a.modals) > 0 {
		content = a.overlayTopModal(base)
	}

	v := tea.NewView(content)
	v.AltScreen = true
	return v
}

// baseView renders the non-modal chrome plus the active tab.
func (a App) baseView() string {
	tabBar := a.tabBar()
	body := a.activeView()
	footer := a.footer()

	sections := []string{tabBar, body, footer}
	if toasts := a.toastView(); toasts != "" {
		sections = append(sections, toasts)
	}

	return lipgloss.JoinVertical(lipgloss.Left, sections...)
}

// tabBar renders the styled tab bar with the active tab highlighted.
func (a App) tabBar() string {
	cells := make([]string, 0, numTabs)
	for i := tabIndex(0); i < numTabs; i++ {
		label := fmt.Sprintf("%d %s", i+1, tabTitles[i])
		if i == a.active {
			cells = append(cells, a.styles.TabActive.Render(label))
		} else {
			cells = append(cells, a.styles.TabInactive.Render(label))
		}
	}
	title := a.styles.Title.Render("stoei")
	return lipgloss.JoinHorizontal(lipgloss.Top, append([]string{title}, cells...)...)
}

// activeView renders the active tab's body.
func (a App) activeView() string {
	if a.active == tabJobs {
		return a.jobs.View()
	}
	return a.others[a.active].View()
}

// footer renders the help bar reflecting the active tab's bindings plus the
// globals.
func (a App) footer() string {
	return a.help.View(a)
}

// toastView renders the current toast lines, styled as errors.
func (a App) toastView() string {
	if len(a.toasts) == 0 {
		return ""
	}
	lines := make([]string, len(a.toasts))
	for i, t := range a.toasts {
		lines[i] = a.styles.Error.Render(t)
	}
	return strings.Join(lines, "\n")
}

// unavailableView renders the full-screen Slurm-unavailable screen.
func (a App) unavailableView() string {
	w, h := a.size()
	box := a.styles.Modal.Render(lipgloss.JoinVertical(
		lipgloss.Center,
		a.styles.Error.Render("SLURM unavailable"),
		"",
		a.styles.Text.Render(a.unavailable.Error()),
		"",
		a.styles.Subtle.Render("Ensure squeue, scontrol, and sacct are on PATH. Press q to quit."),
	))
	return lipgloss.Place(w, h, lipgloss.Center, lipgloss.Center, box)
}

// overlayTopModal composites the top modal centered over base using the lipgloss
// v2 Canvas/Layer compositor.
func (a App) overlayTopModal(base string) string {
	w, h := a.size()
	modal := a.modals[len(a.modals)-1].View()

	mw := lipgloss.Width(modal)
	mh := lipgloss.Height(modal)
	x := max((w-mw)/2, 0)
	y := max((h-mh)/2, 0)

	return lipgloss.NewCanvas(w, h).
		Compose(lipgloss.NewLayer(base)).
		Compose(lipgloss.NewLayer(modal).X(x).Y(y).Z(1)).
		Render()
}

// size returns the cached terminal size, falling back to 80x24 before the first
// WindowSizeMsg arrives.
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

// ShortHelp implements help.KeyMap, combining the active tab's bindings with the
// global ones so the footer reflects the current context.
func (a App) ShortHelp() []key.Binding {
	bindings := a.activeShortHelp()
	return append(bindings, a.keys.Help, a.keys.Refresh, a.keys.Quit)
}

// FullHelp implements help.KeyMap for the expanded view.
func (a App) FullHelp() [][]key.Binding {
	groups := a.activeFullHelp()
	return append(groups, []key.Binding{a.keys.Refresh, a.keys.Help, a.keys.Quit})
}

// activeShortHelp returns the active tab's short-help bindings.
func (a App) activeShortHelp() []key.Binding {
	if a.active == tabJobs {
		return a.jobs.ShortHelp()
	}
	return a.others[a.active].ShortHelp()
}

// activeFullHelp returns the active tab's full-help groups.
func (a App) activeFullHelp() [][]key.Binding {
	if a.active == tabJobs {
		return a.jobs.FullHelp()
	}
	return a.others[a.active].FullHelp()
}
