// Package ui contains the Bubble Tea v2 application: the root model, chrome, and
// the wiring of tabs, modals, and components. Only this layer (and its
// subpackages) imports Bubble Tea and lipgloss.
//
// This file holds the root model. It owns the Store, the SlurmClient, the tab
// sub-models, a modal stack, the two refresh tickers, the help bar, a toast list
// fed by the health notifier, and the theme/styles. The Store is mutated only
// here, on the main loop goroutine, and never inside a fetch Cmd or View.
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
	// job's state changes (cache-evict-on-state-change).
	detailCache *modals.JobDetailCache

	// runningInFlight guards the fast tier: while a running-jobs fetch is
	// outstanding a fast tick skips dispatching another (but still re-arms). The
	// heavy (slow-tier) fetches are instead guarded per section by their
	// StateLoading flag, so visibility-gated and tick-driven dispatches never stack.
	runningInFlight bool
	// spinnerActive is true while the loading-spinner animation tick is in flight,
	// so it is started at most once and stopped when nothing is loading.
	spinnerActive bool

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
// intervals, history window, and log-viewer line count are all derived from the
// configuration rather than hardcoded. configPath is where the settings
// modal persists changes ("" disables persistence, for tests).
func NewWithConfig(s *store.Store, client store.SlurmClient, ring *components.LogRing, cfg config.Config, configPath string) App {
	t := theme.ByName(cfg.Theme)
	styles := theme.BuildStyles(t, true)

	username := client.Username()
	a := App{
		store:      s,
		client:     client,
		cfg:        cfg,
		configPath: configPath,
		keys:       keys.BuildKeyMap(cfg.KeybindMode),
		help:       help.New(),
		theme:      t,
		styles:     styles,
		intervals:  intervalsFromConfig(cfg),
		notifier:   newHealthNotifier(),
		logRing:    ring,
		dark:       true,
		frame:      &frameCache{dirty: true},
		// spinnerActive starts true because Init batches the first spinner tick.
		spinnerActive: true,
		jobs:          tabs.NewJobs(s, username, styles),
		nodes:         tabs.NewNodes(s, styles),
		users:         tabs.NewUsers(s, styles),
		priority:      tabs.NewPriority(s, styles, username),
		logsTab:       tabs.NewLogs(ring, styles),
		sidebar:       components.NewSidebar(styles),
		detailCache:   modals.NewJobDetailCache(),
	}
	// Apply the tab-local filter/sort bindings for the active preset so an
	// emacs-mode config rebinds them (C-s filter, C-o sort) from the start.
	a.applyKeyModeToTabs()
	return a
}

