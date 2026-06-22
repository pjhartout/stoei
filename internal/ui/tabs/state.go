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
// store.StateRole so the tables and detail modals stay consistent.
func colorState(state string, styles theme.Styles) string {
	return styles.StateRoleStyle(store.StateRole(state)).Render(state)
}
