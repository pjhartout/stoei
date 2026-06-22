package tabs

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"

	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// prioritySubtab identifies the active Priority sub-pane.
type prioritySubtab int

const (
	subtabMine prioritySubtab = iota
	subtabUsers
	subtabAccounts
	subtabJobs
)

// Fair-share thresholds for color coding and status labels. The values live in
// store so the Priority tab and the detail modals share one source of truth.
const (
	fairShareSuccessThreshold = store.FairShareSuccessThreshold
	fairShareWarningThreshold = store.FairShareWarningThreshold
)

// userPriorityColumns are the All Users sub-tab columns: rank, user, account, and
// the sshare fair-share factors, ending with a derived status label.
var userPriorityColumns = []column{
	{key: "rank", title: "Rank", width: 6},
	{key: "user", title: "User", width: 14},
	{key: "account", title: "Account", width: 12},
	{key: "raw_shares", title: "RawShares", numeric: true, width: 9},
	{key: "norm_shares", title: "NormShares", numeric: true, width: 10},
	{key: "raw_usage", title: "RawUsage", numeric: true, width: 9},
	{key: "effective_usage", title: "EffectvUsage", numeric: true, width: 12},
	{key: "fair_share", title: "FairShare", numeric: true, width: 9},
	{key: "status", title: "Status", width: 12},
}

// accountPriorityColumns are the Accounts sub-tab columns: rank, account, and the
// sshare fair-share factors, ending with a derived status label.
var accountPriorityColumns = []column{
	{key: "rank", title: "Rank", width: 6},
	{key: "account", title: "Account", width: 16},
	{key: "raw_shares", title: "RawShares", numeric: true, width: 10},
	{key: "norm_shares", title: "NormShares", numeric: true, width: 10},
	{key: "raw_usage", title: "RawUsage", numeric: true, width: 10},
	{key: "effective_usage", title: "EffectvUsage", numeric: true, width: 12},
	{key: "fair_share", title: "FairShare", numeric: true, width: 9},
	{key: "status", title: "Status", width: 12},
}

// jobPriorityColumns are the Jobs sub-tab columns: the pending-job sprio factors
// (job id, user, account, priority, age, fair share, job size, partition, QOS).
var jobPriorityColumns = []column{
	{key: "job_id", title: "JobID", width: 12},
	{key: "user", title: "User", width: 12},
	{key: "account", title: "Account", width: 10},
	{key: "priority", title: "Priority", numeric: true, width: 10},
	{key: "age", title: "Age", numeric: true, width: 8},
	{key: "fair_share", title: "FairShare", numeric: true, width: 9},
	{key: "job_size", title: "JobSize", numeric: true, width: 8},
	{key: "partition", title: "Partition", width: 10},
	{key: "qos", title: "QOS", width: 8},
}

// Priority is the priority-overview tab. It is a two-level mini-root with four
// sub-panes (My / Users / Accounts / Jobs) switched on m/u/a/j. The My pane
// shows a summary line for the current user and their pending jobs; Users and
// Accounts show per-user / per-account sshare with dense ranks; Jobs shows
// pending sprio factors. The current user's and account's rows are highlighted.
// Account-detail modals are deferred to Phase 5.
type Priority struct {
	store    *store.Store
	styles   theme.Styles
	username string

	users    filterTable
	accounts filterTable
	jobs     filterTable
	myJobs   filterTable

	// myAccount is the current user's account, resolved on Refresh from the
	// sshare data; it drives account-row highlighting.
	myAccount string
	summary   string

	status       sectionStatus
	activeSubtab prioritySubtab
	width        int
	height       int
}

// NewPriority returns a Priority tab bound to s for the given username.
func NewPriority(s *store.Store, styles theme.Styles, username string) *Priority {
	p := &Priority{store: s, styles: styles, username: username, status: newSectionStatus()}
	p.users = newFilterTable(userPriorityColumns, styles, nil)
	p.accounts = newFilterTable(accountPriorityColumns, styles, nil)
	p.jobs = newFilterTable(jobPriorityColumns, styles, nil)
	p.myJobs = newFilterTable(myJobPriorityColumns, styles, nil)
	p.Refresh()
	return p
}

// myJobPriorityColumns are the current user's pending-job columns shown on the My
// pane (the job sprio factors without the user/account columns).
var myJobPriorityColumns = []column{
	{key: "job_id", title: "JobID"},
	{key: "priority", title: "Priority", numeric: true},
	{key: "age", title: "Age", numeric: true},
	{key: "fair_share", title: "FairShare", numeric: true},
	{key: "job_size", title: "JobSize", numeric: true},
	{key: "partition", title: "Partition"},
	{key: "qos", title: "QOS"},
}

