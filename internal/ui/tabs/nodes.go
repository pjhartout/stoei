package tabs

import (
	"fmt"

	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/table"
	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// nodeColumns are the Nodes-tab columns in render order. Ports
// NodeOverviewTab.NODE_TABLE_COLUMN_CONFIGS.
var nodeColumns = []column{
	{key: "node", title: "Node", width: 12},
	{key: "state", title: "State", width: 9},
	{key: "cpus", title: "CPUs", width: 8},
	{key: "cpu_pct", title: "CPU%", numeric: true, width: 6},
	{key: "memory", title: "Memory", width: 16},
	{key: "mem_pct", title: "Mem%", numeric: true, width: 6},
	{key: "gpus", title: "GPUs", width: 6},
	{key: "gpu_pct", title: "GPU%", numeric: true, width: 6},
	{key: "gpu_types", title: "GPU Types", width: 12},
	{key: "partitions", title: "Partitions", width: 10},
	{key: "reason", title: "Reason", width: 12},
}

// Indices into nodeColumns used by the row decorator.
var (
	nodeStateColumnIndex  = columnIndexIn(nodeColumns, "state")
	nodeCPUPctColumnIndex = columnIndexIn(nodeColumns, "cpu_pct")
	nodeMemPctColumnIndex = columnIndexIn(nodeColumns, "mem_pct")
	nodeGPUPctColumnIndex = columnIndexIn(nodeColumns, "gpu_pct")
)

// Nodes is the per-node overview tab. It renders a filterable, sortable table of
// every cluster node from the store's derived NodeDisplays: CPU/memory/GPU
// allocation versus total with colored usage percentages, GPU types, partitions,
// and the drain Reason. Coloring of the State and percent columns ports
// node_overview.py (_format_state / _format_pct).
type Nodes struct {
	store  *store.Store
	styles theme.Styles
	tbl    filterTable
}

// NewNodes returns a Nodes tab bound to s.
func NewNodes(s *store.Store, styles theme.Styles) *Nodes {
	n := &Nodes{store: s, styles: styles}
	n.tbl = newFilterTable(nodeColumns, styles, n.decorate)
	n.Refresh()
	return n
}

// SetStyles re-themes the tab.
func (n *Nodes) SetStyles(styles theme.Styles) {
	n.styles = styles
	n.tbl.SetStyles(styles)
}

// SetSize resizes the inner table.
func (n *Nodes) SetSize(width, height int) { n.tbl.SetSize(width, height) }

// Update handles tab-local input (filter/sort/navigation). Enter on a row will
// open a node-detail modal in Phase 5; the hook is noted but not yet wired.
func (n *Nodes) Update(msg tea.Msg) (*Nodes, tea.Cmd) {
	cmd := n.tbl.Update(msg)
	return n, cmd
}

// Refresh rebuilds the table rows from the store's node displays.
func (n *Nodes) Refresh() {
	displays := n.store.NodeDisplays()
	rows := make([][]string, 0, len(displays))
	for _, d := range displays {
		rows = append(rows, nodeRow(d))
	}
	n.tbl.SetRows(rows)
}

// nodeRow builds the plain (markup-free) cell values for one node. Ports the row
// formatting in NodeOverviewTab.update_nodes, including the "N/A" GPU display for
// GPU-less nodes.
func nodeRow(d store.NodeDisplay) []string {
	cpuDisplay := fmt.Sprintf("%d/%d", d.CPUsAlloc, d.CPUsTotal)
	memDisplay := fmt.Sprintf("%.1f/%.1f GB", d.MemoryAllocGB, d.MemoryTotalGB)

	gpuDisplay, gpuPct, gpuTypes := "N/A", "N/A", "N/A"
	if d.GPUsTotal > 0 {
		gpuDisplay = fmt.Sprintf("%d/%d", d.GPUsAlloc, d.GPUsTotal)
		gpuPct = fmt.Sprintf("%.1f%%", d.GPUUsagePct())
		if d.GPUTypes != "" {
			gpuTypes = d.GPUTypes
		}
	}

	return []string{
		d.Name,
		d.State,
		cpuDisplay,
		fmt.Sprintf("%.1f%%", d.CPUUsagePct()),
		memDisplay,
		fmt.Sprintf("%.1f%%", d.MemoryUsagePct()),
		gpuDisplay,
		gpuPct,
		gpuTypes,
		d.Partitions,
		d.Reason,
	}
}

// decorate colors the State cell and the three percent cells. Percent coloring
// uses the high-is-bad thresholds (90/70) from node_overview._format_pct.
func (n *Nodes) decorate(plain []string, styles theme.Styles) table.Row {
	row := make(table.Row, len(plain))
	copy(row, plain)

	if nodeStateColumnIndex >= 0 && nodeStateColumnIndex < len(row) {
		row[nodeStateColumnIndex] = colorState(plain[nodeStateColumnIndex], styles)
	}
	for _, idx := range []int{nodeCPUPctColumnIndex, nodeMemPctColumnIndex, nodeGPUPctColumnIndex} {
		if idx >= 0 && idx < len(row) {
			row[idx] = colorPctCell(plain[idx], styles)
		}
	}
	return row
}

// colorPctCell colors a "NN.N%" cell using the node usage thresholds, leaving a
// non-percent value (such as "N/A") unstyled.
func colorPctCell(cell string, styles theme.Styles) string {
	pct, ok := parsePercent(cell)
	if !ok {
		return cell
	}
	return styles.PctStyle(pct, theme.PctHighThreshold, theme.PctMidThreshold, false).Render(cell)
}

// CapturesInput reports whether the filter bar is open.
func (n *Nodes) CapturesInput() bool { return n.tbl.CapturesInput() }

// View renders the node table.
func (n *Nodes) View() string { return n.tbl.View() }

// ShortHelp returns the tab-local bindings.
func (n *Nodes) ShortHelp() []key.Binding { return n.tbl.ShortHelp() }

// FullHelp returns the expanded bindings.
func (n *Nodes) FullHelp() [][]key.Binding { return n.tbl.FullHelp() }
