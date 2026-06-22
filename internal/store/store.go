package store

import (
	"time"

	"github.com/pjhartout/stoei/internal/slurm"
)

// State is the load state of a single Store section. It mirrors the four-state
// lifecycle the UI renders (spinner / data / error badge).
type State int

const (
	// StateIdle means the section has never been fetched.
	StateIdle State = iota
	// StateLoading means a fetch is in flight.
	StateLoading
	// StateLoaded means the section holds valid data from a completed fetch.
	StateLoaded
	// StateError means the most recent fetch failed; prior data (if any) is kept.
	StateError
)

// String returns the lowercase state name, matching the Python load-state labels.
func (s State) String() string {
	switch s {
	case StateIdle:
		return "idle"
	case StateLoading:
		return "loading"
	case StateLoaded:
		return "loaded"
	case StateError:
		return "error"
	default:
		return "unknown"
	}
}

// Section identifies a Store dataset for generation tracking and state queries.
type Section int

const (
	// SectionRunningJobs is the current user's running/pending jobs.
	SectionRunningJobs Section = iota
	// SectionHistory is the current user's job history plus requeue stats.
	SectionHistory
	// SectionNodes is the cluster node list.
	SectionNodes
	// SectionAllUsersJobs is every running/pending job across all users.
	SectionAllUsersJobs
	// SectionFairShare is the sshare fair-share data.
	SectionFairShare
	// SectionPendingPrio is the sprio pending-priority data.
	SectionPendingPrio
	// SectionEnergy is the energy-history data.
	SectionEnergy
	// SectionWaitTime is the wait-time history data.
	SectionWaitTime
	// numSections is the count of sections; keep last.
	numSections
)

// String returns a stable identifier for the section, used as the health key and
// in toast messages.
func (s Section) String() string {
	switch s {
	case SectionRunningJobs:
		return "running_jobs"
	case SectionHistory:
		return "history"
	case SectionNodes:
		return "nodes"
	case SectionAllUsersJobs:
		return "all_users_jobs"
	case SectionFairShare:
		return "fair_share"
	case SectionPendingPrio:
		return "pending_priority"
	case SectionEnergy:
		return "energy"
	case SectionWaitTime:
		return "wait_time"
	default:
		return "unknown"
	}
}

// Meta is the per-section load metadata common to every dataset.
type Meta struct {
	State       State
	LastUpdated time.Time
	Err         error
}

// Store holds every Slurm dataset plus its derived cluster statistics. Each
// dataset carries a Meta (state/last-updated/error). A per-section request
// generation enforces invariant I4 centrally: a setter applies its result only
// when the result's generation is at least the section's current generation, so
// a slow superseded fetch can never overwrite a newer one.
//
// The Store is plain data. It is mutated only by its setters (and NextGen),
// which the root model's Update calls on the main loop goroutine — never from a
// fetch goroutine and never from View.
type Store struct {
	gen [numSections]uint64

	RunningJobs     []slurm.RunningJob
	RunningJobsMeta Meta

	HistoryJobs  []slurm.HistoryJob
	HistoryStats slurm.HistoryStats
	HistoryMeta  Meta

	Nodes     []slurm.Node
	NodesMeta Meta

	AllUsersJobs     []slurm.AllUsersJob
	AllUsersJobsMeta Meta

	FairShare     []slurm.FairShareEntry
	FairShareMeta Meta

	PendingPrio     []slurm.PriorityEntry
	PendingPrioMeta Meta

	Energy     []slurm.EnergyRecord
	EnergyMeta Meta

	WaitTime     []slurm.WaitTimeRecord
	WaitTimeMeta Meta

	// ClusterStats is recomputed from Nodes, AllUsersJobs, and WaitTime whenever
	// any of those three sections is applied.
	ClusterStats ClusterStats

	// now is the injectable clock used to stamp LastUpdated; tests override it so
	// "updated N ago" is deterministic. It defaults to time.Now.
	now func() time.Time
}

