package store

import (
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
)

// UsageBand classifies how an association's recent usage compares with its
// configured share. It is the quantity Slurm's Fair Tree ranks on (LevelFS is its
// reciprocal), so it is what "over-served" and "under-served" mean in practice.
type UsageBand int

const (
	// UsageUnknown means the ratio cannot be computed: the share is zero or a
	// field is missing (root and unconfigured associations).
	UsageUnknown UsageBand = iota
	// UsageUnused means the association has no recent usage at all.
	UsageUnused
	// UsageUnder means usage is at or below the share: the association is owed
	// cluster time and ranks high.
	UsageUnder
	// UsageOver means usage is above the share by up to UsageHeavyRatio.
	UsageOver
	// UsageHeavy means usage exceeds the share by more than UsageHeavyRatio.
	UsageHeavy
)

// UsageHeavyRatio is the usage/share ratio above which an association is
// classified as heavily over-served.
const UsageHeavyRatio = 2.0

// Label returns the human-readable status for the band ("" for unknown).
func (b UsageBand) Label() string {
	switch b {
	case UsageUnused:
		return "Unused"
	case UsageUnder:
		return "Under-served"
	case UsageOver:
		return "Over-served"
	case UsageHeavy:
		return "Heavily over-served"
	default:
		return ""
	}
}

// Role returns the semantic color role for the band, in the vocabulary of
// StateRole so the theme colors it like any other status.
func (b UsageBand) Role() string {
	switch b {
	case UsageUnused:
		return "muted"
	case UsageUnder:
		return "success"
	case UsageOver:
		return "warning"
	case UsageHeavy:
		return "error"
	default:
		return ""
	}
}

// UsageRatio returns how much of its share an association has consumed:
// EffectvUsage divided by NormShares, so 1 means usage matches the share and 12
// means twelve times it. ok is false when NormShares is zero or either field
// does not parse; the ratio is then meaningless and callers should show nothing.
func UsageRatio(e FairShareEntry) (ratio float64, ok bool) {
	share, err := strconv.ParseFloat(strings.TrimSpace(e.NormShares), 64)
	if err != nil || share <= 0 {
		return 0, false
	}
	usage, err := strconv.ParseFloat(strings.TrimSpace(e.EffectvUsage), 64)
	if err != nil || usage < 0 {
		return 0, false
	}
	return usage / share, true
}

// ClassifyUsage maps a usage ratio to its band. ok=false is UsageUnknown; the
// remaining bands split on zero, 1, and UsageHeavyRatio.
func ClassifyUsage(ratio float64, ok bool) UsageBand {
	switch {
	case !ok:
		return UsageUnknown
	case ratio == 0:
		return UsageUnused
	case ratio <= 1:
		return UsageUnder
	case ratio <= UsageHeavyRatio:
		return UsageOver
	default:
		return UsageHeavy
	}
}

// RankedShare is one association in a fair-share ranking, with its dense rank
// out of the ranked total and its derived usage classification.
type RankedShare struct {
	Entry FairShareEntry
	Rank  int
	Total int
	// Ratio is the usage/share ratio; RatioOK is false when it is undefined.
	Ratio   float64
	RatioOK bool
	Band    UsageBand
}

// FairShareValue parses the sshare FairShare factor. Account rows are blank under
// Fair Tree and read as 0.
func FairShareValue(e FairShareEntry) float64 {
	v, err := strconv.ParseFloat(strings.TrimSpace(e.FairShare), 64)
	if err != nil || math.IsNaN(v) {
		return 0
	}
	return v
}

// RankActiveUsers ranks the users who compete for the cluster: user-level
// associations with any effective usage, one row per user (the association with
// the highest fair-share factor, which is the one Slurm would favor), ordered by
// FairShare descending with dense ranks (ties share a rank). Users with no usage
// are excluded because Fair Tree parks them at the top with an identical factor,
// which would bury the active users and make the rank total meaningless.
func RankActiveUsers(entries []FairShareEntry) []RankedShare {
	best := map[string]FairShareEntry{}
	for _, e := range entries {
		if e.IsAccount() {
			continue
		}
		ratio, ok := UsageRatio(e)
		if !ok || ratio == 0 {
			continue
		}
		if prev, seen := best[e.User]; !seen || FairShareValue(e) > FairShareValue(prev) {
			best[e.User] = e
		}
	}
	users := make([]FairShareEntry, 0, len(best))
	for _, e := range best {
		users = append(users, e)
	}
	sort.SliceStable(users, func(i, j int) bool {
		fi, fj := FairShareValue(users[i]), FairShareValue(users[j])
		if fi != fj {
			return fi > fj
		}
		return users[i].User < users[j].User
	})
	return rankShares(users, FairShareValue)
}

