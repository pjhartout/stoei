package tabs

import (
	"strconv"
	"strings"

	"charm.land/lipgloss/v2"

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

// stateRole classifies a job/node state into one of the semantic color roles.
type stateRole int

const (
	// roleDefault uses the default foreground.
	roleDefault stateRole = iota
	// roleSuccess is green (running/active).
	roleSuccess
	// roleWarning is yellow (pending/transitional).
	roleWarning
	// roleError is red (failed/timeout).
	roleError
	// roleMuted is dimmed (cancelled).
	roleMuted
)

// stateRoles maps the leading state token to its color role. Ports the
// state_map in colors.ThemeColors.state_color, covering both job and node states.
var stateRoles = map[string]stateRole{
	"RUNNING":       roleSuccess,
	"COMPLETING":    roleSuccess,
	"COMPLETED":     roleSuccess,
	"PENDING":       roleWarning,
	"PREEMPTED":     roleWarning,
	"SUSPENDED":     roleWarning,
	"REQUEUED":      roleWarning,
	"FAILED":        roleError,
	"TIMEOUT":       roleError,
	"NODE_FAIL":     roleError,
	"OUT_OF_MEMORY": roleError,
	"CANCELLED":     roleMuted,
	"IDLE":          roleSuccess,
	"ALLOCATED":     roleWarning,
	"MIXED":         roleWarning,
	"DOWN":          roleError,
	"DRAIN":         roleError,
	"DRAINED":       roleError,
}

// roleFor returns the color role for a state string. It uppercases and takes the
// leading token so values like "RUNNING by 12345" classify by "RUNNING",
// matching colors.state_color's split()[0] handling.
func roleFor(state string) stateRole {
	upper := strings.ToUpper(strings.TrimSpace(state))
	if i := strings.IndexByte(upper, ' '); i >= 0 {
		upper = upper[:i]
	}
	if role, ok := stateRoles[upper]; ok {
		return role
	}
	return roleDefault
}

// styleForRole returns the lipgloss style for a color role from the active
// styles.
func styleForRole(role stateRole, styles theme.Styles) lipgloss.Style {
	switch role {
	case roleSuccess:
		return styles.Success
	case roleWarning:
		return styles.Warning
	case roleError:
		return styles.Error
	case roleMuted:
		return styles.Muted
	default:
		return styles.Text
	}
}

// colorState renders a state string with its theme color applied, for display in
// the State column.
func colorState(state string, styles theme.Styles) string {
	return styleForRole(roleFor(state), styles).Render(state)
}
