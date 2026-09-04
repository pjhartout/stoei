// Package slurm builds Slurm command invocations and parses their output into
// plain Go structs. It is the lowest layer of the application and imports nothing
// from the UI or store packages. All scheduler IO goes through a Runner so the
// parsers can be exercised against golden fixtures with no real subprocess.
package slurm

import (
	"sort"
	"time"
)

// GPUEntry is a single GPU allocation parsed from a TRES or Gres string. Type is
// the GPU model (for example "h200" or "A100") or the literal "gpu" for generic
// entries that carry no model; Count is the number of GPUs of that type.
type GPUEntry struct {
	Type  string
	Count int
}

// AllUsersJob is one RUNNING or PENDING job across all users, as returned by the
// fixed-width "squeue -O" command and parsed by ParseAllUsersJobs.
type AllUsersJob struct {
	ID        string
	Name      string
	User      string
	Partition string
	State     string
	Time      string
	NumNodes  string
	NodeList  string
	Reason    string
	TRES      string
}

// RunningJob is one row of the pipe-delimited "squeue -o" output used for the
// current user's running/pending jobs. Fields follow the format string
// "%i|%j|%T|%M|%D|%R|%V|%S" (id, name, state, time, nodes, nodelist, submit,
// start).
type RunningJob struct {
	ID         string
	Name       string
	State      string
	Time       string
	Nodes      string
	NodeList   string
	SubmitTime string
	StartTime  string
}

// HistoryJob is one row of the job-history view, derived from the journal's
// ControllerJob records by HistoryJobsFor (slurmdbd/sacct are never queried).
type HistoryJob struct {
	ID       string
	Name     string
	State    string
	Restart  string
	Elapsed  string
	ExitCode string
	NodeList string
	Submit   string
	Start    string
	End      string
	// StdOut and StdErr are the journal-recorded log-file paths; "" when the
	// scheduler reported none or the record predates path capture.
	StdOut string
	StdErr string
}

// HistoryStats are the aggregate requeue counters derived from journal jobs by
// HistoryJobsFor, alongside the history rows.
type HistoryStats struct {
	TotalJobs     int
	TotalRequeues int
	MaxRequeues   int
}

// Node is one cluster node parsed from "scontrol show nodes" output. Fields holds
// every Key=Value pair scontrol reported for the node; the named fields are
// convenience accessors lifted from Fields for the values consumers read most.
type Node struct {
	Name      string
	State     string
	CPUTot    string
	CPUAlloc  string
	RealMem   string
	AllocMem  string
	CfgTRES   string
	AllocTRES string
	Gres      string
	Reason    string
	Fields    map[string]string
}

// JobDetail is the parsed Key=Value view of a single job from "scontrol show
// jobid". Fields holds the complete key/value map; Source records which command
// produced it ("scontrol").
type JobDetail struct {
	Fields map[string]string
	Source string
}

// FairShareEntry is one row of "sshare" output, holding its eight columns. An
// entry with an empty User is an account-level row; otherwise it is a user-level
// row.
type FairShareEntry struct {
	Account      string
	User         string
	RawShares    string
	NormShares   string
	RawUsage     string
	NormUsage    string
	EffectvUsage string
	FairShare    string
}

// IsAccount reports whether the entry is an account-level row (no User set).
func (e FairShareEntry) IsAccount() bool { return e.User == "" }

// PriorityEntry is one pending job's row from "sprio": its identity (job, user,
// account, partition, QOS), the total scheduling priority, and the weighted
// contribution of every multifactor component. A job submitted to several
// partitions yields one entry per partition.
type PriorityEntry struct {
	JobID     string
	User      string
	Account   string
	Partition string
	QOS       string
	Priority  int64
	Factors   PriorityFactors
}

// PriorityFactors are the weighted priority components sprio reports for a job.
// Each is already multiplied by its cluster weight, so the components sum to the
// job's priority (Nice is negative for a niced job). TRES is the sum of the
// per-TRES weighted values.
type PriorityFactors struct {
	Age       int64
	FairShare int64
	JobSize   int64
	Partition int64
	QOS       int64
	TRES      int64
	Assoc     int64
	Site      int64
	Nice      int64
}

// PriorityFactor is one named, weighted priority component.
type PriorityFactor struct {
	Name  string
	Value int64
}

// Add accumulates other into f component-wise, for summing factors across a set
// of jobs.
func (f *PriorityFactors) Add(other PriorityFactors) {
	f.Age += other.Age
	f.FairShare += other.FairShare
	f.JobSize += other.JobSize
	f.Partition += other.Partition
	f.QOS += other.QOS
	f.TRES += other.TRES
	f.Assoc += other.Assoc
	f.Site += other.Site
	f.Nice += other.Nice
}

// Contributions returns the non-zero components ordered by absolute value
// descending, so a breakdown reads most-important-first. A job with every
// component at zero yields nil.
func (f PriorityFactors) Contributions() []PriorityFactor {
	all := []PriorityFactor{
		{"FairShare", f.FairShare}, {"Age", f.Age}, {"JobSize", f.JobSize},
		{"Partition", f.Partition}, {"QOS", f.QOS}, {"TRES", f.TRES},
		{"Assoc", f.Assoc}, {"Site", f.Site}, {"Nice", f.Nice},
	}
	out := all[:0]
	for _, c := range all {
		if c.Value != 0 {
			out = append(out, c)
		}
	}
	if len(out) == 0 {
		return nil
	}
	sort.SliceStable(out, func(i, j int) bool { return abs64(out[i].Value) > abs64(out[j].Value) })
	return out
}

// abs64 returns the absolute value of v.
func abs64(v int64) int64 {
	if v < 0 {
		return -v
	}
	return v
}

// PriorityConfig is the controller's job-priority configuration from "scontrol
// show config": the plugin, each factor's weight, and the two time constants
// that govern how the age and fair-share factors evolve.
type PriorityConfig struct {
	// Type is the PriorityType plugin, e.g. "priority/multifactor" or
	// "priority/basic" (FIFO).
	Type    string
	Weights PriorityWeights
	// MaxAge is PriorityMaxAge: the queue time at which the age factor reaches
	// its full weight.
	MaxAge time.Duration
	// DecayHalfLife is PriorityDecayHalfLife: how long it takes recorded usage
	// to halve. Zero means usage never decays.
	DecayHalfLife time.Duration
	FavorSmall    bool
}

// PriorityWeights are the PriorityWeight* multipliers. TRES keeps the raw
// "cpu=1000,gres/gpu=2000" list ("" when unset) because it is per-resource.
type PriorityWeights struct {
	Age       int64
	Assoc     int64
	FairShare int64
	JobSize   int64
	Partition int64
	QOS       int64
	TRES      string
}

// Multifactor reports whether the multifactor plugin is active; any other plugin
// (priority/basic) schedules jobs in submission order and has no factors.
func (c PriorityConfig) Multifactor() bool {
	return c.Type == "priority/multifactor"
}
