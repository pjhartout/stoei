package store

import (
	"strconv"
	"strings"

	"github.com/pjhartout/stoei/internal/slurm"
)

// JobEfficiency is the derived per-job hardware efficiency shown in the
// detail modal: measured usage related to the allocation it ran against. It
// is pure data; the ui layer only formats it.
type JobEfficiency struct {
	// Live reports the numbers are a snapshot of a running job (sstat) rather
	// than final accounting (sacct).
	Live bool
	// Sampled is false when the accounting gatherer recorded no samples,
	// e.g. a job that finished within the sampling interval.
	Sampled bool

	// CPUPercent is consumed CPU time over elapsed×allocated-CPUs. CPUKnown
	// is false when the allocation or elapsed time is unknown.
	CPUPercent  float64
	CPUKnown    bool
	CPUTimeSec  float64
	CPUAvailSec float64
	AllocCPUs   int

	// MaxRSSBytes is the peak resident set; MemPercent relates it to the
	// requested memory when that is known.
	MaxRSSBytes int64
	ReqMemBytes int64
	MemPercent  float64
	MemKnown    bool

	// GPUCount is the number of allocated GPUs; GPUUtilPercent is the
	// per-GPU average utilization (the accounted gres/gpuutil sum divided by
	// the count, clamped to 100). GPUIsMIG marks MIG slices, whose
	// utilization NVML cannot sample (it always accounts 0).
	GPUCount       int
	GPUIsMIG       bool
	GPUUtilPercent float64
	GPUUtilKnown   bool
	GPUMemBytes    int64
	GPUMemKnown    bool

	// Cumulative filesystem IO and its average rate over the elapsed time.
	DiskReadBytes    int64
	DiskWriteBytes   int64
	ReadBytesPerSec  float64
	WriteBytesPerSec float64
	ElapsedSec       float64
}

// DeriveJobEfficiency relates measured usage to the job's allocation. The
// sacct path carries its own allocation; the sstat path does not, so the
// scontrol detail fields the caller already holds fill the gaps (RunTime,
// NumCPUs, TRES/Gres).
func DeriveJobEfficiency(u JobUsage, fields map[string]string) JobEfficiency {
	eff := JobEfficiency{
		Live:           u.Source == "sstat",
		Sampled:        u.Sampled,
		CPUTimeSec:     u.CPUTimeSec,
		MaxRSSBytes:    u.MaxRSSBytes,
		GPUUtilKnown:   u.GPUUtilKnown,
		GPUMemBytes:    u.GPUMemBytes,
		GPUMemKnown:    u.GPUMemKnown,
		DiskReadBytes:  u.DiskReadBytes,
		DiskWriteBytes: u.DiskWriteBytes,
	}

	eff.ElapsedSec = u.ElapsedSec
	if eff.ElapsedSec == 0 {
		eff.ElapsedSec = slurm.ParseElapsedToSeconds(fields["RunTime"])
	}
	eff.AllocCPUs = u.AllocCPUs
	if eff.AllocCPUs == 0 {
		eff.AllocCPUs, _ = strconv.Atoi(strings.TrimSpace(fields["NumCPUs"]))
	}

	gpus := u.GPUs
	if len(gpus) == 0 {
		for _, src := range []string{fields["TRES"], fields["AllocTRES"], fields["ReqTRES"]} {
			if gpus = slurm.ParseGPUEntries(src); len(gpus) > 0 {
				break
			}
		}
		if len(gpus) == 0 {
			gpus = slurm.ParseGPUFromGres(fields["TresPerNode"])
		}
	}
	eff.GPUCount = slurm.CalculateTotalGPUs(gpus, true)
	for _, g := range gpus {
		if slurm.IsMIGType(g.Type) {
			eff.GPUIsMIG = true
		}
	}

	if eff.Sampled && eff.ElapsedSec > 0 && eff.AllocCPUs > 0 {
		eff.CPUAvailSec = eff.ElapsedSec * float64(eff.AllocCPUs)
		eff.CPUPercent = 100 * eff.CPUTimeSec / eff.CPUAvailSec
		eff.CPUKnown = true
	}

	// Newer scontrol emits AllocTRES/ReqTRES instead of the older bare TRES;
	// the allocation is preferred over the request (they differ when CPUs are
	// rounded up to whole cores).
	for _, src := range []string{fields["TRES"], fields["AllocTRES"], fields["ReqTRES"]} {
		if memGB := slurm.ParseTRESResources(src).MemoryGB; memGB > 0 {
			eff.ReqMemBytes = int64(memGB * (1 << 30))
			break
		}
	}
	if eff.Sampled && eff.ReqMemBytes > 0 && eff.MaxRSSBytes > 0 {
		eff.MemPercent = 100 * float64(eff.MaxRSSBytes) / float64(eff.ReqMemBytes)
		eff.MemKnown = true
	}

	if eff.GPUUtilKnown && eff.GPUCount > 0 {
		eff.GPUUtilPercent = u.GPUUtilPercent / float64(eff.GPUCount)
		if eff.GPUUtilPercent > 100 {
			eff.GPUUtilPercent = 100
		}
	}
	if eff.GPUIsMIG {
		// NVML cannot sample MIG slices; the accounted 0 is not a measurement.
		eff.GPUUtilKnown = false
	}

	if eff.ElapsedSec > 0 {
		eff.ReadBytesPerSec = float64(u.DiskReadBytes) / eff.ElapsedSec
		eff.WriteBytesPerSec = float64(u.DiskWriteBytes) / eff.ElapsedSec
	}
	return eff
}
