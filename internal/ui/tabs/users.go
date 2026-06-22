package tabs

import (
	"fmt"
	"sort"
	"strconv"

	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// userSubtab identifies the active Users sub-pane.
type userSubtab int

const (
	subtabRunning userSubtab = iota
	subtabPending
	subtabEnergy
)

// runningUserColumns are the Running sub-tab columns: per-user running totals
// (user, jobs, CPUs, memory, GPUs, GPU types, nodes, and node list).
var runningUserColumns = []column{
	{key: "user", title: "User"},
	{key: "jobs", title: "Jobs", numeric: true},
	{key: "cpus", title: "CPUs", numeric: true},
	{key: "memory", title: "Memory (GB)", numeric: true},
	{key: "gpus", title: "GPUs", numeric: true},
	{key: "gpu_types", title: "GPU Types"},
	{key: "nodes", title: "Nodes", numeric: true},
	{key: "nodelist", title: "NodeList"},
}

// pendingUserColumns are the Pending sub-tab columns: per-user requested totals
// for pending jobs (user, pending jobs, CPUs, memory, GPUs, GPU types).
var pendingUserColumns = []column{
	{key: "user", title: "User"},
	{key: "pending_jobs", title: "Pending Jobs", numeric: true},
	{key: "cpus", title: "CPUs Requested", numeric: true},
	{key: "memory", title: "Memory (GB)", numeric: true},
	{key: "gpus", title: "GPUs Requested", numeric: true},
	{key: "gpu_types", title: "GPU Types"},
}

// energyUserColumns are the Energy sub-tab columns: per-user energy and
// CPU/GPU-hour totals (user, jobs, energy, GPU-hours, CPU-hours).
var energyUserColumns = []column{
	{key: "user", title: "User"},
	{key: "jobs", title: "Jobs", numeric: true},
	{key: "energy", title: "Energy"},
	{key: "gpu_hours", title: "GPU-hours", numeric: true},
	{key: "cpu_hours", title: "CPU-hours", numeric: true},
}

// Users is the user-overview tab. It is a two-level mini-root: it owns three
// filterable sub-pane tables (Running / Pending / Energy) and an activeSubtab,
// switching between them on the r/p/e keys. Each pane renders from a different
// store aggregation (running/pending per-user stats, energy stats).
// Enter→user-detail modal is deferred to Phase 5.
type Users struct {
	store        *store.Store
	styles       theme.Styles
	energyMonths int

	running filterTable
	pending filterTable
	energy  filterTable

	status       sectionStatus
	activeSubtab userSubtab
	width        int
	height       int
}

// NewUsers returns a Users tab bound to s. energyMonths labels the energy pane.
func NewUsers(s *store.Store, styles theme.Styles, energyMonths int) *Users {
	u := &Users{store: s, styles: styles, energyMonths: energyMonths, status: newSectionStatus()}
	u.running = newFilterTable(runningUserColumns, styles, nil)
	u.pending = newFilterTable(pendingUserColumns, styles, nil)
	u.energy = newFilterTable(energyUserColumns, styles, nil)
	u.Refresh()
	return u
}

// active returns a pointer to the currently active sub-pane table.
func (u *Users) active() *filterTable {
	switch u.activeSubtab {
	case subtabPending:
		return &u.pending
	case subtabEnergy:
		return &u.energy
	default:
		return &u.running
	}
}

// SetEnergyMonths updates the energy-window label (months) used by the energy
// pane header, applied live when the user changes it in settings.
func (u *Users) SetEnergyMonths(months int) {
	u.energyMonths = months
	u.Refresh()
}

// SetKeyMode switches every sub-pane's filter/sort bindings to the given preset.
func (u *Users) SetKeyMode(mode string) {
	u.running.SetKeyMode(mode)
	u.pending.SetKeyMode(mode)
	u.energy.SetKeyMode(mode)
}

// SetStyles re-themes all three panes.
func (u *Users) SetStyles(styles theme.Styles) {
	u.styles = styles
	u.running.SetStyles(styles)
	u.pending.SetStyles(styles)
	u.energy.SetStyles(styles)
}

// SetSize records the area and sizes every pane, reserving a row for the sub-tab
// header (I7).
func (u *Users) SetSize(width, height int) {
	u.width = width
	u.height = height
	inner := height - subtabHeaderRows
	if inner < 1 {
		inner = 1
	}
	u.running.SetSize(width, inner)
	u.pending.SetSize(width, inner)
	u.energy.SetSize(width, inner)
}

// subtabHeaderRows is the vertical space reserved for the sub-tab header.
const subtabHeaderRows = 2

// Update routes sub-tab-switch keys (r/p/e) to a switch, otherwise forwards to
// the active pane. The owning root reassigns the returned model and batches the
// cmd (I3).
func (u *Users) Update(msg tea.Msg) (*Users, tea.Cmd) {
	if km, ok := msg.(tea.KeyPressMsg); ok && !u.active().CapturesInput() {
		switch km.String() {
		case "r":
			u.activeSubtab = subtabRunning
			u.reobserve()
			return u, nil
		case "p":
			u.activeSubtab = subtabPending
			u.reobserve()
			return u, nil
		case "e":
			u.activeSubtab = subtabEnergy
			u.reobserve()
			return u, nil
		}
	}
	cmd := u.active().Update(msg)
	return u, cmd
}

// Refresh rebuilds all three panes from the store aggregations and updates the
// load-status tracker for the active sub-pane's backing section.
func (u *Users) Refresh() {
	u.running.SetRows(runningUserRows(u.store.RunningUserStats()))
	u.pending.SetRows(pendingUserRows(u.store.PendingUserStats()))
	u.energy.SetRows(energyUserRows(u.store.EnergyStats()))
	sec, hasData := u.activeSection()
	u.status.observe(u.store.State(sec), hasData)
}

// activeSection returns the store section backing the active sub-pane and whether
// that pane currently has rows. The Running and Pending panes both derive from
// the all-users-jobs section; the Energy pane derives from the energy section.
func (u *Users) activeSection() (store.Section, bool) {
	switch u.activeSubtab {
	case subtabEnergy:
		return store.SectionEnergy, len(u.energy.rows) > 0
	case subtabPending:
		return store.SectionAllUsersJobs, len(u.pending.rows) > 0
	default:
		return store.SectionAllUsersJobs, len(u.running.rows) > 0
	}
}

// runningUserRows builds the Running pane rows, sorted by total CPUs descending
// to surface the heaviest users first.
func runningUserRows(users []store.UserStats) [][]string {
	sorted := make([]store.UserStats, len(users))
	copy(sorted, users)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].TotalCPUs > sorted[j].TotalCPUs })

	rows := make([][]string, 0, len(sorted))
	for _, us := range sorted {
		rows = append(rows, []string{
			us.Username,
			strconv.Itoa(us.JobCount),
			strconv.Itoa(us.TotalCPUs),
			fmt.Sprintf("%.1f", us.TotalMemoryGB),
			strconv.Itoa(us.TotalGPUs),
			naIfEmpty(us.GPUTypes),
			strconv.Itoa(us.TotalNodes),
			naIfEmpty(us.NodeNames),
		})
	}
	return rows
}