// New returns an empty Store with every section in StateIdle and the clock set
// to time.Now.
func New() *Store {
	return &Store{now: time.Now, ClusterStats: newClusterStats()}
}

// SetClock overrides the Store's time source. Tests use it to make LastUpdated
// deterministic.
func (s *Store) SetClock(now func() time.Time) { s.now = now }

// clock returns the current time using the injected clock, defaulting to
// time.Now if unset (a zero-value Store from a struct literal).
func (s *Store) clock() time.Time {
	if s.now == nil {
		return time.Now()
	}
	return s.now()
}

// NextGen bumps and returns the request generation for a section. The caller
// dispatches a fetch tagged with the returned value; the matching setter later
// drops any result whose generation is older than the section's current one.
// Call this exactly once per dispatch (I4).
func (s *Store) NextGen(section Section) uint64 {
	s.gen[section]++
	return s.gen[section]
}

// Gen returns the section's current request generation without bumping it.
func (s *Store) Gen(section Section) uint64 { return s.gen[section] }

// State returns the load state of a section.
func (s *Store) State(section Section) State {
	switch section {
	case SectionRunningJobs:
		return s.RunningJobsMeta.State
	case SectionHistory:
		return s.HistoryMeta.State
	case SectionNodes:
		return s.NodesMeta.State
	case SectionAllUsersJobs:
		return s.AllUsersJobsMeta.State
	case SectionFairShare:
		return s.FairShareMeta.State
	case SectionPendingPrio:
		return s.PendingPrioMeta.State
	case SectionEnergy:
		return s.EnergyMeta.State
	case SectionWaitTime:
		return s.WaitTimeMeta.State
	default:
		return StateIdle
	}
}

// SectionErr returns the most recent fetch error for a section, or nil. It lets
// a tab render an inline error badge for a failed section.
func (s *Store) SectionErr(section Section) error {
	switch section {
	case SectionRunningJobs:
		return s.RunningJobsMeta.Err
	case SectionHistory:
		return s.HistoryMeta.Err
	case SectionNodes:
		return s.NodesMeta.Err
	case SectionAllUsersJobs:
		return s.AllUsersJobsMeta.Err
	case SectionFairShare:
		return s.FairShareMeta.Err
	case SectionPendingPrio:
		return s.PendingPrioMeta.Err
	case SectionEnergy:
		return s.EnergyMeta.Err
	case SectionWaitTime:
		return s.WaitTimeMeta.Err
	default:
		return nil
	}
}

// SetLoading marks a section as loading for the given generation, provided that
// generation is current. It is called when a fetch is dispatched so the UI shows
// a spinner. A stale (superseded) loading mark is ignored.
func (s *Store) SetLoading(section Section, gen uint64) {
	if gen < s.gen[section] {
		return
	}
	switch section {
	case SectionRunningJobs:
		s.RunningJobsMeta.State = StateLoading
	case SectionHistory:
		s.HistoryMeta.State = StateLoading
	case SectionNodes:
		s.NodesMeta.State = StateLoading
	case SectionAllUsersJobs:
		s.AllUsersJobsMeta.State = StateLoading
	case SectionFairShare:
		s.FairShareMeta.State = StateLoading
	case SectionPendingPrio:
		s.PendingPrioMeta.State = StateLoading
	case SectionEnergy:
		s.EnergyMeta.State = StateLoading
	case SectionWaitTime:
		s.WaitTimeMeta.State = StateLoading
	}
}

// stale reports whether a result for section tagged gen should be dropped because
// a newer generation has since been dispatched (I4).
func (s *Store) stale(section Section, gen uint64) bool {
	return gen < s.gen[section]
}

// applyMeta updates a Meta from a fetch result: on error it records StateError
// and the error (keeping any prior data); on success it records StateLoaded, the
// timestamp, and clears the error.
func (s *Store) applyMeta(m *Meta, err error) {
	m.LastUpdated = s.clock()
	if err != nil {
		m.State = StateError
		m.Err = err
		return
	}
	m.State = StateLoaded
	m.Err = nil
}