// UserAssociations returns every user-level association of username in the
// order sshare listed them, so a user in several accounts can see all of them.
func UserAssociations(entries []FairShareEntry, username string) []FairShareEntry {
	var out []FairShareEntry
	for _, e := range entries {
		if e.User == username {
			out = append(out, e)
		}
	}
	return out
}

// RankAccounts ranks the accounts that compete for the cluster — those with a
// configured share and recent usage — by how well served they are: usage/share
// ascending, so the account most owed cluster time is first (the order Fair
// Tree walks the top of the tree in). Accounts without usage are excluded for
// the same reason as in RankActiveUsers: they all tie at the top and bury the
// ones that matter. The synthetic root of the tree is skipped too, because it is
// the whole cluster rather than a share of it.
func RankAccounts(entries []FairShareEntry) []RankedShare {
	var accounts []FairShareEntry
	for _, e := range entries {
		if !e.IsAccount() || e.Account == "root" {
			continue
		}
		if ratio, ok := UsageRatio(e); ok && ratio > 0 {
			accounts = append(accounts, e)
		}
	}
	key := func(e FairShareEntry) float64 {
		ratio, _ := UsageRatio(e)
		return ratio
	}
	sort.SliceStable(accounts, func(i, j int) bool {
		ki, kj := key(accounts[i]), key(accounts[j])
		if ki != kj {
			return ki < kj
		}
		return accounts[i].Account < accounts[j].Account
	})
	return rankShares(accounts, key)
}

// AccountCount returns the number of account-level associations excluding the
// synthetic root, so a caller can say how many RankAccounts left out.
func AccountCount(entries []FairShareEntry) int {
	n := 0
	for _, e := range entries {
		if e.IsAccount() && e.Account != "root" {
			n++
		}
	}
	return n
}

// rankShares assigns dense ranks to sorted entries, where consecutive entries
// with an equal key share a rank, and fills in the usage classification.
func rankShares(sorted []FairShareEntry, key func(FairShareEntry) float64) []RankedShare {
	out := make([]RankedShare, len(sorted))
	rank := 0
	for i, e := range sorted {
		if i == 0 || key(e) != key(sorted[i-1]) {
			rank++
		}
		ratio, ok := UsageRatio(e)
		out[i] = RankedShare{
			Entry: e, Rank: rank, Total: len(sorted),
			Ratio: ratio, RatioOK: ok, Band: ClassifyUsage(ratio, ok),
		}
	}
	return out
}

// FindRankedUser returns the ranked row for username, or nil when the user is
// not among the ranked entries.
func FindRankedUser(ranked []RankedShare, username string) *RankedShare {
	for i := range ranked {
		if ranked[i].Entry.User == username {
			return &ranked[i]
		}
	}
	return nil
}

// FindRankedAccount returns the ranked row for account, or nil when absent.
func FindRankedAccount(ranked []RankedShare, account string) *RankedShare {
	for i := range ranked {
		if ranked[i].Entry.Account == account {
			return &ranked[i]
		}
	}
	return nil
}

// RecoveryTime estimates how long an over-served association must stay idle for
// its usage to decay back to its share: usage halves every halfLife, so the
// answer is halfLife × log2(ratio). It assumes the rest of the cluster keeps a
// steady load (effective usage is relative). ok is false when the association is
// not over-served or usage never decays (zero half-life).
func RecoveryTime(ratio float64, halfLife time.Duration) (time.Duration, bool) {
	if ratio <= 1 || halfLife <= 0 {
		return 0, false
	}
	return time.Duration(math.Log2(ratio) * float64(halfLife)), true
}

// QueuePosition locates one pending job in the priority order the scheduler
// walks: its 1-based rank among every pending job on the cluster and among the
// pending jobs of its own partition (the ones it directly competes with).
type QueuePosition struct {
	Cluster        int
	ClusterTotal   int
	Partition      int
	PartitionTotal int
}

// RankedPriority is one sprio row with its queue position.
type RankedPriority struct {
	Entry PriorityEntry
	Pos   QueuePosition
}

