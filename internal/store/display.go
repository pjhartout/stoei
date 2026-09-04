package store

import (
	"fmt"
	"strconv"
	"strings"
	"time"

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

// FormatPercent renders an sshare 0..1 fraction as a percentage of the cluster
// ("2.08%", "26.1%"), with two decimals below 10% so small shares stay
// distinguishable. Unparseable input yields "".
func FormatPercent(fraction string) string {
	v, err := strconv.ParseFloat(strings.TrimSpace(fraction), 64)
	if err != nil {
		return ""
	}
	pct := 100 * v
	if pct < 10 {
		return fmt.Sprintf("%.2f%%", pct)
	}
	return fmt.Sprintf("%.1f%%", pct)
}

// FormatRatio renders a usage/share ratio as a multiplier ("12.5×", "0.81×"),
// with an extra decimal below 1 where the difference matters. An undefined or
// zero ratio renders empty: the status beside it already says "Unused".
func FormatRatio(ratio float64, ok bool) string {
	switch {
	case !ok || ratio == 0:
		return ""
	case ratio < 1:
		return fmt.Sprintf("%.2f×", ratio)
	default:
		return fmt.Sprintf("%.1f×", ratio)
	}
}

// FormatRank renders "147 of 171 active users (bottom 15%)": the dense rank plus
// a percentile, counted from the top for the better half and from the bottom
// otherwise, never smaller than 1%.
func FormatRank(rank, total int, noun string) string {
	pct := 100 * rank / total
	var where string
	if pct <= 50 {
		where = fmt.Sprintf("top %d%%", max(pct, 1))
	} else {
		where = fmt.Sprintf("bottom %d%%", max(100-pct, 1))
	}
	return fmt.Sprintf("%d of %d %s (%s)", rank, total, noun, where)
}

// FormatDays renders a duration in whole days ("51d"), whole hours below a day
// ("18h"), and "<1h" below an hour, rounding to the nearest unit.
func FormatDays(d time.Duration) string {
	if d >= 24*time.Hour {
		return fmt.Sprintf("%dd", int64((d+12*time.Hour)/(24*time.Hour)))
	}
	if d < time.Hour {
		return "<1h"
	}
	return fmt.Sprintf("%dh", int64((d+30*time.Minute)/time.Hour))
}

// FormatQueue renders a 1-based queue position as "#142/176".
func FormatQueue(pos, total int) string {
	return fmt.Sprintf("#%d/%d", pos, total)
}

// FormatBreakdown lists a job's non-zero weighted factors largest first, as
// "FairShare 658033 · Partition 100 · JobSize 5 · Age 1", so a row explains
// where its priority comes from.
func FormatBreakdown(f PriorityFactors) string {
	contributions := f.Contributions()
	parts := make([]string, len(contributions))
	for i, c := range contributions {
		parts[i] = fmt.Sprintf("%s %d", c.Name, c.Value)
	}
	return strings.Join(parts, " · ")
}

// FormatStanding phrases a user's standing in one partition's queue: "best at
// #3 of 4 · 2 ahead of you · 2 jobs", or "first in line" when nothing is ahead.
// The job count is only mentioned when it is more than one.
func FormatStanding(s PartitionStanding) string {
	ahead := fmt.Sprintf("%d ahead of you", s.Best.Partition-1)
	if s.Best.Partition == 1 {
		ahead = "first in line"
	}
	text := fmt.Sprintf("best at #%d of %d · %s", s.Best.Partition, s.Best.PartitionTotal, ahead)
	if s.Jobs > 1 {
		text += fmt.Sprintf(" · %d jobs", s.Jobs)
	}
	return text
}

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
