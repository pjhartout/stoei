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
	"time"

	"charm.land/bubbles/v2/help"
	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/config"
	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/components"
	"github.com/pjhartout/stoei/internal/ui/keys"
	"github.com/pjhartout/stoei/internal/ui/modals"
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

	// cfg is the live user configuration. The settings modal mutates it and
	// re-applies the derived theme/keymap/intervals/windows in place.
	cfg config.Config

	keys      keys.KeyMap
	help      help.Model
	theme     theme.Theme
	styles    theme.Styles
	intervals Intervals

	// configPath is where Save writes the persisted config; empty disables
	// persistence (tests). It is resolved from the XDG path by the constructor.
	configPath string

	notifier *healthNotifier
	toasts   []toastItem

	// logs is the in-memory ring buffer of the app's own log lines; the Logs tab
	// renders from it and the app appends to it.
	logRing *components.LogRing

	// Tabs held concretely; the active tab receives routed input.
	jobs     *tabs.Jobs
	nodes    *tabs.Nodes
	users    *tabs.Users
	priority *tabs.Priority
	logsTab  *tabs.Logs
	active   tabIndex

	// sidebar renders cluster load; it is composed beside the active tab on wide
	// terminals and auto-hidden when narrow.
	sidebar *components.Sidebar

	// modals is the modal stack. The top modal consumes all input while open and
	// is composited over the base via the lipgloss Canvas/Layer compositor.
	modals []modals.Modal

	// detailCache memoizes rendered job details, evicting an entry when that
	// job's state changes (cache-evict-on-state-change, Python 77e57c3).
	detailCache *modals.JobDetailCache

	// runningInFlight guards the fast tier: while a running-jobs fetch is
	// outstanding a fast tick skips dispatching another (but still re-arms).
	runningInFlight bool
	// heavyInFlight guards the slow tier the same way for the heavy batch. It is
	// derived from heavyPending so it clears only once all heavy fetches return,
	// not when whichever finishes first does.
	heavyInFlight bool
	// heavyPending counts the outstanding heavy-wave fetches.
	heavyPending int

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

// New constructs the root model wired to s and client using the default
// configuration. Styles default to dark until the terminal reports its
// background. A fresh log ring is allocated; use NewWithLogRing to share an
// existing ring (for example one already wired as a logging sink).
func New(s *store.Store, client store.SlurmClient) App {
	return NewWithLogRing(s, client, components.NewLogRing(components.DefaultMaxLogLines))
}

// NewWithLogRing constructs the root model wired to s, client, and an existing
// log ring, using the default configuration.
func NewWithLogRing(s *store.Store, client store.SlurmClient, ring *components.LogRing) App {
	return NewWithConfig(s, client, ring, config.Default(), "")
}

// NewWithConfig constructs the root model from cfg: the theme, keymap, refresh
// intervals, history/energy windows, and log-viewer line count are all derived
// from the configuration rather than hardcoded. configPath is where the settings
// modal persists changes ("" disables persistence, for tests).
func NewWithConfig(s *store.Store, client store.SlurmClient, ring *components.LogRing, cfg config.Config, configPath string) App {
	t := theme.ByName(cfg.Theme)
	styles := theme.BuildStyles(t, true)

	username := client.Username()
	a := App{
		store:       s,
		client:      client,
		cfg:         cfg,
		configPath:  configPath,
		keys:        keys.BuildKeyMap(cfg.KeybindMode),
		help:        help.New(),
		theme:       t,
		styles:      styles,
		intervals:   intervalsFromConfig(cfg),
		notifier:    newHealthNotifier(),
		logRing:     ring,
		dark:        true,
		frame:       &frameCache{dirty: true},
		jobs:        tabs.NewJobs(s, username, styles),
		nodes:       tabs.NewNodes(s, styles),
		users:       tabs.NewUsers(s, styles, cfg.EnergyHistoryMonths),
		priority:    tabs.NewPriority(s, styles, username),
		logsTab:     tabs.NewLogs(ring, styles),
		sidebar:     components.NewSidebar(styles),
		detailCache: modals.NewJobDetailCache(),
	}
	// Apply the tab-local filter/sort bindings for the active preset so an
	// emacs-mode config rebinds them (C-s filter, C-o sort) from the start.
	a.applyKeyModeToTabs()
	return a
}

