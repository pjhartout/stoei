package slurm

import (
	"context"
	"fmt"
	"strconv"
	"strings"
)

// JobUsage is the measured hardware consumption of one job, aggregated across
// its accounting steps. The .extern step is excluded everywhere: it tracks the
// allocation cgroup, reports a meaningless CPU time, and would poison every
// aggregate.
type JobUsage struct {
	// Source records where the numbers came from: "sacct" (slurmdbd, finished
	// jobs) or "sstat" (live slurmstepd samples, running jobs).
	Source string

	// ElapsedSec, AllocCPUs, and GPUs describe the allocation the usage is
	// measured against. Only the sacct path knows them (sstat reports usage,
	// not allocation); on the sstat path they are zero and the caller supplies
	// the allocation from the scontrol detail it already holds.
	ElapsedSec float64
	AllocCPUs  int
	GPUs       []GPUEntry

	// CPUTimeSec is the consumed CPU time (user+system, all tasks) in seconds.
	CPUTimeSec float64
	// MaxRSSBytes is the peak resident set across steps (PSS-based when the
	// cluster gathers with UsePss, so shared pages are not double-counted).
	MaxRSSBytes int64
	// DiskReadBytes and DiskWriteBytes are cumulative filesystem IO summed
	// across steps (the fs/disk TRES, i.e. /proc/<pid>/io byte counters).
	DiskReadBytes  int64
	DiskWriteBytes int64

	// GPUUtilPercent is the accounted average GPU utilization summed across
	// the allocated GPUs (gres/gpuutil): a 3-GPU job at full tilt reports up
	// to 300. Divide by the GPU count for a per-GPU average. Only valid when
	// GPUUtilKnown; NVML cannot sample MIG slices, which always account 0.
	GPUUtilPercent float64
	GPUUtilKnown   bool
	// GPUMemBytes is the peak accounted GPU memory (gres/gpumem).
	GPUMemBytes int64
	GPUMemKnown bool

	// Sampled reports whether any step carried usage samples. The gatherer
	// samples periodically, so a job that finished quickly may have none.
	Sampled bool
}

// sacctUsageFormat lists the per-job usage columns of the single-job sacct
// lookup. The job-level row carries the allocation and TotalCPU; step rows
// carry the measured TRES usage.
const sacctUsageFormat = "JobID,ElapsedRaw,AllocCPUS,TotalCPU,AllocTRES," +
	"MaxRSS,TRESUsageInTot,TRESUsageInAve,TRESUsageInMax,TRESUsageOutTot"

// sacctUsageFieldCount is the number of pipe-delimited columns sacctUsageFormat produces.
var sacctUsageFieldCount = strings.Count(sacctUsageFormat, ",") + 1

// sstatUsageFormat lists the usage columns of the live single-job sstat
// lookup. sstat has no allocation columns; the caller supplies those.
const sstatUsageFormat = "JobID,MaxRSS,TRESUsageInTot,TRESUsageInAve," +
	"TRESUsageInMax,TRESUsageOutTot"

// sstatUsageFieldCount is the number of pipe-delimited columns sstatUsageFormat produces.
var sstatUsageFieldCount = strings.Count(sstatUsageFormat, ",") + 1

// JobUsage returns the measured hardware usage of one job. A running job is
// sampled live via sstat, which slurmstepd answers only for the caller's own
// jobs; a finished job comes from slurmdbd via sacct. Both are single-job
// indexed lookups, so neither puts meaningful load on the controller or the
// accounting database. A nil error with Sampled=false means the lookup
// succeeded but no usage samples exist (yet).
func (c *Client) JobUsage(ctx context.Context, jobID string, running bool) (JobUsage, error) {
	normalized := NormalizeArrayJobID(jobID)
	if err := validateJobID(normalized); err != nil {
		return JobUsage{}, err
	}

	if running {
		out, err := c.runner.Run(ctx, "sstat", "-a", "-n", "-P", "-j", normalized, "-o", sstatUsageFormat)
		if err != nil {
			return JobUsage{}, fmt.Errorf("job %s usage: %w", jobID, err)
		}
		return ParseSstatUsage(normalized, string(out)), nil
	}

	out, err := c.runner.Run(ctx, "sacct", "-n", "-P", "-j", normalized, "-o", sacctUsageFormat)
	if err != nil {
		return JobUsage{}, fmt.Errorf("job %s usage: %w", jobID, err)
	}
	return ParseSacctUsage(normalized, string(out)), nil
}

