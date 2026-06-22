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

// runningUserColumns are the Running sub-tab columns. Ports
// UserOverviewTab.RUNNING_USERS_COLUMNS.
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

// pendingUserColumns are the Pending sub-tab columns. Ports
// UserOverviewTab.PENDING_USERS_COLUMNS.
var pendingUserColumns = []column{
	{key: "user", title: "User"},
	{key: "pending_jobs", title: "Pending Jobs", numeric: true},
	{key: "cpus", title: "CPUs Requested", numeric: true},
	{key: "memory", title: "Memory (GB)", numeric: true},
	{key: "gpus", title: "GPUs Requested", numeric: true},
	{key: "gpu_types", title: "GPU Types"},
}

// energyUserColumns are the Energy sub-tab columns. Ports
// UserOverviewTab.ENERGY_USERS_COLUMNS.
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
// store aggregation (running/pending per-user stats, energy stats), matching
// UserOverviewTab. Enter→user-detail modal is deferred to Phase 5.
type Users struct {
	store        *store.Store
	styles       theme.Styles
	energyMonths int

	running filterTable
	pending filterTable
	energy  filterTable

	activeSubtab userSubtab
	width        int
	height       int
}

// NewUsers returns a Users tab bound to s. energyMonths labels the energy pane.
func NewUsers(s *store.Store, styles theme.Styles, energyMonths int) *Users {
	u := &Users{store: s, styles: styles, energyMonths: energyMonths}
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
			return u, nil
		case "p":
			u.activeSubtab = subtabPending
			return u, nil
		case "e":
			u.activeSubtab = subtabEnergy
			return u, nil
		}
	}
	cmd := u.active().Update(msg)
	return u, cmd
}

// Refresh rebuilds all three panes from the store aggregations.
func (u *Users) Refresh() {
	u.running.SetRows(runningUserRows(u.store.RunningUserStats()))
	u.pending.SetRows(pendingUserRows(u.store.PendingUserStats()))
	u.energy.SetRows(energyUserRows(u.store.EnergyStats()))
}

// runningUserRows builds the Running pane rows, sorted by total CPUs descending
// to surface the heaviest users first. Ports UserOverviewTab.update_users.
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
// stats by requested CPUs descending. Ports
// UserOverviewTab.update_pending_users.
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
// stats by total energy descending. Ports UserOverviewTab.update_energy_users.
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

// naIfEmpty returns "N/A" for an empty string, matching the Python "N/A"
// fallbacks used for GPU types and node lists.
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

// View renders the sub-tab header above the active pane.
func (u *Users) View() string {
	header := u.subtabHeader()
	return lipgloss.JoinVertical(lipgloss.Left, header, "", u.active().View())
}

// subtabHeader renders the "User Overview" header with the active sub-tab
// highlighted, porting UserOverviewTab._update_subtab_header.
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