// applyKeyModeToTabs pushes the active keybinding preset's tab-local filter/sort
// bindings into every tab. Ports the part of the emacs preset that rebinds
// FILTER_SHOW/SORT_CYCLE for the tab tables.
func (a *App) applyKeyModeToTabs() {
	mode := a.cfg.KeybindMode
	a.jobs.SetKeyMode(mode)
	a.nodes.SetKeyMode(mode)
	a.users.SetKeyMode(mode)
	a.priority.SetKeyMode(mode)
}

// intervalsFromConfig derives the two-tier refresh intervals from cfg's
// refresh_interval (seconds): the fast tier is the configured interval, the slow
// tier is slowIntervalFactor times it.
func intervalsFromConfig(cfg config.Config) Intervals {
	fast := time.Duration(cfg.RefreshInterval * float64(time.Second))
	if fast <= 0 {
		fast = defaultFastInterval
	}
	return Intervals{Fast: fast, Slow: fast * slowIntervalFactor}
}

// LogRing returns the app's log ring so the caller can wire it as a logging sink.
func (a App) LogRing() *components.LogRing { return a.logRing }

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
	return fetchHistory(a.client, gen, a.cfg.JobHistoryDays)
}

// dispatchHeavy bumps every heavy section's generation, marks each loading, sets
// the in-flight guard, and returns a batched Cmd for the whole wave.
func (a *App) dispatchHeavy() tea.Cmd {
	a.heavyInFlight = true
	a.heavyPending = heavyFetchCount

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
		fetchEnergy(a.client, gEnergy, a.cfg.EnergyHistoryMonths),
		fetchWaitTime(a.client, gWait, waitTimeHours),
	)
}

// waitTimeHours is the per-partition wait-time lookback window. It is not user
// configurable (no Python Settings field exists for it).
const waitTimeHours = 1

// heavyFetchCount is the number of fetches dispatchHeavy batches; the slow-tier
// in-flight guard clears only after all of them return (see heavyDone).
const heavyFetchCount = 6

// heavyDone records that one heavy-wave fetch returned, clearing heavyInFlight
// only once all of them have. The guard must not be cleared by whichever fetch
// finishes first — waitTime in particular returns instantly during a slurmdbd
// cooldown — or a slow tick would re-dispatch the whole wave while the heavier
// squeue/scontrol fetches are still running.
func (a *App) heavyDone() {
	if a.heavyPending > 0 {
		a.heavyPending--
	}
	a.heavyInFlight = a.heavyPending > 0
}

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

	}

	if m, cmd, ok := a.handleDataMsg(msg); ok {
		return m, cmd
	}
	if m, cmd, ok := a.handleModalMsg(msg); ok {
		return m, cmd
	}
	return a.routeToActive(msg)
}

