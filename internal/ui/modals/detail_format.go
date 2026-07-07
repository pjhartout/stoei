package modals

import (
	"fmt"
	"sort"
	"strings"

	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// fieldCategory is a titled group of field keys rendered together in a detail
// modal. The category lists below define the order in which known fields appear.
type fieldCategory struct {
	title  string
	fields []string
}

// scontrolJobCategories groups the fields of "scontrol show jobid" output into
// the titled sections shown in the job-detail modal.
var scontrolJobCategories = []fieldCategory{
	{"Identity", []string{"JobId", "JobName", "UserId", "GroupId", "Account", "QOS"}},
	{"Status", []string{"JobState", "Reason", "ExitCode", "DerivedExitCode", "RunTime", "TimeLimit", "Restarts", "Requeue"}},
	{"Resources", []string{"Partition", "NumNodes", "NumCPUs", "NumTasks", "CPUs/Task", "TRES", "MinCPUsNode", "MinMemoryNode", "MinMemoryCPU", "ReqTRES", "AllocTRES", "Gres", "TresPerNode"}},
	{"Nodes", []string{"NodeList", "BatchHost", "ReqNodeList", "ExcNodeList", "Features", "Reservation"}},
	{"Timing", []string{"SubmitTime", "EligibleTime", "AccrueTime", "StartTime", "EndTime", "Deadline", "SuspendTime", "PreemptTime", "PreemptEligibleTime", "LastSchedEval"}},
	{"Paths", []string{"WorkDir", "StdErr", "StdOut", "StdIn", "Command", "BatchFlag"}},
	{"Scheduling", []string{"Priority", "Nice", "Contiguous", "Licenses", "Network", "Power", "NtasksPerN:B:S:C", "CoreSpec", "Shared", "OverSubscribe"}},
}

// nodeCategories groups the fields of "scontrol show node" output into the
// titled sections shown in the node-detail modal.
var nodeCategories = []fieldCategory{
	{"Identity", []string{"NodeName", "NodeAddr", "NodeHostName", "Arch", "OS", "Version"}},
	{"Status", []string{"State", "Reason", "Owner", "MCS_label"}},
	{"Resources", []string{"CPUTot", "CPUAlloc", "CPULoad", "CPUEfctv", "RealMemory", "AllocMem", "FreeMem", "CfgTRES", "AllocTRES", "Gres", "TmpDisk"}},
	{"Hardware", []string{"CoresPerSocket", "Sockets", "Boards", "ThreadsPerCore", "Weight", "AvailableFeatures", "ActiveFeatures"}},
	{"Partitions", []string{"Partitions"}},
	{"Timing", []string{"BootTime", "SlurmdStartTime", "LastBusyTime", "ResumeAfterTime"}},
	{"Power", []string{"CurrentWatts", "AveWatts"}},
}

// labelWidth is the width each field label is padded to with trailing dots so
// values align in a column.
const labelWidth = 24

// formatJobDetail renders a JobDetail's "scontrol show jobid" fields grouped by
// category.
func formatJobDetail(detail store.JobDetail, styles theme.Styles) string {
	if len(detail.Fields) == 0 {
		return styles.Subtle.Render("No job information could be parsed.")
	}
	return formatCategorized(detail.Fields, scontrolJobCategories, nil, styles)
}

// formatNodeDetail renders a node's scontrol fields grouped by category.
func formatNodeDetail(detail store.JobDetail, styles theme.Styles) string {
	if len(detail.Fields) == 0 {
		return styles.Subtle.Render("No node information could be parsed.")
	}
	return formatCategorized(detail.Fields, nodeCategories, nil, styles)
}

// maxNodeJobs caps how many rows the "Jobs on Node" section renders before
// collapsing the remainder into an "... and N more" line.
const maxNodeJobs = 30

// formatNodeJobs renders the jobs currently occupying the node as a "Jobs on
// Node" section, listing each job's user, id, name, CPU and GPU counts, and run
// time. It returns "" when the store is nil or no jobs occupy the node.
func formatNodeJobs(st *store.Store, node string, styles theme.Styles) string {
	if st == nil {
		return ""
	}
	jobs := store.JobsOnNode(st.AllUsersJobs, node)
	if len(jobs) == 0 {
		return ""
	}

	lines := []string{
		styles.Title.Render(" Jobs on Node "),
		"",
		styles.Subtle.Render(fmt.Sprintf("  %-12s %-12s %-20s %-6s %-6s %-10s",
			"User", "JobID", "Name", "CPUs", "GPUs", "Time")),
	}
	for i, j := range jobs {
		if i >= maxNodeJobs {
			lines = append(lines, styles.Subtle.Render(fmt.Sprintf("  ... and %d more jobs", len(jobs)-maxNodeJobs)))
			break
		}
		lines = append(lines, fmt.Sprintf("  %-12s %-12s %-20s %-6d %-6d %-10s",
			trunc(j.User, 12), trunc(j.ID, 12), trunc(j.Name, 20), j.CPUs, j.GPUs, trunc(j.Time, 10)))
	}
	return strings.Join(lines, "\n")
}

// formatCategorized renders fields grouped by category, then any remaining
// uncategorized fields under "Other" in sorted order. display optionally maps a
// field key to a friendlier label.
func formatCategorized(fields map[string]string, categories []fieldCategory, display map[string]string, styles theme.Styles) string {
	var lines []string
	seen := map[string]struct{}{}

	for _, cat := range categories {
		var catLines []string
		for _, f := range cat.fields {
			val, ok := fields[f]
			if !ok {
				continue
			}
			seen[f] = struct{}{}
			label := f
			if display != nil {
				if d, ok := display[f]; ok {
					label = d
				}
			}
			catLines = append(catLines, formatFieldLine(label, f, val, styles))
		}
		if len(catLines) > 0 {
			lines = append(lines, "", styles.Title.Render(" "+cat.title+" "))
			lines = append(lines, catLines...)
		}
	}

	var remaining []string
	for k := range fields {
		if _, ok := seen[k]; !ok {
			remaining = append(remaining, k)
		}
	}
	if len(remaining) > 0 {
		sort.Strings(remaining)
		lines = append(lines, "", styles.Title.Render(" Other "))
		for _, k := range remaining {
			label := k
			if display != nil {
				if d, ok := display[k]; ok {
					label = d
				}
			}
			lines = append(lines, formatFieldLine(label, k, fields[k], styles))
		}
	}

	return strings.Join(lines, "\n")
}

// formatFieldLine renders one "label.......... value" line, coloring the value by
// the field key via colorFieldValue.
func formatFieldLine(label, key, value string, styles theme.Styles) string {
	leader := dottedLabel(label, labelWidth)
	return "  " + styles.Subtle.Render(leader) + " " + colorFieldValue(key, value, styles)
}

// dottedLabel renders a label left-aligned and padded out to width with trailing
// dots (a dotted leader); labels at or over width are returned unchanged.
func dottedLabel(label string, width int) string {
	if len(label) >= width {
		return label
	}
	return label + strings.Repeat(".", width-len(label))
}

// colorFieldValue colors a field value by its key: states get their role color,
// exit codes go green for 0:0 and red otherwise, paths are italicized, time
// fields are warning-colored, counts are bolded, and TRES/Gres are green. Empty
// or placeholder values render as a subdued "(not set)".
func colorFieldValue(key, value string, styles theme.Styles) string {
	if value == "" || value == "(null)" || value == "N/A" || value == "None" {
		return styles.Subtle.Render("(not set)")
	}
	switch {
	case key == "JobState" || key == "State":
		base := value
		if i := strings.IndexByte(value, ' '); i >= 0 {
			base = value[:i]
		}
		return stateStyle(base, styles).Bold(true).Render(value)
	case strings.Contains(key, "ExitCode"):
		if value == "0:0" {
			return styles.Success.Render("0:0 ✓")
		}
		return styles.Error.Render(value + " ✗")
	case key == "WorkDir" || key == "StdErr" || key == "StdOut" || key == "StdIn" || key == "Command":
		return styles.Text.Italic(true).Render(value)
	case strings.Contains(key, "Time") && value != "Unknown" && value != "N/A":
		return styles.Warning.Render(value)
	case key == "NumNodes" || key == "NumCPUs" || key == "NumTasks" || key == "Priority" || key == "Nice" || key == "Restarts":
		return styles.Text.Bold(true).Render(value)
	case strings.Contains(key, "TRES") || key == "Gres":
		return styles.Success.Render(value)
	case strings.Contains(key, "Node") && key != "NumNodes":
		return styles.Text.Render(value)
	default:
		return styles.Text.Render(value)
	}
}

// stateStyle returns the style for a job/node state using the shared
// store.StateRole classification, so a state colors the same here as in the
// tables.
func stateStyle(state string, styles theme.Styles) lipgloss.Style {
	return styles.StateRoleStyle(store.StateRole(state))
}

// stdoutStderrPaths extracts the stdout and stderr log paths from a job detail's
// fields, preferring the scontrol keys (StdOut/StdErr) and falling back to the
// sacct keys (StdOutPath/StdErrPath).
func stdoutStderrPaths(fields map[string]string) (stdout, stderr string) {
	stdout = firstNonEmpty(fields["StdOut"], fields["StdOutPath"])
	stderr = firstNonEmpty(fields["StdErr"], fields["StdErrPath"])
	return stdout, stderr
}

// firstNonEmpty returns the first non-empty, non-placeholder value.
func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		v = strings.TrimSpace(v)
		if v != "" && v != "(null)" && v != "N/A" {
			return v
		}
	}
	return ""
}

// fmtInt formats an int for a summary line.
func fmtInt(n int) string { return fmt.Sprintf("%d", n) }
