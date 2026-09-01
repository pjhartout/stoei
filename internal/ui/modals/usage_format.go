package modals

import (
	"fmt"
	"strings"

	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// usageForeignNote is the section body shown for another user's running job:
// slurmstepd answers live usage queries only for one's own jobs.
const usageForeignNote = "only visible to the job's owner while it runs; " +
	"recorded to accounting on completion"

// formatUsageSection renders the Efficiency section appended below the
// scontrol fields in the job-detail modal: measured CPU efficiency, peak RAM,
// GPU utilization/memory, and cumulative disk IO with average rates.
func formatUsageSection(eff store.JobEfficiency, styles theme.Styles) string {
	title := " Efficiency "
	if eff.Live {
		title = " Efficiency (live) "
	}
	lines := []string{"", styles.Title.Render(title)}

	if !eff.Sampled {
		note := "job finished before usage was sampled"
		if eff.Live {
			note = "no usage samples recorded yet"
		}
		lines = append(lines, "  "+styles.Subtle.Render(note))
		return strings.Join(lines, "\n")
	}

	if eff.CPUKnown {
		detail := fmt.Sprintf("(%s CPU of %s across %d CPUs)",
			fmtDurShort(eff.CPUTimeSec), fmtDurShort(eff.CPUAvailSec), eff.AllocCPUs)
		lines = append(lines, usageLine("CPU efficiency",
			pctStyle(eff.CPUPercent, styles).Render(fmtPct(eff.CPUPercent))+" "+styles.Subtle.Render(detail), styles))
	}

	if eff.MaxRSSBytes > 0 {
		val := styles.Text.Bold(true).Render(fmtBytes(eff.MaxRSSBytes))
		if eff.MemKnown {
			val += " " + styles.Subtle.Render(fmt.Sprintf("(%s of %s requested)",
				fmtPct(eff.MemPercent), fmtBytes(eff.ReqMemBytes)))
		}
		lines = append(lines, usageLine("Peak RAM", val, styles))
	}

	if eff.GPUCount > 0 {
		switch {
		case eff.GPUIsMIG:
			lines = append(lines, usageLine("GPU utilization",
				styles.Subtle.Render("n/a (MIG slice — not measurable)"), styles))
		case eff.GPUUtilKnown:
			detail := "(avg)"
			if eff.GPUCount > 1 {
				detail = fmt.Sprintf("(avg across %d GPUs)", eff.GPUCount)
			}
			lines = append(lines, usageLine("GPU utilization",
				pctStyle(eff.GPUUtilPercent, styles).Render(fmtPct(eff.GPUUtilPercent))+" "+styles.Subtle.Render(detail), styles))
		default:
			lines = append(lines, usageLine("GPU utilization",
				styles.Subtle.Render("no data"), styles))
		}
		if eff.GPUMemKnown {
			lines = append(lines, usageLine("GPU memory peak",
				styles.Text.Bold(true).Render(fmtBytes(eff.GPUMemBytes)), styles))
		}
	}

	lines = append(lines,
		usageLine("Disk read", ioValue(eff.DiskReadBytes, eff.ReadBytesPerSec, styles), styles),
		usageLine("Disk written", ioValue(eff.DiskWriteBytes, eff.WriteBytesPerSec, styles), styles),
	)
	return strings.Join(lines, "\n")
}

// formatUsageNote renders the Efficiency header with a single subdued note in
// place of metrics.
func formatUsageNote(note string, styles theme.Styles) string {
	return "\n" + styles.Title.Render(" Efficiency ") + "\n  " + styles.Subtle.Render(note)
}

// usageLine renders one dotted-leader line in the detail modal's field style.
func usageLine(label, value string, styles theme.Styles) string {
	return "  " + styles.Subtle.Render(dottedLabel(label, labelWidth)) + " " + value
}

// ioValue renders a cumulative byte count with its average rate.
func ioValue(bytes int64, rate float64, styles theme.Styles) string {
	val := styles.Text.Bold(true).Render(fmtBytes(bytes))
	if rate > 0 {
		val += " " + styles.Subtle.Render(fmt.Sprintf("(%s/s avg)", fmtBytes(int64(rate))))
	}
	return val
}

// pctStyle colors an efficiency percentage: healthy utilization renders
// success, middling renders warning, poor renders error.
func pctStyle(pct float64, styles theme.Styles) lipgloss.Style {
	switch {
	case pct >= 70:
		return styles.Success
	case pct >= 30:
		return styles.Warning
	default:
		return styles.Error
	}
}

// fmtPct renders a percentage with one decimal below 10% and none above, so
// tiny values do not collapse to "0%".
func fmtPct(pct float64) string {
	if pct < 10 {
		return fmt.Sprintf("%.1f%%", pct)
	}
	return fmt.Sprintf("%.0f%%", pct)
}

// fmtBytes renders a byte count in binary units with one decimal.
func fmtBytes(b int64) string {
	const unit = 1024
	if b < unit {
		return fmt.Sprintf("%dB", b)
	}
	val := float64(b)
	for _, suffix := range []string{"K", "M", "G", "T", "P"} {
		val /= unit
		if val < unit {
			return fmt.Sprintf("%.1f%s", val, suffix)
		}
	}
	return fmt.Sprintf("%.1fE", val/unit)
}

// fmtDurShort renders a duration in seconds compactly with its two most
// significant units: "2d23h", "4h44m", "2m51s", "45s".
func fmtDurShort(sec float64) string {
	s := int64(sec)
	switch {
	case s >= 86400:
		return fmt.Sprintf("%dd%dh", s/86400, s%86400/3600)
	case s >= 3600:
		return fmt.Sprintf("%dh%dm", s/3600, s%3600/60)
	case s >= 60:
		return fmt.Sprintf("%dm%ds", s/60, s%60)
	default:
		return fmt.Sprintf("%ds", s)
	}
}