// handleDataMsg applies an async fetch result to the store and refreshes the
// affected views, returning handled=false for non-data messages. The six
// heavy-wave results call heavyDone so the slow-tier guard clears only once all
// of them return, not when whichever finishes first does.
func (a App) handleDataMsg(msg tea.Msg) (tea.Model, tea.Cmd, bool) {
	switch msg := msg.(type) {
	case runningJobsMsg:
		a.runningInFlight = false
		a.store.SetRunningJobs(msg.jobs, msg.gen, msg.err)
		a.observe(store.SectionRunningJobs, msg.err)
		a.jobs.Refresh()
		a.detailCache.SyncStates(a.store.MergedJobs()) // evict on state change (77e57c3)
		a.frame.dirty = true
		return a, nil, true

	case historyMsg:
		a.store.SetHistory(msg.jobs, msg.stats, msg.gen, msg.err)
		a.observe(store.SectionHistory, msg.err)
		a.jobs.Refresh() // Completed/failed history jobs merge into the Jobs table.
		a.detailCache.SyncStates(a.store.MergedJobs())
		a.frame.dirty = true
		return a, nil, true

	case nodesMsg:
		a.heavyDone()
		a.store.SetNodes(msg.nodes, msg.gen, msg.err)
		a.observe(store.SectionNodes, msg.err)
		a.nodes.Refresh()
		a.refreshSidebar() // ClusterStats derives from nodes.
		a.frame.dirty = true
		return a, nil, true

	case allUsersJobsMsg:
		a.heavyDone()
		a.store.SetAllUsersJobs(msg.jobs, msg.gen, msg.err)
		a.observe(store.SectionAllUsersJobs, msg.err)
		a.jobs.Refresh()   // My-Usage banner derives from all-users jobs.
		a.users.Refresh()  // Running/Pending panes derive from all-users jobs.
		a.refreshSidebar() // Pending resources derive from all-users jobs.
		a.frame.dirty = true
		return a, nil, true

	case fairShareMsg:
		a.heavyDone()
		a.store.SetFairShare(msg.entries, msg.gen, msg.err)
		a.observe(store.SectionFairShare, msg.err)
		a.priority.Refresh()
		a.frame.dirty = true
		return a, nil, true

	case pendingPrioMsg:
		a.heavyDone()
		a.store.SetPendingPrio(msg.entries, msg.gen, msg.err)
		a.observe(store.SectionPendingPrio, msg.err)
		a.priority.Refresh()
		a.frame.dirty = true
		return a, nil, true

	case energyMsg:
		a.heavyDone()
		a.store.SetEnergy(msg.records, msg.gen, msg.err)
		a.observe(store.SectionEnergy, msg.err)
		a.users.Refresh() // Energy pane derives from energy records.
		a.frame.dirty = true
		return a, nil, true

	case waitTimeMsg:
		a.heavyDone()
		a.store.SetWaitTime(msg.records, msg.gen, msg.err)
		a.observe(store.SectionWaitTime, msg.err)
		a.refreshSidebar() // Wait-time stats derive from wait-time records.
		a.frame.dirty = true
		return a, nil, true
	}
	return a, nil, false
}

// handleModalMsg processes the messages modals emit (job-id submit, log open,
// cancel result, toasts, settings), returning handled=false otherwise.
func (a App) handleModalMsg(msg tea.Msg) (tea.Model, tea.Cmd, bool) {
	switch msg := msg.(type) {
	case modals.JobIDSubmittedMsg:
		return a, a.openJobDetail(msg.JobID, ""), true

	case modals.OpenLogMsg:
		if strings.TrimSpace(msg.Path) == "" {
			a.pushToast("No " + msg.Label + " path available")
			return a, nil, true
		}
		return a, a.pushModal(modals.NewLogViewer(a.styles, msg.Path, msg.Label, a.cfg.LogViewerLines)), true

	case modals.CancelRequestedMsg:
		if msg.Err != nil {
			a.pushToast("Cancel failed for " + msg.JobID + ": " + msg.Err.Error())
			return a, nil, true
		}
		a.pushToast("Cancelled job " + msg.JobID)
		return a, a.manualRefresh(), true // refresh so the job leaves the list

	case modals.LogToastMsg:
		a.pushToast(msg.Text)
		return a, nil, true

	case modals.SettingsToastMsg:
		a.pushToast(msg.Text)
		return a, nil, true

	case modals.SettingsAppliedMsg:
		return a, a.applyConfig(msg.Config), true
	}
	return a, nil, false
}

