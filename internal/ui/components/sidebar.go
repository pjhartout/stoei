package components

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// spinnerFrames are the braille loading frames, matching the per-section status
// spinner so loading indicators look consistent across the UI.
var spinnerFrames = []string{"⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"}

// spinnerFrame picks a loading-animation frame from wall-clock time. The UI's
// spinner tick re-renders at ~10 fps while a section is loading, so the frame
// advances and the indicator animates.
func spinnerFrame() string {
	idx := (time.Now().UnixNano() / int64(100*time.Millisecond)) % int64(len(spinnerFrames))
	return spinnerFrames[idx]
}

// SidebarMinTermWidth is the terminal-width threshold below which the cluster
// sidebar auto-hides so the active tab keeps the full frame on narrow terminals.
const SidebarMinTermWidth = 100

// gbPerTB converts gigabytes to terabytes for memory display.
const gbPerTB = 1024.0

// Sidebar renders cluster-wide load statistics from the store's derived
// ClusterStats: free-vs-allocated nodes/CPU/memory/GPU by type and array-expanded
// pending resources per partition. It renders from data only and never fetches.
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

// ClusterLoadContent renders the cluster-load sections without the sidebar's
// border box, so a scrollable modal can show the same content when the sidebar
// is too tall to fit. loaded=false yields the loading placeholder.
func ClusterLoadContent(stats store.ClusterStats, styles theme.Styles, loaded bool) string {
	return (&Sidebar{styles: styles, stats: stats, loaded: loaded}).body()
}