// applyKeyModeToTabs pushes the active keybinding preset's tab-local filter/sort
// bindings into every tab so a non-default preset (for example emacs mode, which
// rebinds filter to C-s and sort to C-o) takes effect on the tab tables.
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
	heavy := a.dispatchHeavyVisible()

	return tea.Batch(
		tea.RequestBackgroundColor,
		critical,
		heavy,
		fastTick(a.intervals.Fast),
		slowTick(a.intervals.Slow),
		spinnerTick(spinnerTickInterval),
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

// completionBulkThreshold is the just-vanished job count above which
// fetchCompletions switches from one "scontrol show jobid" per id to a single
// bulk history refresh. A draining array can vanish dozens of jobs in one tick;
// past this threshold the bulk path is both lighter and complete.
const completionBulkThreshold = 8

// fetchCompletions returns a Cmd that records the final state of just-vanished
// jobs in history, so completions observed mid-session reach the history view.
// For a small batch it asks the controller for each job's record directly; once
// the batch exceeds completionBulkThreshold (a draining array) it instead runs
// one bulk "scontrol show jobs" history refresh (throttled at the client), which
// captures every retained job in a single controller call rather than dozens —
// and, unlike the per-id path, drops none of them. Returns nil when nothing
// vanished.
func (a *App) fetchCompletions(ids []string) tea.Cmd {
	if len(ids) == 0 {
		return nil
	}
	if len(ids) > completionBulkThreshold {
		return a.dispatchHistory()
	}
	cmds := make([]tea.Cmd, len(ids))
	for i, id := range ids {
		cmds[i] = fetchCompletedJob(a.client, id)
	}
	return tea.Batch(cmds...)
}

// dispatchHistory bumps the history generation, marks it loading, and returns the
// fetch Cmd.
func (a *App) dispatchHistory() tea.Cmd {
	gen := a.store.NextGen(store.SectionHistory)
	a.store.SetLoading(store.SectionHistory, gen)
	return fetchHistory(a.client, gen, a.cfg.JobHistoryDays)
}

// dispatchHeavyVisible dispatches the heavy fetches whose data the UI can
// currently surface, leaving the rest unpolled to keep load off the controller.
// Nodes and all-users jobs are always refreshed: they feed the cluster sidebar,
// the always-available 'L' cluster-load modal, the Jobs My-Usage banner, and the
// Users tab, so a consumer is reachable from any tab. Fair-share and
// pending-priority are shown only on the Priority tab and the user/account detail
// modals (reachable from the Priority and Users tabs), so they are polled only
// while one of those tabs is active. Each fetch is guarded by its section's
// StateLoading flag (dispatchSection), so a slow tick and a tab-switch fetch never
// stack a duplicate, and generation tags drop any superseded result.
func (a *App) dispatchHeavyVisible() tea.Cmd {
	cmds := []tea.Cmd{
		a.dispatchSection(store.SectionNodes),
		a.dispatchSection(store.SectionAllUsersJobs),
	}
	if a.tabNeedsPriorityData(a.active) {
		cmds = append(cmds, a.dispatchSection(store.SectionFairShare), a.dispatchSection(store.SectionPendingPrio))
	}
	return tea.Batch(cmds...)
}

// tabNeedsPriorityData reports whether tab t renders fair-share / pending-priority
// data: the Priority tab directly, and the Users tab through the user/account
// detail modal.
func (a *App) tabNeedsPriorityData(t tabIndex) bool {
	return t == tabPriority || t == tabUsers
}

// dispatchSection bumps a heavy section's generation, marks it loading, and
// returns its fetch Cmd — unless it is already loading, in which case it returns
// nil so a concurrent dispatch is not stacked on top.
func (a *App) dispatchSection(section store.Section) tea.Cmd {
	if a.store.State(section) == store.StateLoading {
		return nil
	}
	gen := a.store.NextGen(section)
	a.store.SetLoading(section, gen)
	switch section {
	case store.SectionNodes:
		return fetchNodes(a.client, gen)
	case store.SectionAllUsersJobs:
		return fetchAllUsersJobs(a.client, gen)
	case store.SectionFairShare:
		return fetchFairShare(a.client, gen)
	case store.SectionPendingPrio:
		return fetchPendingPrio(a.client, gen)
	default:
		return nil
	}
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

	case spinnerTickMsg:
		return a.handleSpinnerTick()
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
// affected views, returning handled=false for non-data messages. Each heavy-wave
// result clears its own section's loading flag through the store setter, so the
// per-section dispatch guard releases independently.
func (a App) handleDataMsg(msg tea.Msg) (tea.Model, tea.Cmd, bool) {
	switch msg := msg.(type) {
	case runningJobsMsg:
		a.runningInFlight = false
		vanished := a.store.SetRunningJobs(msg.jobs, msg.gen, msg.err)
		a.observe(store.SectionRunningJobs, msg.err)
		a.jobs.Refresh()
		a.detailCache.SyncStates(a.store.MergedJobs()) // evict cached details on state change
		a.frame.dirty = true
		return a, a.fetchCompletions(vanished), true

	case historyMsg:
		a.store.SetHistory(msg.jobs, msg.stats, msg.gen, msg.err)
		a.observe(store.SectionHistory, msg.err)
		a.jobs.Refresh() // Completed/failed history jobs merge into the Jobs table.
		a.detailCache.SyncStates(a.store.MergedJobs())
		a.frame.dirty = true
		return a, nil, true

	case completedJobMsg:
		if msg.found {
			a.store.AddCompletedJob(msg.job)
			a.jobs.Refresh() // The finished job joins the history rows in the Jobs table.
			a.detailCache.SyncStates(a.store.MergedJobs())
			a.frame.dirty = true
		}
		return a, nil, true

	case nodesMsg:
		a.store.SetNodes(msg.nodes, msg.gen, msg.err)
		a.observe(store.SectionNodes, msg.err)
		a.nodes.Refresh()
		a.refreshSidebar() // ClusterStats derives from nodes.
		a.frame.dirty = true
		return a, nil, true

	case allUsersJobsMsg:
		a.store.SetAllUsersJobs(msg.jobs, msg.gen, msg.err)
		a.observe(store.SectionAllUsersJobs, msg.err)
		a.jobs.Refresh()   // My-Usage banner derives from all-users jobs.
		a.users.Refresh()  // Running/Pending panes derive from all-users jobs.
		a.refreshSidebar() // Pending resources derive from all-users jobs.
		a.frame.dirty = true
		return a, nil, true

	case fairShareMsg:
		a.store.SetFairShare(msg.entries, msg.gen, msg.err)
		a.observe(store.SectionFairShare, msg.err)
		a.priority.Refresh()
		a.frame.dirty = true
		return a, nil, true

	case pendingPrioMsg:
		a.store.SetPendingPrio(msg.entries, msg.gen, msg.err)
		a.observe(store.SectionPendingPrio, msg.err)
		a.priority.Refresh()
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
	// 'r' refresh): a tab-local binding overrides the global one.
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
	case msg.String() == "L":
		return a, a.openClusterLoad()
	}

	// Detail/action keys open a modal for the active tab's selected row.
	if cmd, handled := a.handleModalOpenKey(msg); handled {
		return a, cmd
	}

	if idx, ok := tabForKey(msg); ok {
		cmd := a.setActive(idx)
		return a, cmd
	}
	switch msg.String() {
	case "tab":
		cmd := a.setActive((a.active + 1) % numTabs)
		return a, cmd
	case "shift+tab":
		cmd := a.setActive((a.active + numTabs - 1) % numTabs)
		return a, cmd
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
// to cancel a completed/failed job (a toast, no modal): the confirm modal only
// opens for a job that is still active.
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

// setActive switches the active tab to idx (a no-op when it is already active) and
// fetches any heavy data the new tab needs but that went unpolled while it was
// hidden, so the tab shows fresh data on arrival rather than waiting for the next
// slow tick. Nodes and all-users are polled every tick regardless, so only the
// Priority/Users fair-share + pending-priority become newly needed; they are
// fetched when entering one of those tabs from outside. The dispatch self-skips
// while its section is already loading, bounding the cost of rapid tab cycling.
func (a *App) setActive(idx tabIndex) tea.Cmd {
	if idx == a.active {
		return nil
	}
	prev := a.active
	a.active = idx
	a.frame.dirty = true
	if a.tabNeedsPriorityData(idx) && !a.tabNeedsPriorityData(prev) {
		return tea.Batch(a.dispatchSection(store.SectionFairShare), a.dispatchSection(store.SectionPendingPrio), a.ensureSpinner())
	}
	return nil
}

// manualRefresh re-fetches the running jobs, the journal history, and the visible
// heavy data, bumping their generations so superseded in-flight results are
// dropped (I4). The running fetch is skipped while one is in flight; the heavy
// fetches self-skip per section while already loading (dispatchSection), and only
// the data the visible UI needs is refreshed (dispatchHeavyVisible). History
// refreshes from the controller journal (throttled at the client), so it is always
// re-run without ever touching slurmdbd. The caller owns user-visible feedback (the
// 'r' key pushes a toast), since re-fetching alone is not visible while data is on
// screen.
func (a *App) manualRefresh() tea.Cmd {
	a.frame.dirty = true
	cmds := []tea.Cmd{a.dispatchHistory()}
	if !a.runningInFlight {
		cmds = append(cmds, a.dispatchRunning())
	}
	cmds = append(cmds, a.dispatchHeavyVisible(), a.ensureSpinner())
	return tea.Batch(cmds...)
}

// handleFastTick dispatches a running-jobs refresh when none is in flight and
// always re-arms exactly the fast tier (I2). The live squeue list is never gated
// on terminal focus: focus is not visibility (a visible-but-unfocused pane — a
// tmux split, a tiling layout — would otherwise silently freeze), so the primary
// list the user watches always refreshes.
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
	cmds = append(cmds, a.ensureSpinner())
	return a, tea.Batch(cmds...)
}

// handleSlowTick dispatches the visible heavy fetches and always re-arms exactly
// the slow tier (I2). Each fetch self-skips while its section is already loading,
// so a tick never stacks a duplicate. Controller load is bounded by tab visibility
// (dispatchHeavyVisible) — what is actually on screen — not by terminal focus.
func (a App) handleSlowTick() (tea.Model, tea.Cmd) {
	cmds := []tea.Cmd{slowTick(a.intervals.Slow)}
	cmds = append(cmds, a.dispatchHeavyVisible(), a.ensureSpinner())
	return a, tea.Batch(cmds...)
}

// ensureSpinner starts the loading-spinner animation tick if it is not already
// running and a section is loading, returning the tick Cmd (or nil). Guarding on
// spinnerActive keeps at most one spinner tier in flight.
func (a *App) ensureSpinner() tea.Cmd {
	if a.spinnerActive || !a.store.AnyLoading() {
		return nil
	}
	a.spinnerActive = true
	return spinnerTick(spinnerTickInterval)
}

// handleSpinnerTick advances the loading-spinner animation: it marks the frame
// dirty so the spinner re-renders its next wall-clock frame, and re-arms only
// while something is still loading, so the tick stops when the UI goes idle.
func (a App) handleSpinnerTick() (tea.Model, tea.Cmd) {
	if !a.store.AnyLoading() {
		a.spinnerActive = false
		return a, nil
	}
	a.frame.dirty = true
	return a, spinnerTick(spinnerTickInterval)
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

// openClusterLoad opens the cluster-load statistics as a scrollable modal, so the
// full content is reachable even when it is taller than the sidebar can show (or
// the sidebar is hidden on a narrow terminal).
func (a *App) openClusterLoad() tea.Cmd {
	loaded := a.store.State(store.SectionNodes) == store.StateLoaded
	return a.pushModal(modals.NewClusterLoad(a.store.ClusterStats, loaded, a.styles))
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
	}
	a.pushToastLevel(t.Message, level)
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
// footer/help reflect the new preset), and updates the refresh intervals. The
// history/log-line windows are read from a.cfg on the next dispatch, so updating
// a.cfg suffices. A manual refresh is triggered so the new history window takes
// effect at once.
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

	if a.configPath != "" {
		if err := config.Save(a.configPath, cfg); err != nil {
			a.pushToast("Failed to save settings: " + err.Error())
		}
	}

	a.frame.dirty = true
	// Re-fetch so the new history window is reflected immediately.
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
	w, h := a.size()
	body := a.activeView()

	// Constrain the active tab to its allotted width so a wide table is clipped at
	// the panel edge (and padded to fill it) instead of rendering at its full
	// natural width and overflowing past the sidebar / off the screen.
	tabW := w
	if components.ShouldShow(w) {
		tabW = max(w-a.sidebar.Width(), 1)
	}
	body = lipgloss.PlaceHorizontal(tabW, lipgloss.Left,
		lipgloss.NewStyle().MaxWidth(tabW).Render(body))

	if components.ShouldShow(w) {
		body = lipgloss.JoinHorizontal(lipgloss.Top, body, a.sidebar.View())
	}
	footer := a.footer()

	sections := []string{tabBar, a.tabBarRule(), body, footer}
	if toasts := a.toastView(); toasts != "" {
		// Trim the body to the space left after the toast so the toast box fits
		// within the terminal height instead of spilling off the bottom. 3 = the
		// tab bar, the rule, and the footer rows; the (possibly wrapped, possibly
		// stacked) toast takes the rest.
		bodyRows := max(h-3-lipgloss.Height(toasts), 1)
		sections[2] = lipgloss.NewStyle().MaxHeight(bodyRows).Render(body)
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
	return renderToasts(a.toasts, a.widthOrDefault(), a.styles)
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
		a.styles.Subtle.Render("Ensure squeue and scontrol are on PATH. Press q to quit."),
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

	// A Compositor (not chained Canvas.Compose) is required to honor each layer's
	// X/Y: Canvas.Compose draws a layer at the full canvas bounds, ignoring its
	// offset, so the modal would pin to the top-left. The Compositor flattens
	// layers to absolute positions and draws each at its own bounds.
	return lipgloss.NewCanvas(w, h).
		Compose(lipgloss.NewCompositor(
			lipgloss.NewLayer(base),
			lipgloss.NewLayer(modal).X(x).Y(y).Z(1),
		)).
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
