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

// String returns the lowercase state name ("idle", "loading", "loaded",
// "error").
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
	// SectionPriorityConfig is the controller's priority plugin/weights, fetched
	// once per session.
	SectionPriorityConfig
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
	case SectionPriorityConfig:
		return "priority_config"
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
	// runningLoaded becomes true after the first successful running-jobs fetch and
	// stays true. Until then MergedJobs has no trustworthy squeue snapshot to tell a
	// stale history RUNNING row from a live one, so it leaves history states as-is.
	runningLoaded bool

	// HistoryJobs is the public history view: the session-completion overlay
	// followed by the journal base, rebuilt whenever either changes. Readers use
	// it directly; historyBase and completed are the inputs rebuildHistory merges.
	HistoryJobs  []slurm.HistoryJob
	HistoryStats slurm.HistoryStats
	HistoryMeta  Meta
	// historyBase is the most recent controller-journal history result; completed
	// holds jobs observed finishing this session (from scontrol), kept apart so the
	// overlay survives a journal refresh until that refresh includes the job.
	historyBase []slurm.HistoryJob
	completed   []slurm.HistoryJob

	Nodes     []slurm.Node
	NodesMeta Meta

	AllUsersJobs     []slurm.AllUsersJob
	AllUsersJobsMeta Meta

	FairShare     []slurm.FairShareEntry
	FairShareMeta Meta

	PendingPrio     []slurm.PriorityEntry
	PendingPrioMeta Meta

	PriorityConfig     slurm.PriorityConfig
	PriorityConfigMeta Meta

	// ClusterStats is recomputed from Nodes and AllUsersJobs whenever either
	// section is applied.
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

// meta returns the section's Meta, or nil for an unknown section. It is the
// single section-to-Meta mapping; the per-section accessors derive from it so
// adding a section means touching exactly one switch.
func (s *Store) meta(section Section) *Meta {
	switch section {
	case SectionRunningJobs:
		return &s.RunningJobsMeta
	case SectionHistory:
		return &s.HistoryMeta
	case SectionNodes:
		return &s.NodesMeta
	case SectionAllUsersJobs:
		return &s.AllUsersJobsMeta
	case SectionFairShare:
		return &s.FairShareMeta
	case SectionPendingPrio:
		return &s.PendingPrioMeta
	case SectionPriorityConfig:
		return &s.PriorityConfigMeta
	default:
		return nil
	}
}

// State returns the load state of a section.
func (s *Store) State(section Section) State {
	if m := s.meta(section); m != nil {
		return m.State
	}
	return StateIdle
}

// Settled reports whether a section has completed at least one fetch, whether
// it succeeded or failed. A view that needs several sections at once can wait
// on this rather than rendering piecemeal as each one lands; a later refresh of
// a settled section keeps its previous result visible.
func (s *Store) Settled(section Section) bool {
	if m := s.meta(section); m != nil {
		return !m.LastUpdated.IsZero()
	}
	return false
}

// AnyLoading reports whether any section currently has a fetch in flight. The UI
// uses it to run the loading-spinner animation only while there is something to
// animate.
func (s *Store) AnyLoading() bool {
	for sec := Section(0); sec < numSections; sec++ {
		if s.State(sec) == StateLoading {
			return true
		}
	}
	return false
}

// SectionErr returns the most recent fetch error for a section, or nil. It lets
// a tab render an inline error badge for a failed section.
func (s *Store) SectionErr(section Section) error {
	if m := s.meta(section); m != nil {
		return m.Err
	}
	return nil
}

