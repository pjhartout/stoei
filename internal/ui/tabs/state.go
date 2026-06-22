package tabs

import (
	"strconv"
	"strings"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// parsePercent parses a "NN.N%" cell into its float value. It returns ok=false
// for cells that are not percentages (for example "N/A"), so callers can leave
// them unstyled.
func parsePercent(cell string) (float64, bool) {
	s := strings.TrimSpace(cell)
	if !strings.HasSuffix(s, "%") {
		return 0, false
	}
	v, err := strconv.ParseFloat(strings.TrimSuffix(s, "%"), 64)
	if err != nil {
		return 0, false
	}
	return v, true
}

// colorState renders a state string with its theme color applied, for display in
// the State column. The state -> color-role classification lives in
// store.StateRole so the tables and detail modals stay consistent. The colored
// cell ends with a foreground-only reset so a selected row's background highlight
// bar is preserved across it rather than being cleared mid-line by a full reset.
func colorState(state string, styles theme.Styles) string {
	return foregroundOnlyReset(styles.StateRoleStyle(store.StateRole(state)).Render(state))
}

// foregroundOnlyReset swaps the trailing SGR reset that lipgloss appends to a
// styled string for a foreground-only reset (ESC[39m), leaving any active
// background untouched. This keeps a selected-row highlight continuous across a
// colored cell, which a full reset (ESC[0m) would otherwise clear.
func foregroundOnlyReset(s string) string {
	for _, reset := range []string{"\x1b[0m", "\x1b[m"} {
		if strings.HasSuffix(s, reset) {
			return s[:len(s)-len(reset)] + "\x1b[39m"
		}
	}
	return s
}