// activePane returns a pointer to the currently active sub-pane table. The My
// pane's table is its pending-jobs list.
func (p *Priority) activePane() *filterTable {
	switch p.activeSubtab {
	case subtabUsers:
		return &p.users
	case subtabAccounts:
		return &p.accounts
	case subtabJobs:
		return &p.jobs
	default:
		return &p.myJobs
	}
}

// SetKeyMode switches every sub-pane's filter/sort bindings to the given preset.
func (p *Priority) SetKeyMode(mode string) {
	p.users.SetKeyMode(mode)
	p.accounts.SetKeyMode(mode)
	p.jobs.SetKeyMode(mode)
	p.myJobs.SetKeyMode(mode)
}

// SetStyles re-themes all panes and re-derives the colored rows.
func (p *Priority) SetStyles(styles theme.Styles) {
	p.styles = styles
	p.users.SetStyles(styles)
	p.accounts.SetStyles(styles)
	p.jobs.SetStyles(styles)
	p.myJobs.SetStyles(styles)
	p.Refresh()
}

// SetSize sizes every pane, reserving space for the header and (on the My pane)
// the summary block (I7).
func (p *Priority) SetSize(width, height int) {
	p.width = width
	p.height = height
	inner := height - subtabHeaderRows
	if inner < 1 {
		inner = 1
	}
	p.users.SetSize(width, inner)
	p.accounts.SetSize(width, inner)
	p.jobs.SetSize(width, inner)

	myInner := inner - prioritySummaryRows
	if myInner < 1 {
		myInner = 1
	}
	p.myJobs.SetSize(width, myInner)
}

// prioritySummaryRows is the space reserved for the My-Priority summary block.
const prioritySummaryRows = 9

// Update routes m/u/a/j to a sub-tab switch, otherwise forwards to the active
// pane.
func (p *Priority) Update(msg tea.Msg) (*Priority, tea.Cmd) {
	if km, ok := msg.(tea.KeyPressMsg); ok && !p.activePane().CapturesInput() {
		switch km.String() {
		case "m":
			p.activeSubtab = subtabMine
			p.reobserve()
			return p, nil
		case "u":
			p.activeSubtab = subtabUsers
			p.reobserve()
			return p, nil
		case "a":
			p.activeSubtab = subtabAccounts
			p.reobserve()
			return p, nil
		case "j":
			p.activeSubtab = subtabJobs
			p.reobserve()
			return p, nil
		}
	}
	cmd := p.activePane().Update(msg)
	return p, cmd
}

// userPriorityRow is one ranked sshare user row used internally before display.
type userPriorityRow struct {
	rank    string
	user    string
	account string
	entry   store.FairShareEntry
}

// Refresh rebuilds all four panes plus the My-Priority summary from the store's
// fair-share and pending-priority data.
func (p *Priority) Refresh() {
	users, accounts := splitFairShare(p.store.FairShare)
	rankedUsers := rankUsers(users)
	rankedAccounts := rankAccounts(accounts)
	p.myAccount = accountFor(rankedUsers, p.username)

	p.users.SetRows(userPriorityRows(rankedUsers, p.username, p.styles))
	p.accounts.SetRows(accountPriorityRows(rankedAccounts, p.myAccount, p.styles))
	p.jobs.SetRows(jobPriorityRows(p.store.PendingPrio, p.username, p.styles))
	p.myJobs.SetRows(myJobRows(p.store.PendingPrio, p.username))
	p.summary = p.buildSummary(rankedUsers, rankedAccounts)
	p.reobserve()
}

// activeSection returns the store section backing the active sub-pane and whether
// that pane currently has rows. The My/Users/Accounts panes derive from the
// fair-share section; the Jobs pane derives from the pending-priority section.
func (p *Priority) activeSection() (store.Section, bool) {
	switch p.activeSubtab {
	case subtabJobs:
		return store.SectionPendingPrio, len(p.jobs.rows) > 0
	case subtabUsers:
		return store.SectionFairShare, len(p.users.rows) > 0
	case subtabAccounts:
		return store.SectionFairShare, len(p.accounts.rows) > 0
	default:
		return store.SectionFairShare, len(p.myJobs.rows) > 0 || p.summary != ""
	}
}

// reobserve refreshes the status tracker for the active sub-pane's section.
func (p *Priority) reobserve() {
	sec, hasData := p.activeSection()
	p.status.observe(p.store.State(sec), hasData)
}

