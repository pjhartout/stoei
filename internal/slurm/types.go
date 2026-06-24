// Package slurm builds Slurm command invocations and parses their output into
// plain Go structs. It is the lowest layer of the application and imports nothing
// from the UI or store packages. All scheduler IO goes through a Runner so the
// parsers can be exercised against golden fixtures with no real subprocess.
package slurm

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
	TRES      string
}

// UserJob is one RUNNING or PENDING job for a single user, as returned by the
// fixed-width "squeue -O" command without the UserName column and parsed by
// ParseUserJobs.
type UserJob struct {
	ID        string
	Name      string
	Partition string
	State     string
	Time      string
	NumNodes  string
	NodeList  string
	TRES      string
}

// RunningJob is one row of the pipe-delimited "squeue -o" output used for the
// current user's running/pending jobs. Fields follow the format string
// "%.30i|%.50j|%.8T|%.10M|%.4D|%.12R|%.19V|%.19S" (id, name, state, time, nodes,
// nodelist, submit, start). Raw holds every pipe-separated field so consumers
// can read columns the struct does not name explicitly.
type RunningJob struct {
	ID         string
	Name       string
	State      string
	Time       string
	Nodes      string
	NodeList   string
	SubmitTime string
	StartTime  string
	Raw        []string
}

// HistoryJob is one job from the sacct history query. It mirrors the ten-column
// sacct format "JobID,JobName,State,Restart,Elapsed,ExitCode,NodeList,Submit,
// Start,End". Raw holds every pipe-separated field of the row.
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
	Raw      []string
}

// HistoryStats are the aggregate requeue counters derived from a job-history
// query, returned alongside the parsed jobs by ParseHistory.
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

// PriorityEntry is one pending job's priority breakdown from "sprio", holding its
// nine columns.
type PriorityEntry struct {
	JobID     string
	User      string
	Account   string
	Priority  string
	Age       string
	FairShare string
	JobSize   string
	Partition string
	QOS       string
}
