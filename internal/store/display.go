package store

import (
	"strings"

	"github.com/pjhartout/stoei/internal/slurm"
)

// ShortGPULabel renders a GPU type for display, shortening MIG profiles (e.g.
// "H100_PCIE_1G.10GB" -> "1g.10gb"). It wraps slurm.ShortGPULabel so the UI layer
// can reach it without importing slurm directly.
func ShortGPULabel(typ string) string {
	return slurm.ShortGPULabel(typ)
}

// IsMIGType reports whether a GPU type names a MIG slice. It wraps
// slurm.IsMIGType so the UI layer can reach it without importing slurm directly.
func IsMIGType(typ string) bool {
	return slurm.IsMIGType(typ)
}

// Fair-share color thresholds shared by the Priority tab and the user/account
// detail modals so the two views never drift.
const (
	// FairShareSuccessThreshold is the fair-share factor at or above which the
	// value is colored as healthy ("success").
	FairShareSuccessThreshold = 0.5
	// FairShareWarningThreshold is the fair-share factor at or above which the
	// value is colored as a warning; below it the value is colored as an error.
	FairShareWarningThreshold = 0.2
)

// StateRole classifies a Slurm job or node state into a semantic color role —
// "success", "warning", "error", "muted", or "" for the default — so the tables
// and the detail modals color a given state identically (previously each
// re-implemented the mapping and they drifted). It uppercases the state and uses
// its leading whitespace-delimited token, so "RUNNING by 123" classifies as
// RUNNING. Both long forms and squeue's abbreviations are recognized.
func StateRole(state string) string {
	s := strings.ToUpper(strings.TrimSpace(state))
	if i := strings.IndexByte(s, ' '); i >= 0 {
		s = s[:i]
	}
	switch s {
	case "RUNNING", "R", "COMPLETING", "CG", "COMPLETED", "CD", "IDLE":
		return "success"
	case "PENDING", "PD", "PREEMPTED", "PR", "SUSPENDED", "S", "REQUEUED", "RQ",
		"ALLOCATED", "ALLOC", "MIXED", "MIX", "CONFIGURING", "CF", "DRAINING":
		return "warning"
	case "FAILED", "F", "TIMEOUT", "TO", "NODE_FAIL", "NF", "OUT_OF_MEMORY", "OOM",
		"BOOT_FAIL", "BF", "DOWN", "DRAIN", "DRAINED":
		return "error"
	case "CANCELLED", "CA", "CANCELED":
		return "muted"
	default:
		return ""
	}
}
