package modals

import (
	"fmt"
	"sort"
	"strings"

	"github.com/charmbracelet/x/ansi"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// These caps limit how many rows each list section of the user/account detail
// blocks renders before collapsing the remainder into an "... and N more" line.
const (
	maxUserPriorityJobs    = 10
	maxAccountUsers        = 15
	maxAccountRunningJobs  = 20
	maxAccountPriorityJobs = 15
)

// summaryLine renders one "Label.......... value" summary row.
func summaryLine(label, value string, styles theme.Styles) string {
	return "  " + styles.Subtle.Render(dottedLabel(label, labelWidth)) + " " + value
}

// formatUserInfo renders a user-detail block from the store's already-fetched
// data, in this section order: a user summary, jobs-by-state, pending resources,
// fair-share priority, pending job priorities, and a job list. The job rows come
// from the all-users list filtered to this user.
func formatUserInfo(username string, st *store.Store, styles theme.Styles) string {
	jobs := userJobs(st, username)
	userStats, ok := store.FindUserStats(store.AggregateUserStats(jobs, store.NodeGPUModels(st.Nodes)), username)
	if !ok {
		userStats = store.UserStats{Username: username}
	}
	pending := findPendingStats(st.PendingUserStats(), username)
	ranked := store.RankActiveUsers(st.FairShare)
	me := store.FindRankedUser(ranked, username)
	assocs := store.UserAssociations(st.FairShare, username)
	prios := store.UserPending(store.RankPending(st.PendingPrio), username)

	var lines []string

	lines = append(lines, styles.Title.Render(" User Summary "))
	lines = append(lines, summaryLine("Username", styles.Text.Bold(true).Render(username), styles))
	lines = append(lines, summaryLine("Running Jobs", styles.Text.Bold(true).Render(fmtInt(userStats.JobCount)), styles))
	lines = append(lines, summaryLine("Total CPUs", fmtInt(userStats.TotalCPUs), styles))
	lines = append(lines, summaryLine("Total Memory (GB)", fmt.Sprintf("%.1f", userStats.TotalMemoryGB), styles))
	lines = append(lines, summaryLine("Total GPUs", fmtInt(userStats.TotalGPUs), styles))
	if userStats.GPUTypes != "" {
		lines = append(lines, summaryLine("GPU Types", styles.Success.Render(userStats.GPUTypes), styles))
	}
	lines = append(lines, summaryLine("Unique Nodes", fmtInt(userStats.TotalNodes), styles))

	running, pendingCount := countByState(jobs)
	lines = append(lines, "", styles.Title.Render(" Jobs by State "))
	lines = append(lines, summaryLine("Running", styles.Success.Bold(true).Render(fmtInt(running)), styles))
	lines = append(lines, summaryLine("Pending", styles.Warning.Bold(true).Render(fmtInt(pendingCount)), styles))

	if pending != nil {
		lines = append(lines, "", styles.Title.Render(" Pending Resources "))
		lines = append(lines, summaryLine("Pending Jobs", styles.Warning.Bold(true).Render(fmtInt(pending.PendingJobCount)), styles))
		lines = append(lines, summaryLine("Requested CPUs", fmtInt(pending.PendingCPUs), styles))
		lines = append(lines, summaryLine("Requested Memory (GB)", fmt.Sprintf("%.1f", pending.PendingMemoryGB), styles))
		lines = append(lines, summaryLine("Requested GPUs", fmtInt(pending.PendingGPUs), styles))
		if pending.PendingGPUTypes != "" {
			lines = append(lines, summaryLine("GPU Types", styles.Success.Render(pending.PendingGPUTypes), styles))
		}
	}

	if len(assocs) > 0 {
		lines = append(lines, "", styles.Title.Render(" Fair-Share Priority "))
		lines = append(lines, userFairShareLines(me, assocs, st, styles)...)
	}

	if len(prios) > 0 {
		lines = append(lines, "", styles.Title.Render(" Pending Job Priorities "))
		for _, s := range store.PartitionStandings(prios) {
			lines = append(lines, summaryLine(s.Partition, store.FormatStanding(s), styles))
		}
		lines = append(lines, "", styles.Subtle.Render(fmt.Sprintf("  %-12s %-9s %-12s %-9s %s",
			"Partition", "Queue", "JobID", "Priority", "Breakdown")))
		for i, p := range store.ByPartition(prios) {
			if i >= maxUserPriorityJobs {
				lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  ... and %d more pending jobs", len(prios)-maxUserPriorityJobs)))
				break
			}
			lines = append(lines, fmt.Sprintf("  %-12s %-9s %-12s %-9d %s",
				trunc(p.Entry.Partition, 12), store.FormatQueue(p.Pos.Partition, p.Pos.PartitionTotal),
				trunc(p.Entry.JobID, 12), p.Entry.Priority, store.FormatBreakdown(p.Entry.Factors)))
		}
	}

	if len(jobs) > 0 {
		lines = append(lines, "", styles.Title.Render(" Job List "), "")
		lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  %-12s %-15s %-8s %-12s %-10s %-6s %-20s",
			"JobID", "Name", "State", "Partition", "Time", "Nodes", "NodeList")))
		for _, j := range jobs {
			lines = append(lines, fmt.Sprintf("  %-12s %-15s %s %-12s %-10s %-6s %-20s",
				trunc(j.ID, 12), trunc(j.Name, 15), userJobStateCell(j.State, styles),
				trunc(j.Partition, 12), trunc(j.Time, 10), trunc(j.NumNodes, 6), trunc(j.NodeList, 20)))
		}
	} else {
		lines = append(lines, "", styles.Subtle.Render("No active jobs found for this user."))
	}

	return strings.Join(lines, "\n")
}