// pendingUserRows builds the Pending pane rows. The store already sorts pending
// stats by requested CPUs descending.
func pendingUserRows(users []store.UserPendingStats) [][]string {
	rows := make([][]string, 0, len(users))
	for _, us := range users {
		rows = append(rows, []string{
			us.Username,
			strconv.Itoa(us.PendingJobCount),
			strconv.Itoa(us.PendingCPUs),
			fmt.Sprintf("%.1f", us.PendingMemoryGB),
			strconv.Itoa(us.PendingGPUs),
			naIfEmpty(us.PendingGPUTypes),
		})
	}
	return rows
}

// energyUserRows builds the Energy pane rows. The store already sorts energy
// stats by total energy descending.
func energyUserRows(users []store.UserEnergyStats) [][]string {
	rows := make([][]string, 0, len(users))
	for _, us := range users {
		rows = append(rows, []string{
			us.Username,
			strconv.Itoa(us.JobCount),
			store.FormatEnergy(us.TotalEnergyWh),
			fmt.Sprintf("%.0f", us.GPUHours),
			fmt.Sprintf("%.0f", us.CPUHours),
		})
	}
	return rows
}

// naIfEmpty returns "N/A" for an empty string, used as the fallback for GPU types
// and node lists.
func naIfEmpty(s string) string {
	if s == "" {
		return "N/A"
	}
	return s
}

