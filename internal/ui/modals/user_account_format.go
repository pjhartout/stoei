package modals

import (
	"fmt"
	"sort"
	"strconv"
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
	fair := findFairShare(st.FairShare, username)
	prios := userPriorities(st.PendingPrio, username)

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

	if fair != nil {
		lines = append(lines, "", styles.Title.Render(" Fair-Share Priority "))
		lines = append(lines, summaryLine("Account", fair.Account, styles))
		lines = append(lines, summaryLine("Raw Shares", fair.RawShares, styles))
		lines = append(lines, summaryLine("Norm Shares", fair.NormShares, styles))
		lines = append(lines, summaryLine("Raw Usage", fair.RawUsage, styles))
		lines = append(lines, summaryLine("Effective Usage", fair.EffectvUsage, styles))
		lines = append(lines, summaryLine("Fair-Share Factor", fairShareColored(fair.FairShare, styles), styles))
	}

	if len(prios) > 0 {
		lines = append(lines, "", styles.Title.Render(" Pending Job Priorities "), "")
		lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  %-12s %-10s %-8s %-10s %-10s %-12s",
			"JobID", "Priority", "Age", "FairShare", "JobSize", "Partition")))
		for i, p := range prios {
			if i >= maxUserPriorityJobs {
				lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  ... and %d more pending jobs", len(prios)-maxUserPriorityJobs)))
				break
			}
			lines = append(lines, fmt.Sprintf("  %-12s %-10s %-8s %-10s %-10s %-12s",
				trunc(p.JobID, 12), trunc(p.Priority, 10), trunc(p.Age, 8),
				trunc(p.FairShare, 10), trunc(p.JobSize, 10), trunc(p.Partition, 12)))
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
		lines = append(lines, summaryLine("Raw Shares", accountEntry.RawShares, styles))
		lines = append(lines, summaryLine("Norm Shares", accountEntry.NormShares, styles))
		lines = append(lines, summaryLine("Raw Usage", accountEntry.RawUsage, styles))
		lines = append(lines, summaryLine("Effective Usage", accountEntry.EffectvUsage, styles))
		lines = append(lines, summaryLine("Fair-Share Factor", fairShareColored(accountEntry.FairShare, styles), styles))
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
			return parseF(users[i].FairShare) > parseF(users[j].FairShare)
		})
		lines = append(lines, "", styles.Title.Render(" Users in Account "), "")
		lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  %-15s %-12s %-12s %-12s %-10s",
			"User", "RawShares", "NormShares", "EffectvUsage", "FairShare")))
		for i, u := range users {
			if i >= maxAccountUsers {
				lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  ... and %d more users", len(users)-maxAccountUsers)))
				break
			}
			lines = append(lines, fmt.Sprintf("  %-15s %-12s %-12s %-12s %s",
				trunc(u.User, 15), trunc(u.RawShares, 12), trunc(u.NormShares, 12),
				trunc(u.EffectvUsage, 12), fairShareColored(u.FairShare, styles)))
		}
	}

	// Pending Job Priorities: the account's pending sprio rows, sorted by priority
	// descending and capped at maxAccountPriorityJobs, shown between the users and
	// running-jobs sections.
	prios := accountPriorities(st.PendingPrio, usernames)
	if len(prios) > 0 {
		lines = append(lines, "", styles.Title.Render(" Pending Job Priorities "), "")
		lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  %-12s %-12s %-10s %-8s %-10s %-12s",
			"JobID", "User", "Priority", "Age", "FairShare", "Partition")))
		for i, p := range prios {
			if i >= maxAccountPriorityJobs {
				lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  ... and %d more pending jobs", len(prios)-maxAccountPriorityJobs)))
				break
			}
			lines = append(lines, fmt.Sprintf("  %-12s %-12s %-10s %-8s %-10s %-12s",
				trunc(p.JobID, 12), trunc(p.User, 12), trunc(p.Priority, 10),
				trunc(p.Age, 8), trunc(p.FairShare, 10), trunc(p.Partition, 12)))
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

// findFairShare returns the fair-share entry for username, or nil when the user
// has none.
func findFairShare(entries []store.FairShareEntry, username string) *store.FairShareEntry {
	for i := range entries {
		if entries[i].User == username {
			return &entries[i]
		}
	}
	return nil
}

// userPriorities returns the user's pending priorities, sorted by priority desc.
func userPriorities(entries []store.PriorityEntry, username string) []store.PriorityEntry {
	var out []store.PriorityEntry
	for _, e := range entries {
		if e.User == username {
			out = append(out, e)
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return parseF(out[i].Priority) > parseF(out[j].Priority) })
	return out
}

// accountPriorities returns the pending priorities whose user belongs to the
// account (the given username set), sorted by priority descending.
func accountPriorities(entries []store.PriorityEntry, usernames map[string]struct{}) []store.PriorityEntry {
	var out []store.PriorityEntry
	for _, e := range entries {
		if _, ok := usernames[strings.TrimSpace(e.User)]; ok {
			out = append(out, e)
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return parseF(out[i].Priority) > parseF(out[j].Priority) })
	return out
}

// fairShareColored renders a fair-share value colored by the shared
// store.FairShareRole classification. A non-numeric value is returned uncolored.
func fairShareColored(fairShare string, styles theme.Styles) string {
	raw := strings.TrimSpace(fairShare)
	role := store.FairShareRole(raw)
	if role == "" {
		return raw
	}
	return styles.StateRoleStyle(role).Bold(true).Render(raw)
}

// parseF parses a float, returning 0 on failure (sort key only).
func parseF(s string) float64 {
	v, err := strconv.ParseFloat(strings.TrimSpace(s), 64)
	if err != nil {
		return 0
	}
	return v
}

// trunc truncates s to width display cells, never splitting a rune — a
// byte-based cut corrupts multi-byte job names and misaligns wide runes.
func trunc(s string, width int) string {
	return ansi.Truncate(s, width, "")
}