// RankPending orders pending sprio rows by priority descending (ties broken by
// job ID ascending, which is how the scheduler breaks them) and assigns queue
// positions. A job submitted to several partitions has one row per partition;
// it is counted once cluster-wide, at its best row's position, while each row
// gets its own within-partition position.
func RankPending(entries []PriorityEntry) []RankedPriority {
	sorted := make([]PriorityEntry, len(entries))
	copy(sorted, entries)
	sort.SliceStable(sorted, func(i, j int) bool {
		if sorted[i].Priority != sorted[j].Priority {
			return sorted[i].Priority > sorted[j].Priority
		}
		return jobIDLess(sorted[i].JobID, sorted[j].JobID)
	})

	clusterPos := map[string]int{}
	partitionTotal := map[string]int{}
	for _, e := range sorted {
		if _, seen := clusterPos[e.JobID]; !seen {
			clusterPos[e.JobID] = len(clusterPos) + 1
		}
		partitionTotal[e.Partition]++
	}
	partitionSeen := map[string]int{}
	out := make([]RankedPriority, len(sorted))
	for i, e := range sorted {
		partitionSeen[e.Partition]++
		out[i] = RankedPriority{Entry: e, Pos: QueuePosition{
			Cluster:        clusterPos[e.JobID],
			ClusterTotal:   len(clusterPos),
			Partition:      partitionSeen[e.Partition],
			PartitionTotal: partitionTotal[e.Partition],
		}}
	}
	return out
}

// UserPending returns the ranked rows belonging to username, in queue order.
func UserPending(ranked []RankedPriority, username string) []RankedPriority {
	var out []RankedPriority
	for _, r := range ranked {
		if r.Entry.User == username {
			out = append(out, r)
		}
	}
	return out
}

// ByPartition returns the ranked rows grouped by partition (alphabetically) and
// ordered by in-partition position within each group. The scheduler fills each
// partition from its own queue and the partition factor differs between them,
// so this is the order in which jobs actually compete.
func ByPartition(ranked []RankedPriority) []RankedPriority {
	out := make([]RankedPriority, len(ranked))
	copy(out, ranked)
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Entry.Partition != out[j].Entry.Partition {
			return out[i].Entry.Partition < out[j].Entry.Partition
		}
		return out[i].Pos.Partition < out[j].Pos.Partition
	})
	return out
}

// PartitionStanding summarizes a user's pending jobs in one partition: where
// their best job sits in that partition's queue and how many of their jobs wait
// there.
type PartitionStanding struct {
	Partition string
	Best      QueuePosition
	Jobs      int
}

// PartitionStandings groups a user's ranked rows by partition, in order of the
// best job's cluster-wide position so the partition most likely to start
// something comes first.
func PartitionStandings(rows []RankedPriority) []PartitionStanding {
	var out []PartitionStanding
	index := map[string]int{}
	for _, r := range rows {
		i, seen := index[r.Entry.Partition]
		if !seen {
			i = len(out)
			index[r.Entry.Partition] = i
			out = append(out, PartitionStanding{Partition: r.Entry.Partition, Best: r.Pos})
		}
		out[i].Jobs++
		if r.Pos.Partition < out[i].Best.Partition {
			out[i].Best = r.Pos
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Best.Cluster < out[j].Best.Cluster })
	return out
}

// SumFactors totals the weighted factors and priorities of a set of rows, so a
// caller can express each factor as a share of the total priority.
func SumFactors(rows []RankedPriority) (factors PriorityFactors, total int64) {
	for _, r := range rows {
		factors.Add(r.Entry.Factors)
		total += r.Entry.Priority
	}
	return factors, total
}

// jobIDLess orders job IDs numerically by their leading job number and then by
// the full string, so "1000" sorts after "999" and array tasks stay grouped.
func jobIDLess(a, b string) bool {
	na, nb := leadingNumber(a), leadingNumber(b)
	if na != nb {
		return na < nb
	}
	return a < b
}

// leadingNumber parses the run of digits that starts s (the job number in
// "12345_[0-9]"), or 0 when s does not start with a digit.
func leadingNumber(s string) int64 {
	i := 0
	for i < len(s) && s[i] >= '0' && s[i] <= '9' {
		i++
	}
	n, _ := strconv.ParseInt(s[:i], 10, 64)
	return n
}