// handleKey processes global keys, then routes the remainder to the modal stack
// (if any) or the active tab. A modal consumes input first.
func (a App) handleKey(msg tea.KeyPressMsg) (tea.Model, tea.Cmd) {
	if len(a.modals) > 0 {
		return a.routeToActive(msg)
	}

	// When the active tab is capturing text (e.g. a filter bar), route raw keys to
	// it so they are typed rather than triggering global shortcuts.
	if a.activeCapturesInput() {
		return a.routeToActive(msg)
	}

	// Sub-tab switch keys (Users r/p/e, Priority m/u/a/j) belong to the active tab
	// and take precedence over the global shortcuts that share a letter (e.g. the
	// 'r' refresh), matching the Python per-tab BINDINGS overriding globals.
	if a.activeHandlesSubtabKey(msg.String()) {
		return a.routeToActive(msg)
	}

	switch {
	case key.Matches(msg, a.keys.Quit):
		a.quitting = true
		return a, tea.Quit
	case key.Matches(msg, a.keys.Help):
		return a, a.pushModal(modals.NewHelp(a.keys, a.styles))
	case key.Matches(msg, a.keys.Settings):
		return a, a.pushModal(modals.NewSettings(a.styles, a.cfg))
	case key.Matches(msg, a.keys.Refresh):
		a.pushToast("Refreshing…")
		return a, a.manualRefresh()
	}

	// Detail/action keys open a modal for the active tab's selected row.
	if cmd, handled := a.handleModalOpenKey(msg); handled {
		return a, cmd
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

// handleModalOpenKey opens the right modal for the active tab's selected row:
// Enter opens a detail (job/node/user/account), "i" opens the job-id prompt, and
// "c" opens the cancel-confirm on the Jobs tab. It returns handled=false when the
// key is not one of these so the caller can fall through to tab navigation.
func (a *App) handleModalOpenKey(msg tea.KeyPressMsg) (tea.Cmd, bool) {
	switch msg.String() {
	case "enter":
		return a.openDetailForActive(), true
	case "i":
		if a.active == tabJobs {
			return a.pushModal(modals.NewJobInput(a.styles)), true
		}
	case "c":
		if a.active == tabJobs {
			return a.openCancelConfirm(), true
		}
	}
	return nil, false
}

// openDetailForActive opens the detail modal appropriate to the active tab's
// selected row.
func (a *App) openDetailForActive() tea.Cmd {
	switch a.active {
	case tabJobs:
		id, state, _, ok := a.jobs.SelectedJob()
		if !ok {
			a.pushToast("No job selected")
			return nil
		}
		return a.openJobDetail(id, state)
	case tabNodes:
		name := a.nodes.SelectedKey()
		if name == "" {
			a.pushToast("No node selected")
			return nil
		}
		return a.pushModal(modals.NewNodeDetail(a.client, a.styles, name))
	case tabUsers:
		user := a.users.SelectedKey()
		if user == "" {
			a.pushToast("No user selected")
			return nil
		}
		return a.pushModal(modals.NewUserDetail(a.store, a.styles, user))
	case tabPriority:
		kind, k := a.priority.SelectedDetail()
		switch kind {
		case tabs.PriorityDetailUser:
			if k == "" {
				return nil
			}
			return a.pushModal(modals.NewUserDetail(a.store, a.styles, k))
		case tabs.PriorityDetailAccount:
			if k == "" {
				return nil
			}
			return a.pushModal(modals.NewAccountDetail(a.store, a.styles, k))
		}
	}
	return nil
}

// openJobDetail pushes a job-detail modal for jobID at the given live state,
// consulting the detail cache (cache hit shows instantly, state change re-fetches).
func (a *App) openJobDetail(jobID, state string) tea.Cmd {
	return a.pushModal(modals.NewJobDetail(a.client, a.detailCache, a.styles, jobID, state))
}

// openCancelConfirm opens a cancel-confirm modal for the selected job, refusing
// to cancel a completed/failed job (a toast, no modal). Ports the
// active-job guard around CancelConfirmScreen.
func (a *App) openCancelConfirm() tea.Cmd {
	id, state, active, ok := a.jobs.SelectedJob()
	if !ok {
		a.pushToast("No job selected")
		return nil
	}
	if !active {
		a.pushToast("Cannot cancel " + id + ": job is not active (" + state + ")")
		return nil
	}
	name := a.jobs.SelectedJobName()
	return a.pushModal(modals.NewCancelConfirm(a.client, a.styles, id, name))
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

// manualRefresh re-dispatches the minimal-critical and heavy waves, bumping every
// generation so superseded in-flight results are dropped (I4). The caller owns any
// user-visible feedback (the 'r' key pushes a toast), since re-fetching alone is
// not visible while data is already on screen.
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
	// Auto-expire transient toasts each cycle so they don't linger indefinitely.
	a.expireToasts()
	// The log ring is appended to outside the Update loop (a logging sink), so the
	// Logs tab is re-rendered on the fast tick to surface new lines.
	a.logsTab.Refresh()
	a.frame.dirty = true
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
// reassigning the returned sub-model and batching its Cmd (I3). When the top
// modal reports done it is popped off the stack.
func (a App) routeToActive(msg tea.Msg) (tea.Model, tea.Cmd) {
	if n := len(a.modals); n > 0 {
		top, cmd, done := a.modals[n-1].Update(msg)
		a.modals[n-1] = top
		if done {
			a.popModal()
		}
		a.frame.dirty = true
		return a, cmd
	}

	var cmd tea.Cmd
	switch a.active {
	case tabJobs:
		a.jobs, cmd = a.jobs.Update(msg)
	case tabNodes:
		a.nodes, cmd = a.nodes.Update(msg)
	case tabUsers:
		a.users, cmd = a.users.Update(msg)
	case tabPriority:
		a.priority, cmd = a.priority.Update(msg)
	case tabLogs:
		a.logsTab, cmd = a.logsTab.Update(msg)
	}
	a.frame.dirty = true
	return a, cmd
}

// activeCapturesInput reports whether the active tab is consuming raw text input
// (a filter bar is open), so global shortcuts are routed to it instead.
func (a App) activeCapturesInput() bool {
	switch a.active {
	case tabJobs:
		return a.jobs.CapturesInput()
	case tabNodes:
		return a.nodes.CapturesInput()
	case tabUsers:
		return a.users.CapturesInput()
	case tabPriority:
		return a.priority.CapturesInput()
	default:
		return false
	}
}

// activeHandlesSubtabKey reports whether the active tab claims the given key as a
// sub-tab switch (Users: r/p/e; Priority: m/u/a/j).
func (a App) activeHandlesSubtabKey(k string) bool {
	switch a.active {
	case tabUsers:
		return k == "r" || k == "p" || k == "e"
	case tabPriority:
		return k == "m" || k == "u" || k == "a" || k == "j"
	default:
		return false
	}
}

// refreshSidebar pushes the current cluster stats into the sidebar, marking it
// loaded once the nodes section has produced data.
func (a *App) refreshSidebar() {
	loaded := a.store.State(store.SectionNodes) == store.StateLoaded
	a.sidebar.SetStats(a.store.ClusterStats, loaded)
	// The sidebar auto-fits its content, so its width can grow when new stats
	// arrive; re-lay-out the tabs to the new split and force a re-render.
	a.fanoutSize()
	a.frame.dirty = true
}

// observe feeds a fetch outcome to the health notifier and appends/clears a toast
// on an edge transition (I9). On a failing edge it prefers a section-specific,
// cause-aware message over the notifier's generic text so a slurmdbd outage reads
// clearly (for example "Job history unavailable: slurmdbd connection refused").
func (a *App) observe(section store.Section, err error) {
	t, ok := a.notifier.Observe(section.String(), err == nil)
	if !ok {
		return
	}
	level := toastSuccess
	if t.Kind == toastFailed {
		level = toastErrorLevel
		if msg := failureToastMessage(section, err); msg != "" {
			t.Message = msg
		}
	}
	a.pushToastLevel(t.Message, level)
}

// failureToastMessage returns a section-specific failure message, or "" to fall
// back to the notifier's generic text. The three sacct-backed sections special-
// case a slurmdbd "connection refused" so the user understands why that data is
// empty, rather than getting one informative and two generic toasts for the same
// outage.
func failureToastMessage(section store.Section, err error) string {
	if !store.IsSacctUnavailable(err) {
		return ""
	}
	switch section {
	case store.SectionHistory:
		return "Job history unavailable: slurmdbd connection refused"
	case store.SectionEnergy:
		return "Energy data unavailable: slurmdbd connection refused"
	case store.SectionWaitTime:
		return "Wait-time data unavailable: slurmdbd connection refused"
	}
	return ""
}

// pushToast appends a neutral (info) toast, keeping at most maxToasts most-recent
// items. Manual user feedback uses this level.
func (a *App) pushToast(msg string) {
	a.pushToastLevel(msg, toastInfo)
}

// pushToastLevel appends a toast at the given severity level with a fresh TTL,
// keeping at most maxToasts most-recent items.
func (a *App) pushToastLevel(msg string, level toastLevel) {
	a.toasts = append(a.toasts, toastItem{text: msg, level: level, ticks: toastTTL})
	if len(a.toasts) > maxToasts {
		a.toasts = a.toasts[len(a.toasts)-maxToasts:]
	}
	a.frame.dirty = true
}

// expireToasts decrements each toast's remaining ticks and drops expired ones. It
// runs on every fast tick so toasts auto-dismiss after toastTTL cycles. It
// returns whether anything was dropped so the caller can mark the frame dirty.
func (a *App) expireToasts() bool {
	if len(a.toasts) == 0 {
		return false
	}
	kept := a.toasts[:0]
	changed := false
	for _, t := range a.toasts {
		t.ticks--
		if t.ticks > 0 {
			kept = append(kept, t)
		} else {
			changed = true
		}
	}
	a.toasts = kept
	return changed
}

// fanoutSize fans the cached size out to every tab, the sidebar, and modals (I7).
// Tabs reserve space for the chrome (tab bar + footer) and, when the sidebar is
// shown, the sidebar's width.
func (a *App) fanoutSize() {
	w, h := a.size()
	innerH := h - chromeReservedRows
	if innerH < 1 {
		innerH = 1
	}

	a.sidebar.SetSize(0, innerH)
	tabW := w
	if components.ShouldShow(w) {
		tabW = w - a.sidebar.Width() // sidebar auto-fits its content; tab takes the rest
		if tabW < 1 {
			tabW = 1
		}
	}

	a.jobs.SetSize(tabW, innerH)
	a.nodes.SetSize(tabW, innerH)
	a.users.SetSize(tabW, innerH)
	a.priority.SetSize(tabW, innerH)
	a.logsTab.SetSize(tabW, innerH)

	for _, m := range a.modals {
		m.SetSize(w, h)
	}
}

// chromeReservedRows is the vertical space the tab bar, the rule beneath it, and
// the footer occupy.
const chromeReservedRows = 5

// rebuildStyles rebuilds the styles for the current background and re-themes
// every tab, the sidebar, and modals.
func (a *App) rebuildStyles() {
	a.styles = theme.BuildStyles(a.theme, a.dark)
	a.jobs.SetStyles(a.styles)
	a.nodes.SetStyles(a.styles)
	a.users.SetStyles(a.styles)
	a.priority.SetStyles(a.styles)
	a.logsTab.SetStyles(a.styles)
	a.sidebar.SetStyles(a.styles)
	for _, m := range a.modals {
		m.SetStyles(a.styles)
	}
}

// applyConfig persists the new config and applies it live: it swaps the theme
// (rebuilds styles and re-themes every sub-model), swaps the keymap (so the
// footer/help reflect the new preset), updates the refresh intervals, and pushes
// the new energy-months label to the Users tab. The history/energy/log-line
// windows are read from a.cfg on the next dispatch, so updating a.cfg suffices.
// A manual refresh is triggered so the new history/energy windows take effect at
// once. Ports the live-apply path of the Python settings flow.
func (a *App) applyConfig(cfg config.Config) tea.Cmd {
	themeChanged := cfg.Theme != a.cfg.Theme
	a.cfg = cfg

	a.theme = theme.ByName(cfg.Theme)
	if themeChanged {
		a.rebuildStyles()
	}
	a.keys = keys.BuildKeyMap(cfg.KeybindMode)
	a.applyKeyModeToTabs()
	a.intervals = intervalsFromConfig(cfg)
	a.users.SetEnergyMonths(cfg.EnergyHistoryMonths)

	if a.configPath != "" {
		if err := config.Save(a.configPath, cfg); err != nil {
			a.pushToast("Failed to save settings: " + err.Error())
		}
	}

	a.frame.dirty = true
	// Re-fetch so the new history/energy windows are reflected immediately.
	return a.manualRefresh()
}

// pushModal pushes a modal onto the stack, sizes it, and returns its Init Cmd so
// the caller can batch any fetch/spinner the modal starts. The top modal then
// consumes all input until it is popped.
func (a *App) pushModal(m modals.Modal) tea.Cmd {
	w, h := a.size()
	m.SetSize(w, h)
	a.modals = append(a.modals, m)
	a.frame.dirty = true
	return m.Init()
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

// baseView renders the non-modal chrome plus the active tab, composing the
// cluster sidebar beside the tab body on wide terminals (I7 narrow auto-hide).
func (a App) baseView() string {
	tabBar := a.tabBar()
	body := a.activeView()
	if components.ShouldShow(a.widthOrDefault()) {
		body = lipgloss.JoinHorizontal(lipgloss.Top, body, a.sidebar.View())
	}
	footer := a.footer()

	sections := []string{tabBar, a.tabBarRule(), body, footer}
	if toasts := a.toastView(); toasts != "" {
		sections = append(sections, toasts)
	}

	return lipgloss.JoinVertical(lipgloss.Left, sections...)
}

// widthOrDefault returns the cached terminal width, falling back to the default.
func (a App) widthOrDefault() int {
	w, _ := a.size()
	return w
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
	// The title carries a per-rune accent gradient for the charm.land look; pad it
	// to match the Title style's horizontal padding without coloring the spaces.
	title := " " + a.styles.TitleGradient("stoei") + " "
	return lipgloss.JoinHorizontal(lipgloss.Top, append([]string{title}, cells...)...)
}

// tabBarRule renders a thin horizontal rule under the tab bar to visually group
// the chrome from the body, spanning the full terminal width in the subtle border
// color.
func (a App) tabBarRule() string {
	w, _ := a.size()
	if w < 1 {
		w = 1
	}
	return a.styles.Subtle.Render(strings.Repeat("─", w))
}

// activeView renders the active tab's body.
func (a App) activeView() string {
	switch a.active {
	case tabNodes:
		return a.nodes.View()
	case tabUsers:
		return a.users.View()
	case tabPriority:
		return a.priority.View()
	case tabLogs:
		return a.logsTab.View()
	default:
		return a.jobs.View()
	}
}

// footer renders the help bar reflecting the active tab's bindings plus the
// globals.
func (a App) footer() string {
	return a.help.View(a)
}

// toastView renders the current toasts as boxed, accent/error/success-bordered
// transient notices (charm-style), with recovered toasts shown in success green
// and failures in error red.
func (a App) toastView() string {
	return renderToasts(a.toasts, a.styles)
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
	switch a.active {
	case tabNodes:
		return a.nodes.ShortHelp()
	case tabUsers:
		return a.users.ShortHelp()
	case tabPriority:
		return a.priority.ShortHelp()
	case tabLogs:
		return a.logsTab.ShortHelp()
	default:
		return a.jobs.ShortHelp()
	}
}

// activeFullHelp returns the active tab's full-help groups.
func (a App) activeFullHelp() [][]key.Binding {
	switch a.active {
	case tabNodes:
		return a.nodes.FullHelp()
	case tabUsers:
		return a.users.FullHelp()
	case tabPriority:
		return a.priority.FullHelp()
	case tabLogs:
		return a.logsTab.FullHelp()
	default:
		return a.jobs.FullHelp()
	}
}
