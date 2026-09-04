package tabs

import (
	"fmt"
	"sort"
	"strconv"
	"strings"

	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/table"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"

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

// activeUserColumns are the Active Users sub-tab columns: rank among users with
// recent usage, the association, the fair-share factor Slurm ranks on, and how
// the user's usage compares with their share.
var activeUserColumns = []column{
	{key: "rank", title: "Rank", width: 7},
	{key: "user", title: "User", width: 14},
	{key: "account", title: "Account", width: 12},
	{key: "fair_share", title: "FairShare", numeric: true, width: 9},
	{key: "share", title: "Share%", numeric: true, width: 7},
	{key: "usage", title: "Usage%", numeric: true, width: 7},
	{key: "ratio", title: "Usage/Share", numeric: true, width: 11},
	{key: "status", title: "Status", width: 19},
}

// accountColumns are the Accounts sub-tab columns: rank by how well served the
// account is, its share and usage, and how many of its users are active.
var accountColumns = []column{
	{key: "rank", title: "Rank", width: 7},
	{key: "account", title: "Account", width: 16},
	{key: "share", title: "Share%", numeric: true, width: 7},
	{key: "usage", title: "Usage%", numeric: true, width: 7},
	{key: "ratio", title: "Usage/Share", numeric: true, width: 11},
	{key: "status", title: "Status", width: 19},
	{key: "users", title: "Users", width: 9},
}

// jobColumnsPriority are the Jobs sub-tab columns: every pending job grouped by
// partition in queue order, with its position in that partition's queue, then
// every weighted sprio factor. The cluster-wide position is secondary because
// jobs only compete within their partition. JobID stays first: the table
// restores the cursor by first-column key.
var jobColumnsPriority = []column{
	{key: "job_id", title: "JobID", width: 10},
	{key: "partition", title: "Partition", width: 10},
	{key: "queue", title: "Queue", width: 8},
	{key: "user", title: "User", width: 12},
	{key: "account", title: "Account", width: 12},
	{key: "qos", title: "QOS", width: 8},
	{key: "priority", title: "Priority", numeric: true, width: 9},
	{key: "cluster", title: "Cluster-wide", width: 12},
	{key: "fair_share", title: "FairShare", numeric: true, width: 9},
	{key: "age", title: "Age", numeric: true, width: 6},
	{key: "job_size", title: "JobSize", numeric: true, width: 7},
	{key: "partition_prio", title: "PartPrio", numeric: true, width: 8},
	{key: "qos_prio", title: "QOSPrio", numeric: true, width: 7},
	{key: "tres", title: "TRES", numeric: true, width: 6},
	{key: "assoc", title: "Assoc", numeric: true, width: 6},
	{key: "site", title: "Site", numeric: true, width: 5},
	{key: "nice", title: "Nice", numeric: true, width: 5},
}

// myJobColumns are the current user's pending jobs on the My pane: where each
// job sits in its partition's queue and what its priority is made of.
var myJobColumns = []column{
	{key: "job_id", title: "JobID", width: 10},
	{key: "partition", title: "Partition", width: 10},
	{key: "queue", title: "Queue", width: 8},
	{key: "qos", title: "QOS", width: 8},
	{key: "priority", title: "Priority", numeric: true, width: 9},
	{key: "breakdown", title: "Breakdown", noSort: true},
}

// Column indexes shared by the row builders and the decorators that color them.
const (
	userFairShareCol = 3
	userStatusCol    = 7
	accountStatusCol = 5
)

// noteRows is the space reserved above the Active Users and Accounts tables for
// the active/hidden count line.
const noteRows = 1

// Priority is the priority-overview tab: a mini-root with four sub-panes (My /
// Active Users / Accounts / Jobs) switched on m/u/a/j. The My pane explains the
// current user's standing (fair-share rank, usage versus share, recovery time,
// the cluster's factor weights) above their pending jobs with queue positions.
// Active Users and Accounts rank sshare associations; Jobs lists every pending
// job in scheduler order with its weighted factors. Enter on a Users/Accounts row
// is handled by the root, which opens the corresponding detail modal.
type Priority struct {
	store    *store.Store
	styles   theme.Styles
	username string

	users    filterTable
	accounts filterTable
	jobs     filterTable
	myJobs   filterTable

	// summaryLines is the My pane block above the pending-jobs table, kept
	// unwrapped so layout can reflow it to the current width; summary is that
	// block rendered at the current width, and its height decides how much room
	// the table gets.
	summaryLines []summaryLine
	summary      string
	// usersNote and accountsNote are the active/hidden count lines above the
	// Active Users and Accounts tables.
	usersNote    string
	accountsNote string
	// landed records that the Active Users cursor has been placed on the current
	// user's row once, after which the user's own scrolling is left alone.
	landed bool

	status       sectionStatus
	activeSubtab prioritySubtab
	width        int
	height       int
}

// NewPriority returns a Priority tab bound to s for the given username.
func NewPriority(s *store.Store, styles theme.Styles, username string) *Priority {
	p := &Priority{store: s, styles: styles, username: username, status: newSectionStatus()}
	p.users = newFilterTable(activeUserColumns, styles, usageDecorator(userFairShareCol, userStatusCol))
	p.accounts = newFilterTable(accountColumns, styles, usageDecorator(-1, accountStatusCol))
	p.jobs = newFilterTable(jobColumnsPriority, styles, nil)
	p.myJobs = newFilterTable(myJobColumns, styles, nil)
	p.Refresh()
	return p
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

// SetStyles re-themes all panes and re-derives the colored rows and summary.
func (p *Priority) SetStyles(styles theme.Styles) {
	p.styles = styles
	p.users.SetStyles(styles)
	p.accounts.SetStyles(styles)
	p.jobs.SetStyles(styles)
	p.myJobs.SetStyles(styles)
	p.Refresh()
}

// SetSize records the area and lays out every pane (I7).
func (p *Priority) SetSize(width, height int) {
	p.width = width
	p.height = height
	p.layout()
}

// layout sizes every pane from the recorded area, reserving the sub-tab header,
// the Active Users note line, and (on the My pane) the rendered summary, so a
// longer summary never pushes the pending-jobs table off-screen. The summary is
// reflowed here rather than in Refresh so a resize re-wraps it too; until the
// root has sized the tab it is rendered unwrapped and the panes are left alone.
func (p *Priority) layout() {
	p.summary = renderSummary(p.summaryLines, p.width)
	if p.width == 0 && p.height == 0 {
		return
	}
	inner := max(p.height-subtabHeaderRows, 1)
	p.users.SetSize(p.width, max(inner-noteRows, 1))
	p.accounts.SetSize(p.width, max(inner-noteRows, 1))
	p.jobs.SetSize(p.width, inner)
	p.myJobs.SetSize(p.width, max(inner-lipgloss.Height(p.summary), 1))
}

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

// Refresh rebuilds all four panes plus the My pane summary from the store's
// fair-share, pending-priority, and priority-config data.
func (p *Priority) Refresh() {
	fs := p.store.FairShare
	ranked := store.RankActiveUsers(fs)
	me := store.FindRankedUser(ranked, p.username)
	assocs := store.UserAssociations(fs, p.username)
	queue := store.RankPending(p.store.PendingPrio)
	mine := store.UserPending(queue, p.username)

	myAccount := ""
	switch {
	case me != nil:
		myAccount = me.Entry.Account
	case len(assocs) > 0:
		myAccount = assocs[0].Account
	}

	p.users.SetRows(activeUserRows(ranked, p.username))
	p.usersNote = activeUsersNote(fs, len(ranked))
	rankedAccounts := store.RankAccounts(fs)
	p.accounts.SetRows(accountRows(rankedAccounts, fs, myAccount))
	p.accountsNote = activeAccountsNote(fs, len(rankedAccounts))
	p.jobs.SetRows(jobRows(queue, p.username))
	p.myJobs.SetRows(myJobRows(mine))
	p.summaryLines = p.buildSummary(me, assocs, mine)

	if !p.landed && p.username != "" {
		self := highlight(p.username)
		p.landed = p.users.SelectRow(func(row []string) bool { return row[1] == self })
	}
	p.layout()
	p.reobserve()
}

// mySections are the sections the My pane reads at once. It waits for all of
// them to complete a first fetch rather than rendering piecemeal as each lands,
// which would show a half-built summary that reflows three times.
var mySections = [...]store.Section{store.SectionFairShare, store.SectionPendingPrio, store.SectionPriorityConfig}

// myWaiting returns the first My-pane section that has never completed a fetch
// and true, or false once all of them have.
func (p *Priority) myWaiting() (store.Section, bool) {
	for _, sec := range mySections {
		if !p.store.Settled(sec) {
			return sec, true
		}
	}
	return 0, false
}

// activeSection returns the store section whose load state the active sub-pane
// should report and whether that pane already has data to show. Users/Accounts
// derive from fair-share and Jobs from pending-priority. The My pane reports
// whichever of its sections is still awaited, with no data, so the pane shows a
// single spinner until everything has landed; once settled, only a fair-share
// fetch that failed before ever delivering rows still surfaces as a status line.
func (p *Priority) activeSection() (store.Section, bool) {
	switch p.activeSubtab {
	case subtabJobs:
		return store.SectionPendingPrio, len(p.jobs.rows) > 0
	case subtabUsers:
		return store.SectionFairShare, len(p.users.rows) > 0
	case subtabAccounts:
		return store.SectionFairShare, len(p.accounts.rows) > 0
	default:
		if sec, waiting := p.myWaiting(); waiting {
			return sec, false
		}
		return store.SectionFairShare, len(p.store.FairShare) > 0 || p.store.State(store.SectionFairShare) == store.StateLoaded
	}
}

// reobserve refreshes the status tracker for the active sub-pane's section.
func (p *Priority) reobserve() {
	sec, hasData := p.activeSection()
	p.status.observe(p.store.State(sec), hasData)
}

// highlight marks a cell as belonging to the current user.
func highlight(cell string) string { return ">> " + cell }

// activeUserRows builds the Active Users pane rows from the ranked users,
// prefixing the current user's row with ">> ".
func activeUserRows(ranked []store.RankedShare, username string) [][]string {
	out := make([][]string, 0, len(ranked))
	for _, r := range ranked {
		e := r.Entry
		userCell := e.User
		if e.User == username && username != "" {
			userCell = highlight(e.User)
		}
		out = append(out, []string{
			fmt.Sprintf("%d/%d", r.Rank, r.Total),
			userCell,
			e.Account,
			fmt.Sprintf("%.4f", store.FairShareValue(e)),
			store.FormatPercent(e.NormShares),
			store.FormatPercent(e.EffectvUsage),
			store.FormatRatio(r.Ratio, r.RatioOK),
			r.Band.Label(),
		})
	}
	return out
}

// activeUsersNote summarizes how many users compete for the cluster and how
// many associations without recent usage the ranking hides.
func activeUsersNote(entries []store.FairShareEntry, active int) string {
	users := map[string]struct{}{}
	for _, e := range entries {
		if !e.IsAccount() {
			users[e.User] = struct{}{}
		}
	}
	note := plural(active, "active user", "active users")
	if hidden := len(users) - active; hidden > 0 {
		note += " · " + withCommas(int64(hidden)) + " without recent usage hidden"
	}
	return note
}

// activeAccountsNote summarizes how many accounts compete for the cluster and
// how many without a share or recent usage the ranking hides.
func activeAccountsNote(entries []store.FairShareEntry, active int) string {
	note := plural(active, "active account", "active accounts")
	if hidden := store.AccountCount(entries) - active; hidden > 0 {
		note += " · " + withCommas(int64(hidden)) + " without recent usage hidden"
	}
	return note
}

// accountRows builds the Accounts pane rows from the ranked accounts, counting
// each account's active and total users and prefixing the current user's account
// with ">> ".
func accountRows(ranked []store.RankedShare, entries []store.FairShareEntry, myAccount string) [][]string {
	type userCount struct{ active, total int }
	counts := map[string]userCount{}
	for _, e := range entries {
		if e.IsAccount() {
			continue
		}
		c := counts[e.Account]
		c.total++
		if ratio, ok := store.UsageRatio(e); ok && ratio > 0 {
			c.active++
		}
		counts[e.Account] = c
	}

	out := make([][]string, 0, len(ranked))
	for _, r := range ranked {
		e := r.Entry
		accountCell := e.Account
		if e.Account == myAccount && myAccount != "" {
			accountCell = highlight(e.Account)
		}
		c := counts[e.Account]
		out = append(out, []string{
			fmt.Sprintf("%d/%d", r.Rank, r.Total),
			accountCell,
			store.FormatPercent(e.NormShares),
			store.FormatPercent(e.EffectvUsage),
			store.FormatRatio(r.Ratio, r.RatioOK),
			r.Band.Label(),
			fmt.Sprintf("%d/%d", c.active, c.total),
		})
	}
	return out
}

// jobRows builds the Jobs pane rows grouped by partition in queue order,
// prefixing the current user's jobs with ">> ".
func jobRows(queue []store.RankedPriority, username string) [][]string {
	out := make([][]string, 0, len(queue))
	for _, r := range store.ByPartition(queue) {
		e := r.Entry
		userCell := e.User
		if e.User == username && username != "" {
			userCell = highlight(e.User)
		}
		f := e.Factors
		out = append(out, []string{
			e.JobID, e.Partition,
			store.FormatQueue(r.Pos.Partition, r.Pos.PartitionTotal),
			userCell, e.Account, e.QOS,
			strconv.FormatInt(e.Priority, 10),
			store.FormatQueue(r.Pos.Cluster, r.Pos.ClusterTotal),
			strconv.FormatInt(f.FairShare, 10),
			strconv.FormatInt(f.Age, 10),
			strconv.FormatInt(f.JobSize, 10),
			strconv.FormatInt(f.Partition, 10),
			strconv.FormatInt(f.QOS, 10),
			strconv.FormatInt(f.TRES, 10),
			strconv.FormatInt(f.Assoc, 10),
			strconv.FormatInt(f.Site, 10),
			strconv.FormatInt(f.Nice, 10),
		})
	}
	return out
}

// myJobRows builds the current user's pending-job rows for the My pane, grouped
// by partition in queue order.
func myJobRows(mine []store.RankedPriority) [][]string {
	out := make([][]string, 0, len(mine))
	for _, r := range store.ByPartition(mine) {
		e := r.Entry
		out = append(out, []string{
			e.JobID, e.Partition,
			store.FormatQueue(r.Pos.Partition, r.Pos.PartitionTotal),
			e.QOS,
			strconv.FormatInt(e.Priority, 10),
			store.FormatBreakdown(e.Factors),
		})
	}
	return out
}

// usageDecorator colors a row's status cell by its usage band and, when
// fairShareCol is non-negative, the fair-share cell in bold with the same color,
// so the two columns read as one judgement. Plain rows stay markup-free for
// filtering and numeric sorting.
func usageDecorator(fairShareCol, statusCol int) rowDecorator {
	return func(plain []string, styles theme.Styles) table.Row {
		row := make(table.Row, len(plain))
		copy(row, plain)
		if statusCol >= len(plain) || plain[statusCol] == "" {
			return row
		}
		style := styles.StateRoleStyle(usageRoleForLabel(plain[statusCol]))
		row[statusCol] = style.Render(plain[statusCol])
		if fairShareCol >= 0 && fairShareCol < len(plain) {
			row[fairShareCol] = style.Bold(true).Render(plain[fairShareCol])
		}
		return row
	}
}

// usageRoleForLabel maps a rendered usage-band label back to its color role, so
// a decorator can color a plain row from its own status cell.
func usageRoleForLabel(label string) string {
	for b := store.UsageUnknown; b <= store.UsageHeavy; b++ {
		if b.Label() == label {
			return b.Role()
		}
	}
	return ""
}

// summaryLine is one line of the My pane summary before wrapping: a leading
// indent, an optional aligned label, and the text that follows it. When the
// text is reflowed, continuation lines hang under the text column so the label
// alignment survives a narrow pane.
type summaryLine struct {
	indent int
	label  string
	text   string
}

// summaryLabelWidth is the label column of a labelled summary line.
const summaryLabelWidth = 18

// summaryMinWrap is the narrowest text column worth hanging under a label;
// below it the label alignment is given up so words still fit.
const summaryMinWrap = 24

// summaryRow is a labelled, indented summary line.
func summaryRow(label, text string) summaryLine {
	return summaryLine{indent: 2, label: label, text: text}
}

// summaryText is an indented summary line without a label.
func summaryText(text string) summaryLine {
	return summaryLine{indent: 2, text: text}
}

// renderSummary reflows the summary lines to width, wrapping each line's text
// at word boundaries (escape sequences are zero-width) and hanging continuation
// lines under the text's first glyph, so a label column or a padded title keeps
// its alignment. A zero width renders every line unwrapped.
func renderSummary(lines []summaryLine, width int) string {
	out := make([]string, 0, len(lines))
	for _, l := range lines {
		prefix := strings.Repeat(" ", l.indent)
		if l.label != "" {
			prefix += fmt.Sprintf("%-*s  ", summaryLabelWidth, l.label)
		}
		hang := lipgloss.Width(prefix)
		if width > 0 && width-hang < summaryMinWrap && l.label != "" {
			// Too narrow for the label column: put the label on its own line and
			// wrap the text under the plain indent instead.
			out = append(out, strings.Repeat(" ", l.indent)+l.label)
			prefix = strings.Repeat(" ", l.indent)
			hang = l.indent
		}
		plain := ansi.Strip(l.text)
		hang += len(plain) - len(strings.TrimLeft(plain, " "))
		text := l.text
		if width > 0 {
			text = ansi.Wrap(text, max(width-lipgloss.Width(prefix), 1), "")
		}
		for i, part := range strings.Split(text, "\n") {
			if i == 0 {
				out = append(out, prefix+part)
			} else {
				out = append(out, strings.Repeat(" ", hang)+part)
			}
		}
	}
	return strings.Join(out, "\n")
}

// buildSummary assembles the My pane block above the pending-jobs table: the
// user's fair-share standing, how the cluster computes priority, and the
// pending-jobs heading with the user's standing in each partition.
func (p *Priority) buildSummary(me *store.RankedShare, assocs []store.FairShareEntry, mine []store.RankedPriority) []summaryLine {
	var lines []summaryLine
	if fs := p.fairShareBlock(me, assocs); len(fs) > 0 {
		lines = append(append(lines, fs...), summaryLine{})
	}
	if cfg := p.configBlock(store.SumFactors(mine)); len(cfg) > 0 {
		lines = append(append(lines, cfg...), summaryLine{})
	}
	return append(lines, p.pendingLines(mine)...)
}

// fairShareBlock renders the user's standing: the fair-share factor with rank
// and status, usage against share, the recovery estimate, and any other
// accounts the user belongs to. A user with associations but no recent usage
// gets the Unused explanation; a user with none gets a note, but only once the
// fair-share section has actually loaded, so a slow first fetch shows the
// spinner rather than a misleading "no association" message.
func (p *Priority) fairShareBlock(me *store.RankedShare, assocs []store.FairShareEntry) []summaryLine {
	s := p.styles
	if me == nil && len(assocs) == 0 {
		if p.store.State(store.SectionFairShare) != store.StateLoaded {
			return nil
		}
		return []summaryLine{
			p.summaryTitle(""),
			summaryText(s.Subtle.Render(fmt.Sprintf("No fair-share association found for %q — this cluster may not use fair-share, "+
				"or you have never been granted an allocation.", p.username))),
		}
	}

	if me == nil {
		e := assocs[0]
		style := s.StateRoleStyle(store.UsageUnused.Role())
		lines := []summaryLine{
			p.summaryTitle(e.Account),
			summaryRow("Fair-share factor",
				style.Bold(true).Render(fairShareText(e))+"   "+
					style.Render("Unused — no recent usage, so your jobs start near the front of the queue")),
		}
		return append(lines, p.alsoInLines(assocs, e.Account)...)
	}

	e := me.Entry
	style := s.StateRoleStyle(me.Band.Role())
	lines := []summaryLine{
		p.summaryTitle(e.Account),
		summaryRow("Fair-share factor", fmt.Sprintf("%s   rank %s     %s",
			style.Bold(true).Render(fairShareText(e)),
			store.FormatRank(me.Rank, me.Total, "active users"),
			style.Render(me.Band.Label()))),
		summaryRow("Usage vs share", fmt.Sprintf("%s — %s of recent cluster usage on a %s share",
			store.FormatRatio(me.Ratio, me.RatioOK), store.FormatPercent(e.EffectvUsage), store.FormatPercent(e.NormShares))),
	}
	if p.store.State(store.SectionPriorityConfig) == store.StateLoaded {
		halfLife := p.store.PriorityConfig.DecayHalfLife
		if recovery, ok := store.RecoveryTime(me.Ratio, halfLife); ok {
			lines = append(lines, summaryRow("Recovery", fmt.Sprintf("usage halves every %s → ≈%s without jobs to reach 1×  %s",
				store.FormatDays(halfLife), store.FormatDays(recovery), s.Subtle.Render("(approx; assumes steady load)"))))
		}
	}
	return append(lines, p.alsoInLines(assocs, e.Account)...)
}

// alsoInLines lists the user's other associations (beyond the one shown) with
// their fair-share factors, or nothing for a single-account user.
func (p *Priority) alsoInLines(assocs []store.FairShareEntry, shown string) []summaryLine {
	if len(assocs) < 2 {
		return nil
	}
	others := make([]string, 0, len(assocs)-1)
	for _, a := range assocs {
		if a.Account != shown {
			others = append(others, fmt.Sprintf("%s (%s)", a.Account, fairShareText(a)))
		}
	}
	if len(others) == 0 {
		return nil
	}
	return []summaryLine{summaryText(p.styles.Subtle.Render("Also in: " + strings.Join(others, ", ")))}
}

// summaryTitle renders the "Your Priority — user · account" heading; the
// account is omitted when the user has none.
func (p *Priority) summaryTitle(account string) summaryLine {
	who := p.username
	if account != "" {
		who += " · " + account
	}
	return summaryLine{text: p.styles.Title.Render("Your Priority") + p.styles.Text.Render("— "+who)}
}

// configBlock explains how this cluster computes priority from the fetched
// configuration: the non-zero factor weights and, when the user has pending
// jobs, each factor's share of their total priority. A non-multifactor plugin
// gets a one-line FIFO explanation. The block is omitted while the config is
// unavailable (the pane waits for the first fetch; a failed one has already
// been reported by the root).
func (p *Priority) configBlock(factors store.PriorityFactors, total int64) []summaryLine {
	if p.store.State(store.SectionPriorityConfig) != store.StateLoaded {
		return nil
	}
	cfg := p.store.PriorityConfig
	title := summaryLine{text: p.styles.Title.Render("How priority is computed here")}
	if !cfg.Multifactor() {
		return []summaryLine{title,
			summaryText(fmt.Sprintf("Scheduler: %s — jobs start in submission order; fair-share does not apply.", cfg.Type))}
	}
	lines := []summaryLine{title, summaryText(weightsText(cfg))}
	if total > 0 {
		lines = append(lines, summaryText("Your jobs: "+factorSharesText(factors, total)))
	}
	return lines
}

// weightsText lists the non-zero factor weights largest first, annotating Age
// with the queue time at which it maxes out and appending the per-resource TRES
// weights verbatim.
func weightsText(cfg store.PriorityConfig) string {
	w := cfg.Weights
	weights := []store.PriorityFactor{
		{Name: "FairShare", Value: w.FairShare}, {Name: "Age", Value: w.Age},
		{Name: "JobSize", Value: w.JobSize}, {Name: "Partition", Value: w.Partition},
		{Name: "QOS", Value: w.QOS}, {Name: "Assoc", Value: w.Assoc},
	}
	nonZero := weights[:0]
	for _, f := range weights {
		if f.Value != 0 {
			nonZero = append(nonZero, f)
		}
	}
	sort.SliceStable(nonZero, func(i, j int) bool { return nonZero[i].Value > nonZero[j].Value })

	parts := make([]string, 0, len(nonZero)+1)
	for _, f := range nonZero {
		part := f.Name + " ×" + withCommas(f.Value)
		if f.Name == "Age" && cfg.MaxAge > 0 {
			part += " (maxes after " + store.FormatDays(cfg.MaxAge) + ")"
		}
		parts = append(parts, part)
	}
	if w.TRES != "" {
		parts = append(parts, "TRES "+w.TRES)
	}
	if len(parts) == 0 {
		return "No factor weights are configured."
	}
	return strings.Join(parts, " · ")
}

// factorSharesText expresses each non-zero summed factor as a percentage of the
// user's total pending priority, largest first.
func factorSharesText(factors store.PriorityFactors, total int64) string {
	contributions := factors.Contributions()
	parts := make([]string, 0, len(contributions))
	for _, c := range contributions {
		parts = append(parts, fmt.Sprintf("%.2f%% %s", 100*float64(c.Value)/float64(total), c.Name))
	}
	return strings.Join(parts, " · ")
}

// pendingLines renders the pending-jobs heading with the count and, for each
// partition the user is queued in, where their best job sits in that
// partition's queue and how many jobs are ahead of it. Jobs only compete within
// their partition, so this is the number that predicts when one starts.
func (p *Priority) pendingLines(mine []store.RankedPriority) []summaryLine {
	lines := []summaryLine{{text: p.styles.Title.Render(fmt.Sprintf("Your Pending Jobs (%d)", len(mine)))}}
	for _, s := range store.PartitionStandings(mine) {
		lines = append(lines, summaryRow(s.Partition, store.FormatStanding(s)))
	}
	return lines
}

// fairShareText formats the sshare fair-share factor with four decimals.
func fairShareText(e store.FairShareEntry) string {
	return fmt.Sprintf("%.4f", store.FairShareValue(e))
}

// withCommas formats an integer with thousands separators ("10,000,000").
func withCommas(v int64) string {
	digits := strconv.FormatInt(v, 10)
	sign := ""
	if digits[0] == '-' {
		sign, digits = "-", digits[1:]
	}
	var b strings.Builder
	b.Grow(len(digits) + len(digits)/3)
	for i, r := range digits {
		if i > 0 && (len(digits)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(r)
	}
	return sign + b.String()
}

// plural renders a count with the singular or plural noun.
func plural(n int, singular, pluralNoun string) string {
	if n == 1 {
		return "1 " + singular
	}
	return withCommas(int64(n)) + " " + pluralNoun
}

// CapturesInput reports whether the active pane's filter bar is open.
func (p *Priority) CapturesInput() bool { return p.activePane().CapturesInput() }

// PriorityDetailKind identifies which detail modal the selected Priority row maps
// to: a user, an account, or none (the My and Jobs panes have no row detail).
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

// View renders the sub-tab header, then the active pane. A status line (spinner
// or error badge) stands in for a pane whose backing section has not delivered
// data. The My pane shows only that line until every section it reads has
// completed a first fetch, then the whole summary at once; afterwards a
// fair-share fetch that failed without ever delivering rows keeps an error line
// above whatever the other sections can still say.
func (p *Priority) View() string {
	header := p.subtabHeader()
	sec, hasData := p.activeSection()
	line, showLine := p.status.statusLine(p.store.State(sec), hasData, p.store.SectionErr(sec), p.styles)

	switch p.activeSubtab {
	case subtabMine:
		if _, waiting := p.myWaiting(); waiting {
			return lipgloss.JoinVertical(lipgloss.Left, header, "", line)
		}
		parts := []string{header, ""}
		if showLine {
			parts = append(parts, line)
		}
		return lipgloss.JoinVertical(lipgloss.Left, append(parts, p.summary, p.myJobs.View())...)
	case subtabUsers:
		return p.notedPane(header, line, showLine, p.usersNote, p.users.View())
	case subtabAccounts:
		return p.notedPane(header, line, showLine, p.accountsNote, p.accounts.View())
	default:
		if showLine {
			return lipgloss.JoinVertical(lipgloss.Left, header, "", line, p.activePane().View())
		}
		return lipgloss.JoinVertical(lipgloss.Left, header, "", p.activePane().View())
	}
}

// notedPane renders a ranked pane with its active/hidden count line, which the
// loading/error status line replaces while there is nothing to count.
func (p *Priority) notedPane(header, line string, showLine bool, note, table string) string {
	if showLine {
		return lipgloss.JoinVertical(lipgloss.Left, header, "", line, table)
	}
	return lipgloss.JoinVertical(lipgloss.Left, header, "", p.styles.Subtle.Render(note), table)
}

// subtabHeader renders the Priority header with the active sub-tab highlighted.
func (p *Priority) subtabHeader() string {
	title := p.styles.Title.Render("Priority")
	tabs := []string{
		p.subtabLabel("m", "My Priority", subtabMine),
		p.subtabLabel("u", "Active Users", subtabUsers),
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

// prioritySubtabBindings are the m/u/a/j sub-tab switch bindings shown in help.
func prioritySubtabBindings() []key.Binding {
	return []key.Binding{
		key.NewBinding(key.WithKeys("m"), key.WithHelp("m", "mine")),
		key.NewBinding(key.WithKeys("u"), key.WithHelp("u", "users")),
		key.NewBinding(key.WithKeys("a"), key.WithHelp("a", "accounts")),
		key.NewBinding(key.WithKeys("j"), key.WithHelp("j", "jobs")),
	}
}