// splitFairShare splits sshare entries into user-level and account-level rows
// using each entry's IsAccount flag.
func splitFairShare(entries []store.FairShareEntry) (users, accounts []store.FairShareEntry) {
	for _, e := range entries {
		if e.IsAccount() {
			accounts = append(accounts, e)
		} else {
			users = append(users, e)
		}
	}
	return users, accounts
}

// rankUsers sorts users by FairShare descending and assigns dense ranks (tied
// values share a rank).
func rankUsers(users []store.FairShareEntry) []userPriorityRow {
	sorted := make([]store.FairShareEntry, len(users))
	copy(sorted, users)
	sort.SliceStable(sorted, func(i, j int) bool {
		return safeFloat(sorted[i].FairShare) > safeFloat(sorted[j].FairShare)
	})
	ranks := denseRanks(fairShareValues(sorted))
	out := make([]userPriorityRow, len(sorted))
	for i, e := range sorted {
		out[i] = userPriorityRow{rank: ranks[i], user: e.User, account: e.Account, entry: e}
	}
	return out
}

// rankAccounts sorts accounts by FairShare descending and assigns dense ranks.
func rankAccounts(accounts []store.FairShareEntry) []userPriorityRow {
	sorted := make([]store.FairShareEntry, len(accounts))
	copy(sorted, accounts)
	sort.SliceStable(sorted, func(i, j int) bool {
		return safeFloat(sorted[i].FairShare) > safeFloat(sorted[j].FairShare)
	})
	ranks := denseRanks(fairShareValues(sorted))
	out := make([]userPriorityRow, len(sorted))
	for i, e := range sorted {
		out[i] = userPriorityRow{rank: ranks[i], account: e.Account, entry: e}
	}
	return out
}

// fairShareValues extracts the FairShare floats in order, for ranking.
func fairShareValues(entries []store.FairShareEntry) []float64 {
	out := make([]float64, len(entries))
	for i, e := range entries {
		out[i] = safeFloat(e.FairShare)
	}
	return out
}

// accountFor returns the account of the named user from the ranked user rows.
func accountFor(rows []userPriorityRow, username string) string {
	for _, r := range rows {
		if r.user == username {
			return r.account
		}
	}
	return ""
}

// userPriorityRows builds the All Users pane rows, prefixing the current user's
// row with ">> " to highlight it.
func userPriorityRows(rows []userPriorityRow, username string, styles theme.Styles) [][]string {
	out := make([][]string, 0, len(rows))
	for _, r := range rows {
		e := r.entry
		userCell := e.User
		if r.user == username && username != "" {
			userCell = ">> " + e.User
		}
		out = append(out, []string{
			r.rank,
			userCell,
			e.Account,
			e.RawShares,
			e.NormShares,
			e.RawUsage,
			e.EffectvUsage,
			fairShareCell(e.FairShare, styles),
			fairShareStatus(e.FairShare),
		})
	}
	return out
}

// accountPriorityRows builds the Accounts pane rows, prefixing the current user's
// account row with ">> " to highlight it.
func accountPriorityRows(rows []userPriorityRow, myAccount string, styles theme.Styles) [][]string {
	out := make([][]string, 0, len(rows))
	for _, r := range rows {
		e := r.entry
		accountCell := e.Account
		if e.Account == myAccount && myAccount != "" {
			accountCell = ">> " + e.Account
		}
		out = append(out, []string{
			r.rank,
			accountCell,
			e.RawShares,
			e.NormShares,
			e.RawUsage,
			e.EffectvUsage,
			fairShareCell(e.FairShare, styles),
			fairShareStatus(e.FairShare),
		})
	}
	return out
}

// jobPriorityRows builds the Jobs pane rows, sorted by priority descending and
// prefixing the current user's jobs with ">> ".
func jobPriorityRows(entries []store.PriorityEntry, username string, styles theme.Styles) [][]string {
	sorted := make([]store.PriorityEntry, len(entries))
	copy(sorted, entries)
	sort.SliceStable(sorted, func(i, j int) bool {
		return safeFloat(sorted[i].Priority) > safeFloat(sorted[j].Priority)
	})

	out := make([][]string, 0, len(sorted))
	for _, e := range sorted {
		userCell := e.User
		if e.User == username && username != "" {
			userCell = ">> " + e.User
		}
		row := []string{
			e.JobID, userCell, e.Account, e.Priority,
			e.Age, e.FairShare, e.JobSize, e.Partition, e.QOS,
		}
		out = append(out, row)
	}
	return out
}

