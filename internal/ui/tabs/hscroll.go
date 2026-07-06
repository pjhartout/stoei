package tabs

import (
	"strings"

	"charm.land/bubbles/v2/table"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

// hscrollStep is the number of terminal columns one horizontal scroll key moves.
const hscrollStep = 8

// tableContentWidth is the full rendered width of the table: each visible cell
// is its column width plus the single left pad from tableStyles.
func tableContentWidth(cols []table.Column) int {
	w := 0
	for _, c := range cols {
		if c.Width > 0 {
			w += c.Width + 1
		}
	}
	return w
}

// clampHScroll clamps a horizontal offset into the scrollable range; when the
// content fits the pane the only valid offset is 0.
func clampHScroll(offset, contentWidth, paneWidth int) int {
	return min(max(offset, 0), max(0, contentWidth-paneWidth))
}

// hscrollWindow cuts every rendered line to the pane window
// [offset, offset+paneWidth). When the content already fits the pane the view
// passes through unchanged, so horizontal scrolling only engages on overflow.
func hscrollWindow(view string, offset, contentWidth, paneWidth int) string {
	if paneWidth <= 0 || contentWidth <= paneWidth {
		return view
	}
	lines := strings.Split(view, "\n")
	for i := range lines {
		lines[i] = ansi.Cut(lines[i], offset, offset+paneWidth)
	}
	return strings.Join(lines, "\n")
}

// fitTableColumns sizes each column to the longest of its minimum width, its
// title, and its cell values, re-applying the columns only when a width actually
// changes. Columns wider than the pane are fine — the view is windowed by
// hscrollWindow.
func fitTableColumns(t *table.Model, specs []column, rows [][]string, minWidth func(column) int) {
	cur := t.Columns()
	cols := make([]table.Column, len(specs))
	changed := len(cur) != len(specs)
	for i, c := range specs {
		w := lipgloss.Width(c.title)
		if minWidth != nil {
			if mw := minWidth(c); mw > w {
				w = mw
			}
		}
		for _, row := range rows {
			if i < len(row) {
				if cw := lipgloss.Width(row[i]); cw > w {
					w = cw
				}
			}
		}
		cols[i] = table.Column{Title: c.title, Width: w}
		if !changed && cur[i].Width != w {
			changed = true
		}
	}
	if changed {
		t.SetColumns(cols)
	}
}
