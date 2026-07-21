package store

import (
	"context"

	"github.com/pjhartout/stoei/internal/slurm"
)

// FakeClient is a test double for SlurmClient. Each method returns its canned
// value and, if the matching error field is set, that error instead. It records
// the job ID passed to JobDetail/CancelJob so tests can assert call arguments. A zero FakeClient returns empty data and nil
// errors for every method.
type FakeClient struct {
	RunningJobsData     []slurm.RunningJob
	AllUsersJobsData    []slurm.AllUsersJob
	HistoryJobsData     []slurm.HistoryJob
	HistoryStatsData    slurm.HistoryStats
	NodesData           []slurm.Node
	FairShareData       []slurm.FairShareEntry
	PendingPriorityData []slurm.PriorityEntry
	JobDetailData       slurm.JobDetail
	NodeDetailData      slurm.JobDetail
	CompletedJobData    slurm.HistoryJob
	CompletedJobFound   bool
	UsernameStr         string

	AvailableErr       error
	RunningJobsErr     error
	AllUsersJobsErr    error
	JobHistoryErr      error
	ClusterNodesErr    error
	FairShareErr       error
	PendingPriorityErr error
	JobDetailErr       error
	NodeDetailErr      error
	CancelJobErr       error
	UpdateJobErr       error
	HoldJobErr         error
	CompletedJobErr    error

	// LastJobDetailID is the job ID passed to the most recent JobDetail call.
	LastJobDetailID string
	// LastNodeDetailName is the node name passed to the most recent NodeDetail call.
	LastNodeDetailName string
	// LastCancelJobID is the job ID passed to the most recent CancelJob call.
	LastCancelJobID string
	// LastUpdateJobID, LastUpdateKey, and LastUpdateValue record the most recent
	// UpdateJob call.
	LastUpdateJobID string
	LastUpdateKey   string
	LastUpdateValue string
	// LastHoldJobID and LastHold record the most recent HoldJob call.
	LastHoldJobID string
	LastHold      bool
	// LastCompletedJobID is the job ID passed to the most recent CompletedJobRecord call.
	LastCompletedJobID string
	// LastHistoryDays is the day window passed to the most recent JobHistory call.
	LastHistoryDays int
	// AcctWarningMsg is returned (and cleared) by the next AcctWarning call.
	AcctWarningMsg string
	// AcctDueFlag is returned by AcctDue.
	AcctDueFlag bool
}

// AcctDue implements SlurmClient.
func (f *FakeClient) AcctDue() bool { return f.AcctDueFlag }

// AcctWarning implements SlurmClient, mirroring the real one-shot semantics.
func (f *FakeClient) AcctWarning() string {
	w := f.AcctWarningMsg
	f.AcctWarningMsg = ""
	return w
}

// Available implements SlurmClient.
func (f *FakeClient) Available(_ context.Context) error { return f.AvailableErr }

// Username implements SlurmClient.
func (f *FakeClient) Username() string { return f.UsernameStr }

// RunningJobs implements SlurmClient.
func (f *FakeClient) RunningJobs(_ context.Context) ([]slurm.RunningJob, error) {
	return f.RunningJobsData, f.RunningJobsErr
}

// AllUsersJobs implements SlurmClient.
func (f *FakeClient) AllUsersJobs(_ context.Context) ([]slurm.AllUsersJob, error) {
	return f.AllUsersJobsData, f.AllUsersJobsErr
}

// JobHistory implements SlurmClient.
func (f *FakeClient) JobHistory(_ context.Context, days int) ([]slurm.HistoryJob, slurm.HistoryStats, error) {
	f.LastHistoryDays = days
	return f.HistoryJobsData, f.HistoryStatsData, f.JobHistoryErr
}

// ClusterNodes implements SlurmClient.
func (f *FakeClient) ClusterNodes(_ context.Context) ([]slurm.Node, error) {
	return f.NodesData, f.ClusterNodesErr
}

// FairShare implements SlurmClient.
func (f *FakeClient) FairShare(_ context.Context) ([]slurm.FairShareEntry, error) {
	return f.FairShareData, f.FairShareErr
}

// PendingPriority implements SlurmClient.
func (f *FakeClient) PendingPriority(_ context.Context) ([]slurm.PriorityEntry, error) {
	return f.PendingPriorityData, f.PendingPriorityErr
}

// JobDetail implements SlurmClient.
func (f *FakeClient) JobDetail(_ context.Context, jobID string) (slurm.JobDetail, error) {
	f.LastJobDetailID = jobID
	return f.JobDetailData, f.JobDetailErr
}

// NodeDetail implements SlurmClient.
func (f *FakeClient) NodeDetail(_ context.Context, nodeName string) (slurm.JobDetail, error) {
	f.LastNodeDetailName = nodeName
	return f.NodeDetailData, f.NodeDetailErr
}

// CancelJob implements SlurmClient.
func (f *FakeClient) CancelJob(_ context.Context, jobID string) error {
	f.LastCancelJobID = jobID
	return f.CancelJobErr
}

// UpdateJob implements SlurmClient.
func (f *FakeClient) UpdateJob(_ context.Context, jobID, key, value string) error {
	f.LastUpdateJobID, f.LastUpdateKey, f.LastUpdateValue = jobID, key, value
	return f.UpdateJobErr
}

// HoldJob implements SlurmClient.
func (f *FakeClient) HoldJob(_ context.Context, jobID string, hold bool) error {
	f.LastHoldJobID, f.LastHold = jobID, hold
	return f.HoldJobErr
}

// CompletedJobRecord implements SlurmClient.
func (f *FakeClient) CompletedJobRecord(_ context.Context, jobID string) (slurm.HistoryJob, bool, error) {
	f.LastCompletedJobID = jobID
	return f.CompletedJobData, f.CompletedJobFound, f.CompletedJobErr
}

// Compile-time assertion that FakeClient satisfies the interface.
var _ SlurmClient = (*FakeClient)(nil)