// ParseSacctUsage parses pipe-delimited single-job sacct usage output into a
// JobUsage. Only the requested job's own rows are considered (an sacct query
// for an array base id lists every task; those rows are dropped rather than
// blended into a meaningless aggregate).
func ParseSacctUsage(jobID, raw string) JobUsage {
	u := JobUsage{Source: "sacct"}
	for _, line := range strings.Split(strings.TrimSpace(raw), "\n") {
		f := strings.SplitN(line, "|", sacctUsageFieldCount)
		if len(f) < sacctUsageFieldCount {
			continue
		}
		id := strings.TrimSpace(f[0])
		switch {
		case id == jobID:
			u.ElapsedSec = ParseElapsedToSeconds(f[1])
			u.AllocCPUs, _ = strconv.Atoi(strings.TrimSpace(f[2]))
			u.CPUTimeSec = ParseElapsedToSeconds(f[3])
			u.GPUs = ParseGPUEntries(f[4])
		case strings.HasPrefix(id, jobID+"."):
			if strings.HasSuffix(id, ".extern") {
				continue
			}
			mergeStepUsage(&u, f[5], f[6], f[7], f[8], f[9])
		}
	}
	return u
}

// ParseSstatUsage parses pipe-delimited single-job sstat output into a
// JobUsage. CPU time comes from the cpu entry of TRESUsageInTot because sstat
// has no TotalCPU column.
func ParseSstatUsage(jobID, raw string) JobUsage {
	u := JobUsage{Source: "sstat"}
	for _, line := range strings.Split(strings.TrimSpace(raw), "\n") {
		f := strings.SplitN(line, "|", sstatUsageFieldCount)
		if len(f) < sstatUsageFieldCount {
			continue
		}
		id := strings.TrimSpace(f[0])
		if !strings.HasPrefix(id, jobID+".") || strings.HasSuffix(id, ".extern") {
			continue
		}
		mergeStepUsage(&u, f[1], f[2], f[3], f[4], f[5])
		u.CPUTimeSec += ParseElapsedToSeconds(parseTRESPairs(f[2])["cpu"])
	}
	return u
}

// mergeStepUsage folds one step's usage columns into the aggregate: peaks
// (RSS, GPU memory, GPU utilization) take the max across steps, cumulative IO
// sums, and any non-empty usage column marks the job as sampled.
func mergeStepUsage(u *JobUsage, maxRSS, inTot, inAve, inMax, outTot string) {
	if strings.TrimSpace(maxRSS) != "" || strings.TrimSpace(inAve) != "" {
		u.Sampled = true
	}
	if rss := parseSizeBytes(maxRSS); rss > u.MaxRSSBytes {
		u.MaxRSSBytes = rss
	}
	u.DiskReadBytes += parseSizeBytes(parseTRESPairs(inTot)["fs/disk"])
	u.DiskWriteBytes += parseSizeBytes(parseTRESPairs(outTot)["fs/disk"])

	ave := parseTRESPairs(inAve)
	if v, ok := ave["gres/gpuutil"]; ok {
		util, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
		if err == nil {
			u.GPUUtilKnown = true
			if util > u.GPUUtilPercent {
				u.GPUUtilPercent = util
			}
		}
	}
	// Peak GPU memory prefers the max column but falls back to the average
	// column, which some gatherers populate identically.
	mem := parseTRESPairs(inMax)["gres/gpumem"]
	if strings.TrimSpace(mem) == "" {
		mem = ave["gres/gpumem"]
	}
	if strings.TrimSpace(mem) != "" {
		u.GPUMemKnown = true
		if b := parseSizeBytes(mem); b > u.GPUMemBytes {
			u.GPUMemBytes = b
		}
	}
}

// parseTRESPairs splits a TRES usage string such as
// "cpu=00:05:07,fs/disk=21089845644,gres/gpuutil=43,mem=8836674K" into a
// key→value map. Malformed entries are skipped; an empty string yields an
// empty map.
func parseTRESPairs(s string) map[string]string {
	pairs := map[string]string{}
	for _, part := range strings.Split(s, ",") {
		k, v, ok := strings.Cut(part, "=")
		if !ok {
			continue
		}
		pairs[strings.TrimSpace(k)] = strings.TrimSpace(v)
	}
	return pairs
}

// parseSizeBytes parses a Slurm size string into bytes: a bare number is
// bytes, and a trailing K/M/G/T scales by binary multiples ("8836674K",
// "20112.84M"). Empty or malformed input yields 0.
func parseSizeBytes(s string) int64 {
	s = strings.TrimSpace(s)
	if s == "" {
		return 0
	}
	mult := float64(1)
	switch s[len(s)-1] {
	case 'K', 'k':
		mult = 1 << 10
	case 'M', 'm':
		mult = 1 << 20
	case 'G', 'g':
		mult = 1 << 30
	case 'T', 't':
		mult = 1 << 40
	}
	if mult != 1 {
		s = s[:len(s)-1]
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil || v < 0 {
		return 0
	}
	return int64(v * mult)
}