// SetRunningJobs applies a running-jobs fetch result, dropping stale generations.
func (s *Store) SetRunningJobs(data []slurm.RunningJob, gen uint64, err error) {
	if s.stale(SectionRunningJobs, gen) {
		return
	}
	if err == nil {
		s.RunningJobs = data
	}
	s.applyMeta(&s.RunningJobsMeta, err)
}

// SetHistory applies a job-history fetch result, dropping stale generations.
func (s *Store) SetHistory(jobs []slurm.HistoryJob, stats slurm.HistoryStats, gen uint64, err error) {
	if s.stale(SectionHistory, gen) {
		return
	}
	if err == nil {
		s.HistoryJobs = jobs
		s.HistoryStats = stats
	}
	s.applyMeta(&s.HistoryMeta, err)
}

// SetNodes applies a cluster-nodes fetch result and recomputes cluster stats.
func (s *Store) SetNodes(data []slurm.Node, gen uint64, err error) {
	if s.stale(SectionNodes, gen) {
		return
	}
	if err == nil {
		s.Nodes = data
	}
	s.applyMeta(&s.NodesMeta, err)
	s.recomputeClusterStats()
}

// SetAllUsersJobs applies an all-users-jobs fetch result and recomputes cluster
// stats (pending resources depend on it).
func (s *Store) SetAllUsersJobs(data []slurm.AllUsersJob, gen uint64, err error) {
	if s.stale(SectionAllUsersJobs, gen) {
		return
	}
	if err == nil {
		s.AllUsersJobs = data
	}
	s.applyMeta(&s.AllUsersJobsMeta, err)
	s.recomputeClusterStats()
}

// SetFairShare applies a fair-share fetch result, dropping stale generations.
func (s *Store) SetFairShare(data []slurm.FairShareEntry, gen uint64, err error) {
	if s.stale(SectionFairShare, gen) {
		return
	}
	if err == nil {
		s.FairShare = data
	}
	s.applyMeta(&s.FairShareMeta, err)
}

// SetPendingPrio applies a pending-priority fetch result, dropping stale
// generations.
func (s *Store) SetPendingPrio(data []slurm.PriorityEntry, gen uint64, err error) {
	if s.stale(SectionPendingPrio, gen) {
		return
	}
	if err == nil {
		s.PendingPrio = data
	}
	s.applyMeta(&s.PendingPrioMeta, err)
}

// SetEnergy applies an energy-history fetch result, dropping stale generations.
func (s *Store) SetEnergy(data []slurm.EnergyRecord, gen uint64, err error) {
	if s.stale(SectionEnergy, gen) {
		return
	}
	if err == nil {
		s.Energy = data
	}
	s.applyMeta(&s.EnergyMeta, err)
}

// SetWaitTime applies a wait-time fetch result and recomputes cluster stats
// (per-partition wait stats depend on it).
func (s *Store) SetWaitTime(data []slurm.WaitTimeRecord, gen uint64, err error) {
	if s.stale(SectionWaitTime, gen) {
		return
	}
	if err == nil {
		s.WaitTime = data
	}
	s.applyMeta(&s.WaitTimeMeta, err)
	s.recomputeClusterStats()
}

// recomputeClusterStats refreshes the derived ClusterStats from the current
// nodes, all-users jobs, and wait-time data. It is called by every setter whose
// dataset feeds the derivation.
func (s *Store) recomputeClusterStats() {
	s.ClusterStats = DeriveClusterStats(s.Nodes, s.AllUsersJobs, s.WaitTime)
}

// EnergyStats returns the per-user energy summary derived from the current energy
// records.
func (s *Store) EnergyStats() []UserEnergyStats {
	return AggregateEnergyStats(s.Energy)
}

// RunningUserStats returns the per-user running-job summary derived from the
// all-users jobs, excluding pending jobs to match app.py's running aggregation.
func (s *Store) RunningUserStats() []UserStats {
	return AggregateUserStats(RunningUserJobs(s.AllUsersJobs))
}