// SetLoading marks a section as loading for the given generation, provided that
// generation is current. It is called when a fetch is dispatched so the UI shows
// a spinner. A stale (superseded) loading mark is ignored.
func (s *Store) SetLoading(section Section, gen uint64) {
	if gen < s.gen[section] {
		return
	}
	if m := s.meta(section); m != nil {
		m.State = StateLoading
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
// On a fresh, successful result it returns the IDs that were present in the prior
// result but are gone now — the current user's jobs that just left the queue, so
// the caller can fetch their final record and merge it into history without sacct.
// It returns nil for a stale or failed result, and (harmlessly) every prior ID the
// first time the user's queue empties.
func (s *Store) SetRunningJobs(data []slurm.RunningJob, gen uint64, err error) []string {
	if s.stale(SectionRunningJobs, gen) {
		return nil
	}
	var vanished []string
	if err == nil {
		current := make(map[string]struct{}, len(data))
		for _, j := range data {
			current[j.ID] = struct{}{}
		}
		for _, j := range s.RunningJobs {
			if _, ok := current[j.ID]; !ok {
				vanished = append(vanished, j.ID)
			}
		}
		s.RunningJobs = data
		s.runningLoaded = true
	}
	s.applyMeta(&s.RunningJobsMeta, err)
	return vanished
}

// SetHistory applies a job-history fetch result, dropping stale generations. The
// journal result is the history base; the session-observed completions overlay is
// re-applied on top (rebuildHistory) so a job that finished mid-session stays
// visible until a journal refresh absorbs it.
func (s *Store) SetHistory(jobs []slurm.HistoryJob, stats slurm.HistoryStats, gen uint64, err error) {
	if s.stale(SectionHistory, gen) {
		return
	}
	if err == nil {
		s.historyBase = jobs
		s.HistoryStats = stats
		s.rebuildHistory()
	}
	s.applyMeta(&s.HistoryMeta, err)
}

// AddCompletedJob records a job observed finishing this session (sourced from
// scontrol) so it appears in the history view immediately. The newest record wins
// for a duplicate ID; entries the journal base already covers in a terminal state
// are dropped on the next rebuild.
func (s *Store) AddCompletedJob(job slurm.HistoryJob) {
	overlay := make([]slurm.HistoryJob, 0, len(s.completed)+1)
	overlay = append(overlay, job) // newest first
	for _, j := range s.completed {
		if j.ID != job.ID {
			overlay = append(overlay, j)
		}
	}
	s.completed = overlay
	s.rebuildHistory()
}

// rebuildHistory recomputes the public HistoryJobs as the session-completion
// overlay followed by the journal base. The base is authoritative only for jobs
// it records in a terminal state: it also snapshots running/pending jobs, so an
// overlay entry (a freshly observed completion) supersedes a stale non-terminal
// base record for the same id. Without this, a job that was running when stoei
// started stays frozen as RUNNING after it finishes, because the base's stale
// RUNNING snapshot would shadow the overlay's terminal record.
func (s *Store) rebuildHistory() {
	terminalBase := make(map[string]bool, len(s.historyBase))
	for _, j := range s.historyBase {
		if slurm.IsTerminalState(j.State) {
			terminalBase[j.ID] = true
		}
	}
	kept := make([]slurm.HistoryJob, 0, len(s.completed))
	overlayIDs := make(map[string]struct{}, len(s.completed))
	for _, j := range s.completed {
		if terminalBase[j.ID] {
			continue // the base holds the final record; drop the overlay copy.
		}
		kept = append(kept, j)
		overlayIDs[j.ID] = struct{}{}
	}
	s.completed = kept
	merged := make([]slurm.HistoryJob, 0, len(kept)+len(s.historyBase))
	merged = append(merged, kept...)
	for _, j := range s.historyBase {
		if _, ok := overlayIDs[j.ID]; ok {
			continue // superseded by a fresher overlay completion.
		}
		merged = append(merged, j)
	}
	s.HistoryJobs = merged
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

// SetPriorityConfig applies a priority-config fetch result, dropping stale
// generations.
func (s *Store) SetPriorityConfig(data slurm.PriorityConfig, gen uint64, err error) {
	if s.stale(SectionPriorityConfig, gen) {
		return
	}
	if err == nil {
		s.PriorityConfig = data
	}
	s.applyMeta(&s.PriorityConfigMeta, err)
}

// recomputeClusterStats refreshes the derived ClusterStats from the current
// nodes and all-users jobs. It is called by every setter whose dataset feeds the
// derivation.
func (s *Store) recomputeClusterStats() {
	s.ClusterStats = DeriveClusterStats(s.Nodes, s.AllUsersJobs)
}

// RunningUserStats returns the per-user running-job summary derived from the
// all-users jobs, excluding pending jobs. Typeless GPU requests are attributed
// to the hardware of the nodes they run on.
func (s *Store) RunningUserStats() []UserStats {
	return AggregateUserStats(RunningUserJobs(s.AllUsersJobs), NodeGPUModels(s.Nodes))
}