// formatAccountInfo renders an account-detail block from the store's data, in
// this section order: account summary, account fair-share priority, aggregate
// resource usage, the users in the account, pending job priorities, and the
// running jobs.
func formatAccountInfo(account string, st *store.Store, styles theme.Styles) string {
	var accountEntry *store.FairShareEntry
	var users []store.FairShareEntry
	for i := range st.FairShare {
		e := st.FairShare[i]
		if e.Account != account {
			continue
		}
		if e.IsAccount() {
			ec := e
			accountEntry = &ec
		} else {
			users = append(users, e)
		}
	}

	usernames := map[string]struct{}{}
	for _, u := range users {
		usernames[u.User] = struct{}{}
	}

	var running, pending []store.AllUsersJob
	for _, j := range st.AllUsersJobs {
		if _, ok := usernames[strings.TrimSpace(j.User)]; !ok {
			continue
		}
		switch strings.ToUpper(strings.TrimSpace(j.State)) {
		case "RUNNING", "R":
			running = append(running, j)
		case "PENDING", "PD":
			pending = append(pending, j)
		}
	}

	var lines []string
	lines = append(lines, styles.Title.Render(" Account Summary "))
	lines = append(lines, summaryLine("Account Name", styles.Text.Bold(true).Render(account), styles))
	lines = append(lines, summaryLine("Users in Account", styles.Text.Bold(true).Render(fmtInt(len(users))), styles))
	lines = append(lines, summaryLine("Running Jobs", styles.Success.Bold(true).Render(fmtInt(len(running))), styles))
	lines = append(lines, summaryLine("Pending Jobs", styles.Warning.Bold(true).Render(fmtInt(len(pending))), styles))

	if accountEntry != nil {
		lines = append(lines, "", styles.Title.Render(" Account Fair-Share Priority "))
		acct := store.FindRankedAccount(store.RankAccounts(st.FairShare), account)
		lines = append(lines, accountFairShareLines(*accountEntry, acct, styles)...)
	}

	// Current Resource Usage: aggregate CPUs/memory/GPUs and unique nodes over the
	// account's running jobs, shown between the fair-share and users sections.
	usage := store.AggregateAccountResources(running)
	lines = append(lines, "", styles.Title.Render(" Current Resource Usage "))
	lines = append(lines, summaryLine("Total CPUs", fmtInt(usage.TotalCPUs), styles))
	lines = append(lines, summaryLine("Total Memory (GB)", fmt.Sprintf("%.1f", usage.TotalMemoryGB), styles))
	lines = append(lines, summaryLine("Total GPUs", fmtInt(usage.TotalGPUs), styles))
	lines = append(lines, summaryLine("Unique Nodes", fmtInt(usage.UniqueNodes), styles))

	if len(users) > 0 {
		sort.SliceStable(users, func(i, j int) bool {
			return store.FairShareValue(users[i]) > store.FairShareValue(users[j])
		})
		lines = append(lines, "", styles.Title.Render(" Users in Account "), "")
		lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  %-15s %-8s %-8s %-12s %-10s %s",
			"User", "Share", "Usage", "Usage/Share", "FairShare", "Status")))
		for i, u := range users {
			if i >= maxAccountUsers {
				lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  ... and %d more users", len(users)-maxAccountUsers)))
				break
			}
			ratio, ok := store.UsageRatio(u)
			band := store.ClassifyUsage(ratio, ok)
			role := styles.StateRoleStyle(band.Role())
			lines = append(lines, fmt.Sprintf("  %-15s %-8s %-8s %-12s %s %s",
				trunc(u.User, 15), store.FormatPercent(u.NormShares), store.FormatPercent(u.EffectvUsage),
				store.FormatRatio(ratio, ok), role.Render(fmt.Sprintf("%-10s", trunc(strings.TrimSpace(u.FairShare), 10))),
				role.Render(band.Label())))
		}
	}

	// Pending Job Priorities: the account's pending sprio rows grouped by
	// partition in queue order, capped at maxAccountPriorityJobs, shown between
	// the users and running-jobs sections.
	var prios []store.RankedPriority
	for _, p := range store.RankPending(st.PendingPrio) {
		if p.Entry.Account == account {
			prios = append(prios, p)
		}
	}
	if len(prios) > 0 {
		lines = append(lines, "", styles.Title.Render(" Pending Job Priorities "), "")
		lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  %-12s %-9s %-12s %-12s %-9s %s",
			"Partition", "Queue", "JobID", "User", "Priority", "Breakdown")))
		for i, p := range store.ByPartition(prios) {
			if i >= maxAccountPriorityJobs {
				lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  ... and %d more pending jobs", len(prios)-maxAccountPriorityJobs)))
				break
			}
			lines = append(lines, fmt.Sprintf("  %-12s %-9s %-12s %-12s %-9d %s",
				trunc(p.Entry.Partition, 12), store.FormatQueue(p.Pos.Partition, p.Pos.PartitionTotal),
				trunc(p.Entry.JobID, 12), trunc(p.Entry.User, 12), p.Entry.Priority,
				store.FormatBreakdown(p.Entry.Factors)))
		}
	}

	if len(running) > 0 {
		lines = append(lines, "", styles.Title.Render(" Running Jobs "), "")
		lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  %-12s %-12s %-15s %-12s %-10s %-6s",
			"JobID", "User", "Name", "Partition", "Time", "Nodes")))
		for i, j := range running {
			if i >= maxAccountRunningJobs {
				lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  ... and %d more running jobs", len(running)-maxAccountRunningJobs)))
				break
			}
			lines = append(lines, fmt.Sprintf("  %-12s %-12s %-15s %-12s %-10s %-6s",
				trunc(j.ID, 12), trunc(j.User, 12), trunc(j.Name, 15),
				trunc(j.Partition, 12), trunc(j.Time, 10), trunc(j.NumNodes, 6)))
		}
	} else {
		lines = append(lines, "", styles.Subtle.Render("No running jobs found for this account."))
	}

	return strings.Join(lines, "\n")
}

