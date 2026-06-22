package components

import (
	"fmt"
	"sort"
	"strings"

	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// SidebarMinTermWidth is the terminal-width threshold below which the cluster
// sidebar auto-hides so the active tab keeps the full frame. Mirrors the Python
// app's narrow-terminal behavior (the sidebar is removed on small widths).
const SidebarMinTermWidth = 100

// gbPerTB converts gigabytes to terabytes for memory display.
const gbPerTB = 1024.0

// Sidebar renders cluster-wide load statistics from the store's derived
// ClusterStats: free-vs-allocated nodes/CPU/memory/GPU by type, array-expanded
// pending resources per partition, and per-partition wait-time stats. It renders
// from data only and never fetches. Ports widgets/cluster_sidebar.py.
type Sidebar struct {
	styles theme.Styles
	stats  store.ClusterStats
	loaded bool
	height int
}

// NewSidebar returns a Sidebar styled with styles.
func NewSidebar(styles theme.Styles) *Sidebar {
	return &Sidebar{styles: styles}
}

// SetStyles re-themes the sidebar.
func (s *Sidebar) SetStyles(styles theme.Styles) { s.styles = styles }

// SetSize records the available height; the width auto-fits the content.
func (s *Sidebar) SetSize(_, height int) { s.height = height }

// SetStats updates the rendered statistics. Passing loaded=false (before the
// first nodes fetch) shows a loading placeholder.
func (s *Sidebar) SetStats(stats store.ClusterStats, loaded bool) {
	s.stats = stats
	s.loaded = loaded
}

// Width returns the sidebar's rendered width, which auto-fits its widest line.
func (s *Sidebar) Width() int { return lipgloss.Width(s.View()) }

// ShouldShow reports whether the sidebar fits at the given terminal width.
func ShouldShow(termWidth int) bool { return termWidth >= SidebarMinTermWidth }

// View renders the sidebar inside a rounded border tinted with the accent color,
// distinguishing this persistent chrome from the transient (border-colored)
// overlay modals that reuse the same Modal box.
func (s *Sidebar) View() string {
	body := s.body()
	box := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(s.styles.Accent).
		Foreground(s.styles.Text.GetForeground()).
		Padding(1, 2) // no explicit width: the box auto-fits its content
	if s.height > 0 {
		box = box.Height(s.height)
	}
	return box.Render(body)
}

// titleRule renders the sidebar title with a thin underline rule beneath it,
// visually separating the header from the stats. The rule width tracks the
// widest body line so it spans the content.
func (s *Sidebar) titleRule(width int) string {
	if width < 1 {
		width = len("Cluster Load")
	}
	return lipgloss.JoinVertical(lipgloss.Left,
		s.styles.Title.Render("Cluster Load"),
		s.styles.Subtle.Render(strings.Repeat("─", width)),
	)
}

// body renders the sidebar content lines (without the border).
func (s *Sidebar) body() string {
	if !s.loaded {
		return lipgloss.JoinVertical(lipgloss.Left,
			s.titleRule(len("Cluster Load")),
			"",
			s.styles.Subtle.Render("Loading cluster…"),
		)
	}

	var lines []string
	lines = append(lines, s.nodesSection()...)
	lines = append(lines, s.cpuSection()...)
	lines = append(lines, s.memorySection()...)
	lines = append(lines, s.gpuSection()...)
	lines = append(lines, s.waitTimeSection()...)
	lines = append(lines, s.pendingSection()...)

	// Size the title rule to the widest stats line so the underline spans the
	// content.
	width := len("Cluster Load")
	for _, l := range lines {
		if w := lipgloss.Width(l); w > width {
			width = w
		}
	}
	header := []string{s.titleRule(width), ""}
	return strings.Join(append(header, lines...), "\n")
}

// colorPct renders a "NN.N%" value colored by the inverted free-resource
// thresholds (high free is good). Ports ClusterSidebar._color_pct.
func (s *Sidebar) colorPct(pct float64) string {
	style := s.styles.PctStyle(pct, theme.SidebarGreenThreshold, theme.SidebarYellowThreshold, true)
	return style.Render(fmt.Sprintf("%.1f%%", pct))
}

// nodesSection renders the Nodes block.
func (s *Sidebar) nodesSection() []string {
	st := s.stats
	lines := []string{
		s.styles.Text.Bold(true).Render("Nodes:"),
		"  Free: " + s.colorPct(st.FreeNodesPct()),
		fmt.Sprintf("  %d/%d available", st.FreeNodes, st.TotalNodes),
	}
	if st.DrainingNodes > 0 {
		lines = append(lines, s.styles.Subtle.Render(fmt.Sprintf("  (%d draining)", st.DrainingNodes)))
	}
	return append(lines, "")
}

// cpuSection renders the CPUs block.
func (s *Sidebar) cpuSection() []string {
	st := s.stats
	return []string{
		s.styles.Text.Bold(true).Render("CPUs:"),
		"  Free: " + s.colorPct(st.FreeCPUsPct()),
		fmt.Sprintf("  %d/%d available", st.TotalCPUs-st.AllocatedCPUs, st.TotalCPUs),
		"",
	}
}

// memorySection renders the Memory block.
func (s *Sidebar) memorySection() []string {
	st := s.stats
	return []string{
		s.styles.Text.Bold(true).Render("Memory:"),
		"  Free: " + s.colorPct(st.FreeMemoryPct()),
		fmt.Sprintf("  %.1f/%.1f GB", st.TotalMemoryGB-st.AllocatedMemoryGB, st.TotalMemoryGB),
		"",
	}
}

// gpuSection renders the GPUs block, by type when types are known. Ports
// ClusterSidebar._append_gpu_section.
func (s *Sidebar) gpuSection() []string {
	st := s.stats
	if len(st.GPUsByType) > 0 {
		lines := []string{s.styles.Text.Bold(true).Render("GPUs:")}
		types := make([]string, 0, len(st.GPUsByType))
		for t := range st.GPUsByType {
			types = append(types, t)
		}
		sort.Strings(types)
		for _, t := range types {
			ta := st.GPUsByType[t]
			label := t
			if t == "gpu" {
				label = "generic"
			}
			lines = append(lines, fmt.Sprintf("  %s: %d/%d (%s)",
				label, ta.Allocated, ta.Total, s.colorPct(st.GPUTypeFreePct(t))))
		}
		return append(lines, "")
	}

	if st.TotalGPUs > 0 {
		return []string{
			s.styles.Text.Bold(true).Render("GPUs:"),
			fmt.Sprintf("  Total: %d", st.TotalGPUs),
			fmt.Sprintf("  Free: %d (%s)", st.TotalGPUs-st.AllocatedGPUs, s.colorPct(st.FreeGPUsPct())),
			"",
		}
	}
	return nil
}

// waitTimeSection renders the per-partition wait-time block. Ports
// ClusterSidebar._append_wait_time_section.
func (s *Sidebar) waitTimeSection() []string {
	st := s.stats
	if len(st.WaitStatsByPartition) == 0 {
		return nil
	}
	lines := []string{
		s.styles.Text.Bold(true).Render("Wait Times"),
		s.styles.Subtle.Render(fmt.Sprintf("Jobs started in last %dh", st.WaitStatsHours)),
		s.styles.Subtle.Render("(mean/median/range)"),
	}
	for _, part := range sortedKeysFold(st.WaitStatsByPartition) {
		w := st.WaitStatsByPartition[part]
		lines = append(lines, fmt.Sprintf("  %s: %s/%s/%s-%s",
			part,
			store.FormatWaitTime(w.MeanSeconds),
			store.FormatWaitTime(w.MedianSeconds),
			store.FormatWaitTime(w.MinSeconds),
			store.FormatWaitTime(w.MaxSeconds),
		))
	}
	return append(lines, "")
}

// pendingSection renders the per-partition pending-queue block. Ports
// ClusterSidebar._append_pending_queue_section.
func (s *Sidebar) pendingSection() []string {
	st := s.stats
	if st.PendingJobsCount <= 0 {
		return nil
	}
	lines := []string{s.styles.Text.Bold(true).Render("Pending Queue")}
	if len(st.PendingByPartition) == 0 {
		return append(lines, "  (No partition breakdown available)")
	}

	for _, part := range sortedPartitionKeysFold(st.PendingByPartition) {
		ps := st.PendingByPartition[part]
		name := part
		if name == "" {
			name = "unknown"
		}
		lines = append(lines, fmt.Sprintf("  %s: %d jobs", name, ps.JobsCount))
		if ps.CPUs > 0 {
			lines = append(lines, fmt.Sprintf("    CPUs: %d", ps.CPUs))
		}
		if ps.MemoryGB > 0 {
			lines = append(lines, "    Memory: "+formatMemoryGB(ps.MemoryGB))
		}
		if len(ps.GPUsByType) > 0 {
			lines = append(lines, "    GPUs:")
			gtypes := make([]string, 0, len(ps.GPUsByType))
			for t := range ps.GPUsByType {
				gtypes = append(gtypes, t)
			}
			sort.Strings(gtypes)
			for _, t := range gtypes {
				label := t
				if t == "gpu" {
					label = "generic"
				}
				lines = append(lines, fmt.Sprintf("      %s: %d", label, ps.GPUsByType[t]))
			}
		} else if ps.GPUs > 0 {
			lines = append(lines, fmt.Sprintf("    GPUs: %d", ps.GPUs))
		}
	}
	return lines
}

// formatMemoryGB renders memory in GB or TB. Ports cluster_sidebar.format_memory_gb.
func formatMemoryGB(memoryGB float64) string {
	if memoryGB >= gbPerTB {
		return fmt.Sprintf("%.1f TB", memoryGB/gbPerTB)
	}
	return fmt.Sprintf("%.1f GB", memoryGB)
}

// sortedKeysFold returns the wait-stats partition keys sorted case-insensitively.
func sortedKeysFold(m map[string]store.PartitionWaitStats) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool {
		return strings.ToLower(keys[i]) < strings.ToLower(keys[j])
	})
	return keys
}

// sortedPartitionKeysFold returns the pending-partition keys sorted
// case-insensitively.
func sortedPartitionKeysFold(m map[string]store.PendingPartitionStats) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool {
		return strings.ToLower(keys[i]) < strings.ToLower(keys[j])
	})
	return keys
}
