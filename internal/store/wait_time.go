package store

import (
	"fmt"
	"sort"
	"strings"

	"github.com/pjhartout/stoei/internal/slurm"
)

// Wait-time formatting constants, mirroring wait_time.py.
const (
	secondsPerMinute        = 60.0
	minutesPerHour          = 60.0
	hoursPerDay             = 24.0
	integerDisplayThreshold = 10.0
)

// FormatWaitTime renders a duration in seconds as a compact human-readable string
// (e.g. "45s", "5m", "2.3h", "11h", "1.5d"). Values under the integer-display
// threshold keep one decimal place; larger values are integers. Ports
// wait_time.format_wait_time exactly.
func FormatWaitTime(seconds float64) string {
	if seconds < 0 {
		return "0s"
	}
	if seconds < secondsPerMinute {
		return fmt.Sprintf("%ds", int(seconds))
	}
	minutes := seconds / secondsPerMinute
	if minutes < minutesPerHour {
		return fmt.Sprintf("%dm", int(minutes))
	}
	hours := minutes / minutesPerHour
	if hours < hoursPerDay {
		if hours < integerDisplayThreshold {
			return fmt.Sprintf("%.1fh", hours)
		}
		return fmt.Sprintf("%dh", int(hours))
	}
	days := hours / hoursPerDay
	if days < integerDisplayThreshold {
		return fmt.Sprintf("%.1fd", days)
	}
	return fmt.Sprintf("%dd", int(days))
}

// PartitionWaitStats holds wait-time statistics for one partition. Ports
// wait_time.PartitionWaitStats.
type PartitionWaitStats struct {
	Partition     string
	JobCount      int
	MeanSeconds   float64
	MedianSeconds float64
	MinSeconds    float64
	MaxSeconds    float64
}

// CalculatePartitionWaitStats computes per-partition wait-time statistics from
// wait-time records. A record contributes its (start - submit) seconds to its
// partition only when both timestamps are valid and the difference is
// non-negative (slurm.WaitTimeSeconds enforces this). Partitions with no valid
// samples are omitted. Ports wait_time.calculate_partition_wait_stats.
func CalculatePartitionWaitStats(records []slurm.WaitTimeRecord) map[string]PartitionWaitStats {
	byPartition := map[string][]float64{}

	for _, r := range records {
		partition := strings.TrimSpace(r.Partition)
		if partition == "" {
			partition = "unknown"
		}
		secs, ok := slurm.WaitTimeSeconds(strings.TrimSpace(r.Submit), strings.TrimSpace(r.Start))
		if !ok {
			continue
		}
		byPartition[partition] = append(byPartition[partition], secs)
	}

	result := make(map[string]PartitionWaitStats, len(byPartition))
	for partition, waits := range byPartition {
		if len(waits) == 0 {
			continue
		}
		result[partition] = PartitionWaitStats{
			Partition:     partition,
			JobCount:      len(waits),
			MeanSeconds:   meanFloat(waits),
			MedianSeconds: medianFloat(waits),
			MinSeconds:    minFloat(waits),
			MaxSeconds:    maxFloat(waits),
		}
	}
	return result
}

// meanFloat returns the arithmetic mean of a non-empty slice.
func meanFloat(xs []float64) float64 {
	var sum float64
	for _, x := range xs {
		sum += x
	}
	return sum / float64(len(xs))
}

// medianFloat returns the median of a non-empty slice, averaging the two middle
// values for even lengths, matching Python's statistics.median.
func medianFloat(xs []float64) float64 {
	s := make([]float64, len(xs))
	copy(s, xs)
	sort.Float64s(s)
	n := len(s)
	mid := n / 2
	if n%2 == 1 {
		return s[mid]
	}
	return (s[mid-1] + s[mid]) / 2.0
}

// minFloat returns the smallest value of a non-empty slice.
func minFloat(xs []float64) float64 {
	m := xs[0]
	for _, x := range xs[1:] {
		if x < m {
			m = x
		}
	}
	return m
}

// maxFloat returns the largest value of a non-empty slice.
func maxFloat(xs []float64) float64 {
	m := xs[0]
	for _, x := range xs[1:] {
		if x > m {
			m = x
		}
	}
	return m
}