// userJobs returns the all-users jobs belonging to username.
func userJobs(st *store.Store, username string) []store.AllUsersJob {
	var out []store.AllUsersJob
	for _, j := range st.AllUsersJobs {
		if strings.TrimSpace(j.User) == username {
			out = append(out, j)
		}
	}
	return out
}

// countByState counts running and pending jobs.
func countByState(jobs []store.AllUsersJob) (running, pending int) {
	for _, j := range jobs {
		switch strings.ToUpper(strings.TrimSpace(j.State)) {
		case "RUNNING", "R":
			running++
		case "PENDING", "PD":
			pending++
		}
	}
	return running, pending
}

// userJobStateCell colors a state cell in a user job list, padded to width 8,
// using the shared store.StateRole classification so it matches the tables.
func userJobStateCell(state string, styles theme.Styles) string {
	cell := fmt.Sprintf("%-8s", trunc(state, 8))
	role := store.StateRole(state)
	if role == "" {
		return cell
	}
	return styles.StateRoleStyle(role).Bold(true).Render(cell)
}

// findPendingStats returns the pending-resource stats for username, or nil when
// the user has none.
func findPendingStats(stats []store.UserPendingStats, username string) *store.UserPendingStats {
	for i := range stats {
		if stats[i].Username == username {
			return &stats[i]
		}
	}
	return nil
}

