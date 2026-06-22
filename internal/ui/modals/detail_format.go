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
// modal, porting the JOB_CATEGORIES / SACCT_CATEGORIES / NODE_CATEGORIES maps in
// stoei/slurm/formatters.py.
type fieldCategory struct {
	title  string
	fields []string
}

// scontrolJobCategories ports formatters.JOB_CATEGORIES (scontrol show jobid).
var scontrolJobCategories = []fieldCategory{
	{"Identity", []string{"JobId", "JobName", "UserId", "GroupId", "Account", "QOS"}},
	{"Status", []string{"JobState", "Reason", "ExitCode", "DerivedExitCode", "RunTime", "TimeLimit", "Restarts", "Requeue"}},
	{"Resources", []string{"Partition", "NumNodes", "NumCPUs", "NumTasks", "CPUs/Task", "TRES", "MinCPUsNode", "MinMemoryNode", "MinMemoryCPU", "ReqTRES", "AllocTRES", "Gres", "TresPerNode"}},
	{"Nodes", []string{"NodeList", "BatchHost", "ReqNodeList", "ExcNodeList", "Features", "Reservation"}},
	{"Timing", []string{"SubmitTime", "EligibleTime", "AccrueTime", "StartTime", "EndTime", "Deadline", "SuspendTime", "PreemptTime", "PreemptEligibleTime", "LastSchedEval"}},
	{"Paths", []string{"WorkDir", "StdErr", "StdOut", "StdIn", "Command", "BatchFlag"}},
	{"Scheduling", []string{"Priority", "Nice", "Contiguous", "Licenses", "Network", "Power", "NtasksPerN:B:S:C", "CoreSpec", "Shared", "OverSubscribe"}},
}

// sacctFieldDisplay ports formatters.SACCT_FIELD_DISPLAY (sacct -> display name).
var sacctFieldDisplay = map[string]string{
	"JobID": "Job ID", "JobName": "Job Name", "User": "User", "Account": "Account",
	"Partition": "Partition", "State": "State", "ExitCode": "Exit Code",
	"Start": "Start Time", "End": "End Time", "Elapsed": "Elapsed Time",
	"TimelimitRaw": "Time Limit (min)", "NNodes": "Nodes", "NCPUS": "CPUs",
	"NTasks": "Tasks", "ReqMem": "Requested Memory", "MaxRSS": "Max RSS",
	"MaxVMSize": "Max VM Size", "NodeList": "Node List", "WorkDir": "Work Directory",
	"StdOut": "StdOut Path", "StdErr": "StdErr Path", "Submit": "Submit Time",
	"Priority": "Priority", "QOS": "QOS",
}

// sacctJobCategories ports formatters.SACCT_CATEGORIES (sacct fallback).
var sacctJobCategories = []fieldCategory{
	{"Identity", []string{"JobID", "JobName", "User", "Account", "QOS"}},
	{"Status", []string{"State", "ExitCode", "Priority"}},
	{"Resources", []string{"Partition", "NNodes", "NCPUS", "NTasks", "ReqMem", "MaxRSS", "MaxVMSize"}},
	{"Nodes", []string{"NodeList"}},
	{"Timing", []string{"Submit", "Start", "End", "Elapsed", "TimelimitRaw"}},
	{"Paths", []string{"WorkDir", "StdOut", "StdErr"}},
}

// nodeCategories ports formatters.NODE_CATEGORIES (scontrol show node).
var nodeCategories = []fieldCategory{
	{"Identity", []string{"NodeName", "NodeAddr", "NodeHostName", "Arch", "OS", "Version"}},
	{"Status", []string{"State", "Reason", "Owner", "MCS_label"}},
	{"Resources", []string{"CPUTot", "CPUAlloc", "CPULoad", "CPUEfctv", "RealMemory", "AllocMem", "FreeMem", "CfgTRES", "AllocTRES", "Gres", "TmpDisk"}},
	{"Hardware", []string{"CoresPerSocket", "Sockets", "Boards", "ThreadsPerCore", "Weight", "AvailableFeatures", "ActiveFeatures"}},
	{"Partitions", []string{"Partitions"}},
	{"Timing", []string{"BootTime", "SlurmdStartTime", "LastBusyTime", "ResumeAfterTime"}},
	{"Power", []string{"CurrentWatts", "AveWatts"}},
}

// labelWidth is the dotted-leader field-label width, porting the ":.<24" padding
// used throughout formatters.py.
const labelWidth = 24

// formatJobDetail renders a JobDetail's fields, choosing the scontrol or sacct
// category set from its Source. Ports format_job_info / format_sacct_job_info.
func formatJobDetail(detail store.JobDetail, styles theme.Styles) string {
	if len(detail.Fields) == 0 {
		return styles.Subtle.Render("No job information could be parsed.")
	}
	if detail.Source == "sacct" {
		header := styles.Subtle.Render("(i) Historical data from sacct (job completed)")
		body := formatCategorized(detail.Fields, sacctJobCategories, sacctFieldDisplay, styles)
		return header + "\n" + body
	}
	return formatCategorized(detail.Fields, scontrolJobCategories, nil, styles)
}

// formatNodeDetail renders a node's scontrol fields by category. Ports
// format_node_info.
func formatNodeDetail(detail store.JobDetail, styles theme.Styles) string {
	if len(detail.Fields) == 0 {
		return styles.Subtle.Render("No node information could be parsed.")
	}
	return formatCategorized(detail.Fields, nodeCategories, nil, styles)
}

// formatCategorized renders fields grouped by category, then any remaining
// uncategorized fields under "Other" in sorted order. display optionally maps a
// field key to a friendlier label. Ports the shared category-rendering loop in
// formatters.py.
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
// the field key. Ports the per-line formatting in formatters.py (the dotted
// leader plus format_value coloring).
func formatFieldLine(label, key, value string, styles theme.Styles) string {
	leader := dottedLabel(label, labelWidth)
	return "  " + styles.Subtle.Render(leader) + " " + colorFieldValue(key, value, styles)
}

// dottedLabel renders a label padded out to width with trailing dots, porting the
// Python "{label:.<24}" format spec.
func dottedLabel(label string, width int) string {
	if len(label) >= width {
		return label
	}
	return label + strings.Repeat(".", width-len(label))
}

// colorFieldValue colors a field value by key, porting formatters.format_value.
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
// fields, trying the scontrol keys then the sacct keys. Ports the StdOut/StdErr
// extraction get_job_info_and_log_paths performs for the JobInfoScreen.
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