// myJobRows builds the current user's pending-job rows for the My pane, sorted by
// priority descending.
func myJobRows(entries []store.PriorityEntry, username string) [][]string {
	mine := make([]store.PriorityEntry, 0)
	for _, e := range entries {
		if e.User == username {
			mine = append(mine, e)
		}
	}
	sort.SliceStable(mine, func(i, j int) bool {
		return safeFloat(mine[i].Priority) > safeFloat(mine[j].Priority)
	})
	out := make([][]string, 0, len(mine))
	for _, e := range mine {
		out = append(out, []string{
			e.JobID, e.Priority, e.Age, e.FairShare, e.JobSize, e.Partition, e.QOS,
		})
	}
	return out
}

// buildSummary renders the My-Priority summary block (fair share, status, user
// and account ranks, shares, and pending-job count) for the current user, or an
// explanatory note when the user has no fair-share data.
func (p *Priority) buildSummary(users, accounts []userPriorityRow) string {
	var mine *userPriorityRow
	for i := range users {
		if users[i].user == p.username {
			mine = &users[i]
			break
		}
	}
	if mine == nil {
		return p.styles.Subtle.Render(fmt.Sprintf(
			"No fair-share data found for %q. This may occur if you have not submitted jobs recently "+
				"or if fair-share is not configured on this cluster.", p.username))
	}

	e := mine.entry
	status := fairShareStatus(e.FairShare)
	rank := mine.rank
	if rank == "" {
		rank = "?"
	}

	accountRank := "?"
	for _, a := range accounts {
		if a.account == mine.account {
			accountRank = a.rank
			break
		}
	}

	pending := 0
	for _, j := range p.store.PendingPrio {
		if j.User == p.username {
			pending++
		}
	}

	fsStyle := fairShareStyle(e.FairShare, p.styles)
	lines := []string{
		p.styles.Title.Render("Your Priority"),
		"",
		"  FairShare: " + fsStyle.Render(e.FairShare) +
			"   Status: " + fsStyle.Render(status) +
			"   Rank: " + p.styles.Text.Bold(true).Render(rank),
		"  Account: " + p.styles.Text.Bold(true).Render(mine.account) +
			"   Account Rank: " + p.styles.Text.Bold(true).Render(accountRank),
		fmt.Sprintf("  Shares: %s (%s of cluster)", e.RawShares, e.NormShares),
		"",
		"  Pending Jobs: " + p.styles.Text.Bold(true).Render(strconv.Itoa(pending)),
	}
	return lipgloss.JoinVertical(lipgloss.Left, lines...)
}

// fairShareStyle returns the style for a fair-share value: green at/above the
// success threshold, yellow at/above the warning threshold, red below it.
func fairShareStyle(fairShare string, styles theme.Styles) lipgloss.Style {
	v, ok := parseFloat(fairShare)
	if !ok {
		return styles.Text
	}
	switch {
	case v >= fairShareSuccessThreshold:
		return styles.Success
	case v >= fairShareWarningThreshold:
		return styles.Warning
	default:
		return styles.Error
	}
}

// fairShareCell renders a bold, colored FairShare cell, passing through an
// empty value unchanged.
func fairShareCell(fairShare string, styles theme.Styles) string {
	if strings.TrimSpace(fairShare) == "" {
		return fairShare
	}
	return fairShareStyle(fairShare, styles).Bold(true).Render(fairShare)
}

// fairShareStatus returns the status label for a fair-share value:
// "Under-served", "Fair", or "Over-served" by descending threshold, or "" when
// the value does not parse.
func fairShareStatus(fairShare string) string {
	v, ok := parseFloat(fairShare)
	if !ok {
		return ""
	}
	switch {
	case v >= fairShareSuccessThreshold:
		return "Under-served"
	case v >= fairShareWarningThreshold:
		return "Fair"
	default:
		return "Over-served"
	}
}

// denseRanks assigns dense "rank/total" labels to a descending-sorted value list,
// with tied values sharing a rank.
func denseRanks(values []float64) []string {
	total := len(values)
	if total == 0 {
		return nil
	}
	out := make([]string, total)
	rank := 0
	first := true
	var prev float64
	for i, v := range values {
		if first || v != prev {
			rank++
		}
		out[i] = fmt.Sprintf("%d/%d", rank, total)
		prev = v
		first = false
	}
	return out
}

// safeFloat parses a float, returning 0 on failure, for use as a sort key.
func safeFloat(s string) float64 {
	if v, ok := parseFloat(s); ok {
		return v
	}
	return 0
}

