package store

import (
	"sort"
	"strings"

	"github.com/pjhartout/stoei/internal/slurm"
)

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