// body renders the sidebar content lines (without the border).
func (s *Sidebar) body() string {
	if !s.loaded {
		return lipgloss.JoinVertical(lipgloss.Left,
			s.titleRule(len("Cluster Load")),
			"",
			s.styles.Subtle.Render(spinnerFrame()+" Loading cluster…"),
		)
	}

	var lines []string
	lines = append(lines, s.nodesSection()...)
	lines = append(lines, s.cpuSection()...)
	lines = append(lines, s.memorySection()...)
	lines = append(lines, s.gpuSection()...)
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
// thresholds (high free is good: green at/above the green threshold, yellow
// above the yellow threshold, red below).
func (s *Sidebar) colorPct(pct float64) string {
	style := s.styles.PctStyle(pct, theme.SidebarGreenThreshold, theme.SidebarYellowThreshold, true)
	return style.Render(fmt.Sprintf("%.1f%%", pct))
}

// nodesSection renders the Nodes block as a single "free/total free (pct)" line.
func (s *Sidebar) nodesSection() []string {
	st := s.stats
	line := fmt.Sprintf("  %d/%d free (%s)", st.FreeNodes, st.TotalNodes, s.colorPct(st.FreeNodesPct()))
	if st.DrainingNodes > 0 {
		line += s.styles.Subtle.Render(fmt.Sprintf(" · %d drain", st.DrainingNodes))
	}
	return []string{s.styles.Text.Bold(true).Render("Nodes:"), line, ""}
}

// cpuSection renders the CPUs block as a single line.
func (s *Sidebar) cpuSection() []string {
	st := s.stats
	return []string{
		s.styles.Text.Bold(true).Render("CPUs:"),
		fmt.Sprintf("  %d/%d free (%s)", st.TotalCPUs-st.AllocatedCPUs, st.TotalCPUs, s.colorPct(st.FreeCPUsPct())),
		"",
	}
}

// memorySection renders the Memory block as a single line.
func (s *Sidebar) memorySection() []string {
	st := s.stats
	free := st.TotalMemoryGB - st.AllocatedMemoryGB
	return []string{
		s.styles.Text.Bold(true).Render("Memory:"),
		fmt.Sprintf("  %s free (%s)", memPair(free, st.TotalMemoryGB), s.colorPct(st.FreeMemoryPct())),
		"",
	}
}

// gpuSection renders the GPUs block: schedulable capacity broken down by GPU type
// (or a single total when types are unknown), followed by any draining-node
// capacity on its own lines. The generic "gpu" bucket is relabeled "generic" and
// MIG profiles are shortened (see store.ShortGPULabel).
func (s *Sidebar) gpuSection() []string {
	st := s.stats
	var rows []string

	if len(st.GPUsByType) > 0 {
		types := make([]string, 0, len(st.GPUsByType))
		for t := range st.GPUsByType {
			types = append(types, t)
		}
		sort.Strings(types)
		for _, t := range types {
			ta := st.GPUsByType[t]
			rows = append(rows, fmt.Sprintf("  %s %d/%d (%s)",
				s.gpuLabel(t), ta.Allocated, ta.Total, s.colorPct(st.GPUTypeFreePct(t))))
		}
	} else if st.TotalGPUs > 0 {
		rows = append(rows, fmt.Sprintf("  %d/%d free (%s)",
			st.TotalGPUs-st.AllocatedGPUs, st.TotalGPUs, s.colorPct(st.FreeGPUsPct())))
	}

	if len(st.DrainingGPUsByType) > 0 {
		types := make([]string, 0, len(st.DrainingGPUsByType))
		for t := range st.DrainingGPUsByType {
			types = append(types, t)
		}
		sort.Strings(types)
		for _, t := range types {
			rows = append(rows, s.styles.Subtle.Render(
				fmt.Sprintf("  %s %d (drain)", s.gpuLabel(t), st.DrainingGPUsByType[t])))
		}
	}

	if len(rows) == 0 {
		return nil
	}
	return append(append([]string{s.styles.Text.Bold(true).Render("GPUs:")}, rows...), "")
}

// gpuLabel renders a GPU type for the sidebar: the generic "gpu" bucket becomes
// "generic" and MIG profiles are shortened (e.g. "1g.10gb").
func (s *Sidebar) gpuLabel(typ string) string {
	if strings.EqualFold(typ, "gpu") {
		return "generic"
	}
	return store.ShortGPULabel(typ)
}

// pendingSection renders the pending-queue block as one compact line per
// partition — "name Nj·Cc·memG·gpus" with zero fields omitted — or nothing when
// there are no pending jobs.
func (s *Sidebar) pendingSection() []string {
	st := s.stats
	if st.PendingJobsCount <= 0 {
		return nil
	}
	lines := []string{s.styles.Text.Bold(true).Render("Pending:")}
	if len(st.PendingByPartition) == 0 {
		return append(lines, "  (no partition breakdown)")
	}

	for _, part := range sortedKeysFold(st.PendingByPartition) {
		ps := st.PendingByPartition[part]
		name := part
		if name == "" {
			name = "unknown"
		}
		segs := []string{fmt.Sprintf("%dj", ps.JobsCount)}
		if ps.CPUs > 0 {
			segs = append(segs, fmt.Sprintf("%dc", ps.CPUs))
		}
		if ps.MemoryGB > 0 {
			segs = append(segs, compactMem(ps.MemoryGB))
		}
		if gpus := pendingGPUs(ps); gpus != "" {
			segs = append(segs, gpus)
		}
		lines = append(lines, fmt.Sprintf("  %s %s", name, strings.Join(segs, "·")))
	}
	return lines
}

// pendingGPUs renders a partition's pending GPU request compactly, e.g. "2×H200"
// or "2×H200,4×1g.10gb", or "" when none are requested.
func pendingGPUs(ps store.PendingPartitionStats) string {
	if len(ps.GPUsByType) == 0 {
		if ps.GPUs > 0 {
			return fmt.Sprintf("%d×gpu", ps.GPUs)
		}
		return ""
	}
	types := make([]string, 0, len(ps.GPUsByType))
	for t := range ps.GPUsByType {
		types = append(types, t)
	}
	sort.Strings(types)
	parts := make([]string, len(types))
	for i, t := range types {
		parts[i] = fmt.Sprintf("%d×%s", ps.GPUsByType[t], store.ShortGPULabel(t))
	}
	return strings.Join(parts, ",")
}

// compactMem renders a memory amount without a space — "120G", "1.9T".
func compactMem(gb float64) string {
	if gb >= gbPerTB {
		return fmt.Sprintf("%.1fT", gb/gbPerTB)
	}
	return fmt.Sprintf("%.0fG", gb)
}

// memPair renders "free/total" memory in a shared unit — "192/256 GB",
// "1.9/2.0 TB".
func memPair(freeGB, totalGB float64) string {
	if totalGB >= gbPerTB {
		return fmt.Sprintf("%.1f/%.1f TB", freeGB/gbPerTB, totalGB/gbPerTB)
	}
	return fmt.Sprintf("%.0f/%.0f GB", freeGB, totalGB)
}

// sortedKeysFold returns the map's keys sorted case-insensitively.
func sortedKeysFold[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool {
		return strings.ToLower(keys[i]) < strings.ToLower(keys[j])
	})
	return keys
}