// parseFloat parses a float and reports success; NaN-producing inputs report
// false so callers can treat them as "no value".
func parseFloat(s string) (float64, bool) {
	v, err := strconv.ParseFloat(strings.TrimSpace(s), 64)
	if err != nil || math.IsNaN(v) {
		return 0, false
	}
	return v, true
}

// CapturesInput reports whether the active pane's filter bar is open.
func (p *Priority) CapturesInput() bool { return p.activePane().CapturesInput() }

// PriorityDetailKind identifies which detail modal the selected Priority row maps
// to: a user, an account, a job, or none (the My pane has no row detail).
type PriorityDetailKind int

const (
	// PriorityDetailNone means the active pane has no Enter-detail.
	PriorityDetailNone PriorityDetailKind = iota
	// PriorityDetailUser opens a user-detail modal.
	PriorityDetailUser
	// PriorityDetailAccount opens an account-detail modal.
	PriorityDetailAccount
)

// SelectedDetail reports the detail target for the selected row on the active
// pane: the Users pane maps to a user (column 1, after the rank), the Accounts
// pane to an account (column 1). The Jobs and My panes have no row-detail, so
// they report PriorityDetailNone. The ">> " current-user/account highlight prefix
// is stripped.
func (p *Priority) SelectedDetail() (PriorityDetailKind, string) {
	switch p.activeSubtab {
	case subtabUsers:
		return PriorityDetailUser, stripHighlightPrefix(p.users.SelectedCell(1))
	case subtabAccounts:
		return PriorityDetailAccount, stripHighlightPrefix(p.accounts.SelectedCell(1))
	default:
		return PriorityDetailNone, ""
	}
}

// stripHighlightPrefix removes the ">> " current-row marker added by the
// priority row builders.
func stripHighlightPrefix(s string) string {
	return strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(s), ">>"))
}

// View renders the sub-tab header, then either the My-Priority summary plus the
// user's pending jobs, or the active pane.
func (p *Priority) View() string {
	header := p.subtabHeader()
	if p.activeSubtab == subtabMine {
		return lipgloss.JoinVertical(lipgloss.Left,
			header, "",
			p.summary, "",
			p.styles.Title.Render("Your Pending Jobs"),
			p.myJobs.View(),
		)
	}
	sec, hasData := p.activeSection()
	if line, ok := p.status.statusLine(
		p.store.State(sec), hasData, p.store.SectionErr(sec), p.styles,
	); ok {
		return lipgloss.JoinVertical(lipgloss.Left, header, "", line, p.activePane().View())
	}
	return lipgloss.JoinVertical(lipgloss.Left, header, "", p.activePane().View())
}

// subtabHeader renders the Priority header with the active sub-tab highlighted.
func (p *Priority) subtabHeader() string {
	title := p.styles.Title.Render("Priority")
	tabs := []string{
		p.subtabLabel("m", "My Priority", subtabMine),
		p.subtabLabel("u", "All Users", subtabUsers),
		p.subtabLabel("a", "Accounts", subtabAccounts),
		p.subtabLabel("j", "Jobs", subtabJobs),
	}
	return lipgloss.JoinHorizontal(lipgloss.Top, append([]string{title, "  "}, tabs...)...)
}

// subtabLabel renders one Priority sub-tab link.
func (p *Priority) subtabLabel(keyHint, label string, tab prioritySubtab) string {
	text := keyHint + " " + label + "  "
	if p.activeSubtab == tab {
		return p.styles.TabActive.Render(text)
	}
	return p.styles.Subtle.Render(text)
}

// ShortHelp returns the active pane's bindings plus the sub-tab switch hints.
func (p *Priority) ShortHelp() []key.Binding {
	return append(p.activePane().ShortHelp(), prioritySubtabBindings()...)
}

// FullHelp returns the active pane's bindings plus the sub-tab switch group.
func (p *Priority) FullHelp() [][]key.Binding {
	return append(p.activePane().FullHelp(), prioritySubtabBindings())
}

// prioritySubtabBindings are the m/u/a/j sub-tab switch bindings shown in help.
func prioritySubtabBindings() []key.Binding {
	return []key.Binding{
		key.NewBinding(key.WithKeys("m"), key.WithHelp("m", "mine")),
		key.NewBinding(key.WithKeys("u"), key.WithHelp("u", "users")),
		key.NewBinding(key.WithKeys("a"), key.WithHelp("a", "accounts")),
		key.NewBinding(key.WithKeys("j"), key.WithHelp("j", "jobs")),
	}
}