// CapturesInput reports whether the active pane's filter bar is open, so the
// root routes raw keys (including r/p/e) into it instead of switching sub-tabs.
func (u *Users) CapturesInput() bool { return u.active().CapturesInput() }

// SelectedKey returns the username of the selected row on the active pane (the
// first column is always the user), or "" when empty. The root uses it to open a
// user-detail modal on Enter.
func (u *Users) SelectedKey() string { return u.active().SelectedKey() }

// reobserve refreshes the status tracker for the active sub-pane's section,
// called when the sub-pane changes without a data refresh.
func (u *Users) reobserve() {
	sec, hasData := u.activeSection()
	u.status.observe(u.store.State(sec), hasData)
}

// View renders the sub-tab header above the active pane, inserting a debounced
// spinner / error badge when the active pane's backing section is loading or
// failed and the pane has no rows yet.
func (u *Users) View() string {
	header := u.subtabHeader()
	sec, hasData := u.activeSection()
	if line, ok := u.status.statusLine(
		u.store.State(sec), hasData, u.store.SectionErr(sec), u.styles,
	); ok {
		return lipgloss.JoinVertical(lipgloss.Left, header, "", line, u.active().View())
	}
	return lipgloss.JoinVertical(lipgloss.Left, header, "", u.active().View())
}

// subtabHeader renders the "User Overview" header with the active sub-tab
// highlighted.
func (u *Users) subtabHeader() string {
	title := u.styles.Title.Render("User Overview")
	tabs := []string{
		u.subtabLabel("r", "Running", subtabRunning),
		u.subtabLabel("p", "Pending", subtabPending),
		u.subtabLabel("e", "Energy", subtabEnergy),
	}
	return lipgloss.JoinHorizontal(lipgloss.Top, append([]string{title, "  "}, tabs...)...)
}

// subtabLabel renders one sub-tab link, bold when active and dimmed otherwise.
func (u *Users) subtabLabel(keyHint, label string, tab userSubtab) string {
	text := keyHint + " " + label + "  "
	if u.activeSubtab == tab {
		return u.styles.TabActive.Render(text)
	}
	return u.styles.Subtle.Render(text)
}

// ShortHelp returns the active pane's bindings plus the sub-tab switch hints.
func (u *Users) ShortHelp() []key.Binding {
	return append(u.active().ShortHelp(), userSubtabBindings()...)
}

// FullHelp returns the active pane's bindings plus the sub-tab switch group.
func (u *Users) FullHelp() [][]key.Binding {
	return append(u.active().FullHelp(), userSubtabBindings())
}

// userSubtabBindings are the r/p/e sub-tab switch bindings shown in help.
func userSubtabBindings() []key.Binding {
	return []key.Binding{
		key.NewBinding(key.WithKeys("r"), key.WithHelp("r", "running")),
		key.NewBinding(key.WithKeys("p"), key.WithHelp("p", "pending")),
		key.NewBinding(key.WithKeys("e"), key.WithHelp("e", "energy")),
	}
}