// userFairShareLines renders the fair-share summary rows for a user. me is the
// user's row in the active-user ranking (nil when the user has no recent usage);
// assocs are all of the user's associations, so a user in several accounts sees
// the others under "Also in".
func userFairShareLines(me *store.RankedShare, assocs []store.FairShareEntry, st *store.Store, styles theme.Styles) []string {
	entry := assocs[0]
	ratio, ratioOK := store.UsageRatio(entry)
	band := store.ClassifyUsage(ratio, ratioOK)
	if me != nil {
		entry, ratio, ratioOK, band = me.Entry, me.Ratio, me.RatioOK, me.Band
	}
	role := styles.StateRoleStyle(band.Role())

	var lines []string
	lines = append(lines, summaryLine("Account", entry.Account, styles))
	lines = append(lines, summaryLine("Fair-Share Factor", role.Bold(true).Render(strings.TrimSpace(entry.FairShare)), styles))
	if me != nil {
		lines = append(lines, summaryLine("Rank", store.FormatRank(me.Rank, me.Total, "active users"), styles))
	}
	lines = append(lines, summaryLine("Status", role.Render(band.Label()), styles))
	lines = append(lines, summaryLine("Share", fmt.Sprintf("%s of cluster (%s raw shares)", store.FormatPercent(entry.NormShares), strings.TrimSpace(entry.RawShares)), styles))
	lines = append(lines, summaryLine("Usage", store.FormatPercent(entry.EffectvUsage)+" of recent cluster usage", styles))
	if ratioOK && ratio > 0 {
		lines = append(lines, summaryLine("Usage vs share", store.FormatRatio(ratio, true), styles))
	}
	if (band == store.UsageOver || band == store.UsageHeavy) && st.State(store.SectionPriorityConfig) == store.StateLoaded {
		halfLife := st.PriorityConfig.DecayHalfLife
		if recovery, ok := store.RecoveryTime(ratio, halfLife); ok {
			lines = append(lines, summaryLine("Recovery",
				fmt.Sprintf("≈%s idle to reach 1× (usage halves every %s)", store.FormatDays(recovery), store.FormatDays(halfLife)), styles))
		}
	}
	if len(assocs) > 1 {
		others := make([]string, 0, len(assocs)-1)
		for _, a := range assocs {
			if a.Account == entry.Account {
				continue
			}
			others = append(others, fmt.Sprintf("%s (%s)", a.Account, strings.TrimSpace(a.FairShare)))
		}
		lines = append(lines, summaryLine("Also in", strings.Join(others, ", "), styles))
	}
	return lines
}

// accountFairShareLines renders the fair-share summary rows for an account.
// acct is the account's row in the account ranking; it is nil for root, which
// has no share to compare usage against, so only the raw fields are shown then.
func accountFairShareLines(entry store.FairShareEntry, acct *store.RankedShare, styles theme.Styles) []string {
	var lines []string
	if acct != nil {
		role := styles.StateRoleStyle(acct.Band.Role())
		lines = append(lines, summaryLine("Rank", fmt.Sprintf("%d of %d accounts (best-served first)", acct.Rank, acct.Total), styles))
		lines = append(lines, summaryLine("Status", role.Render(acct.Band.Label()), styles))
	}
	lines = append(lines, summaryLine("Share", fmt.Sprintf("%s of cluster (%s raw shares)", store.FormatPercent(entry.NormShares), strings.TrimSpace(entry.RawShares)), styles))
	lines = append(lines, summaryLine("Usage", store.FormatPercent(entry.EffectvUsage)+" of recent cluster usage", styles))
	if acct != nil && acct.RatioOK && acct.Ratio > 0 {
		lines = append(lines, summaryLine("Usage vs share", store.FormatRatio(acct.Ratio, true), styles))
	}
	// Account rows have no FairShare under Fair Tree; only show one when present.
	if fs := strings.TrimSpace(entry.FairShare); fs != "" {
		lines = append(lines, summaryLine("Fair-Share Factor", styles.Text.Bold(true).Render(fs), styles))
	}
	return lines
}

// trunc truncates s to width display cells, never splitting a rune — a
// byte-based cut corrupts multi-byte job names and misaligns wide runes.
func trunc(s string, width int) string {
	return ansi.Truncate(s, width, "")
}
