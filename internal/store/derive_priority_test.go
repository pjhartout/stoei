package store

import (
	"testing"
	"time"
)

func TestUsageRatioAndBands(t *testing.T) {
	cases := []struct {
		name      string
		entry     FairShareEntry
		wantRatio float64
		wantOK    bool
		wantBand  UsageBand
	}{
		{"over-served user", FairShareEntry{NormShares: "0.020833", EffectvUsage: "0.261082"}, 12.53, true, UsageHeavy},
		{"exactly at share", FairShareEntry{NormShares: "0.5", EffectvUsage: "0.5"}, 1, true, UsageUnder},
		{"just over", FairShareEntry{NormShares: "0.5", EffectvUsage: "0.6"}, 1.2, true, UsageOver},
		{"at heavy boundary", FairShareEntry{NormShares: "0.5", EffectvUsage: "1.0"}, 2, true, UsageOver},
		{"unused", FairShareEntry{NormShares: "0.25", EffectvUsage: "0.000000"}, 0, true, UsageUnused},
		{"root has no share", FairShareEntry{NormShares: "0.000000", EffectvUsage: "0.000000"}, 0, false, UsageUnknown},
		{"blank fields", FairShareEntry{}, 0, false, UsageUnknown},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			ratio, ok := UsageRatio(tc.entry)
			if ok != tc.wantOK || (ok && (ratio < tc.wantRatio-0.01 || ratio > tc.wantRatio+0.01)) {
				t.Errorf("UsageRatio = %v, %v; want ≈%v, %v", ratio, ok, tc.wantRatio, tc.wantOK)
			}
			if band := ClassifyUsage(ratio, ok); band != tc.wantBand {
				t.Errorf("band = %v (%q), want %v", band, band.Label(), tc.wantBand)
			}
		})
	}
}

// TestRankActiveUsersDedupesAndHidesUnused asserts the ranking Fair Tree makes
// useful: zero-usage users are excluded, a user in two accounts appears once
// (best factor), and the total counts users rather than associations.
func TestRankActiveUsersDedupesAndHidesUnused(t *testing.T) {
	entries := []FairShareEntry{
		{Account: "physics", User: "", NormShares: "0.5", EffectvUsage: "0.5"},
		{Account: "physics", User: "alice", NormShares: "0.25", EffectvUsage: "0.10", FairShare: "0.90"},
		{Account: "physics", User: "idle", NormShares: "0.25", EffectvUsage: "0.000000", FairShare: "1.000000"},
		{Account: "chem", User: "bob", NormShares: "0.25", EffectvUsage: "0.50", FairShare: "0.30"},
		{Account: "chem", User: "alice", NormShares: "0.25", EffectvUsage: "0.60", FairShare: "0.20"},
		{Account: "chem", User: "carol", NormShares: "0.25", EffectvUsage: "0.10", FairShare: "0.90"},
	}
	ranked := RankActiveUsers(entries)
	if len(ranked) != 3 {
		t.Fatalf("got %d ranked users, want 3 (idle hidden, alice once): %+v", len(ranked), ranked)
	}
	// alice and carol tie on 0.90 and share rank 1; bob is rank 2 of 3.
	if ranked[0].Entry.User != "alice" || ranked[0].Entry.Account != "physics" || ranked[0].Rank != 1 {
		t.Errorf("ranked[0] = %+v, want alice via her best (physics) association at rank 1", ranked[0])
	}
	if ranked[1].Entry.User != "carol" || ranked[1].Rank != 1 {
		t.Errorf("ranked[1] = %+v, want carol tied at rank 1", ranked[1])
	}
	bob := FindRankedUser(ranked, "bob")
	if bob == nil || bob.Rank != 2 || bob.Total != 3 || bob.Band != UsageOver {
		t.Errorf("bob = %+v, want rank 2/3 over-served", bob)
	}
	if FindRankedUser(ranked, "idle") != nil {
		t.Error("idle user must not be ranked")
	}
	if got := UserAssociations(entries, "alice"); len(got) != 2 {
		t.Errorf("alice associations = %d, want 2", len(got))
	}
}

// TestRankAccountsHidesIdleAndOrdersByUsage asserts only accounts with a share
// and recent usage are ranked (root, zero-share, and idle accounts are left out)
// in best-served-first order.
func TestRankAccountsHidesIdleAndOrdersByUsage(t *testing.T) {
	entries := []FairShareEntry{
		{Account: "root", NormShares: "0.000000", EffectvUsage: "0.000000"},
		{Account: "heavy", NormShares: "0.25", EffectvUsage: "1.0"},
		{Account: "fair", NormShares: "0.25", EffectvUsage: "0.25"},
		{Account: "noshare", NormShares: "0", EffectvUsage: "0.1"},
		{Account: "idle", NormShares: "0.25", EffectvUsage: "0"},
		{Account: "physics", User: "alice", NormShares: "0.25", EffectvUsage: "0.1"},
	}
	ranked := RankAccounts(entries)
	want := []string{"fair", "heavy"}
	if len(ranked) != len(want) {
		t.Fatalf("got %d accounts, want %d: %+v", len(ranked), len(want), ranked)
	}
	for i, name := range want {
		if ranked[i].Entry.Account != name || ranked[i].Rank != i+1 || ranked[i].Total != 2 {
			t.Errorf("ranked[%d] = %s/%d of %d, want %s/%d of 2", i, ranked[i].Entry.Account, ranked[i].Rank, ranked[i].Total, name, i+1)
		}
	}
	if ranked[1].Band != UsageHeavy {
		t.Errorf("heavy account band = %v, want heavy", ranked[1].Band)
	}
	if got := AccountCount(entries); got != 4 {
		t.Errorf("AccountCount = %d, want 4 (root excluded, user rows ignored)", got)
	}
}

func TestRecoveryTime(t *testing.T) {
	halfLife := 14 * 24 * time.Hour
	if d, ok := RecoveryTime(12.53, halfLife); !ok || d < 50*24*time.Hour || d > 52*24*time.Hour {
		t.Errorf("RecoveryTime(12.53) = %v, %v; want ≈51d", d, ok)
	}
	if d, ok := RecoveryTime(2, halfLife); !ok || d != halfLife {
		t.Errorf("RecoveryTime(2) = %v, want exactly one half-life", d)
	}
	if _, ok := RecoveryTime(0.8, halfLife); ok {
		t.Error("under-served association must not report a recovery time")
	}
	if _, ok := RecoveryTime(4, 0); ok {
		t.Error("zero half-life (no decay) must not report a recovery time")
	}
}

// TestRankPendingPositions asserts the queue positions a user sees: ordering by
// priority with job-ID tie-break, one cluster-wide slot per job even when it is
// submitted to several partitions, and per-partition positions.
func TestRankPendingPositions(t *testing.T) {
	entries := []PriorityEntry{
		{JobID: "1000", User: "bob", Partition: "gpu", Priority: 500},
		{JobID: "999", User: "alice", Partition: "gpu", Priority: 500},
		{JobID: "42", User: "alice", Partition: "cpu", Priority: 900},
		{JobID: "42", User: "alice", Partition: "gpu", Priority: 800},
		{JobID: "7", User: "carol", Partition: "cpu", Priority: 100},
	}
	ranked := RankPending(entries)
	order := make([]string, len(ranked))
	for i, r := range ranked {
		order[i] = r.Entry.JobID + "@" + r.Entry.Partition
	}
	want := []string{"42@cpu", "42@gpu", "999@gpu", "1000@gpu", "7@cpu"}
	for i := range want {
		if order[i] != want[i] {
			t.Fatalf("order = %v, want %v", order, want)
		}
	}
	if p := ranked[1].Pos; p.Cluster != 1 || p.ClusterTotal != 4 || p.Partition != 1 || p.PartitionTotal != 3 {
		t.Errorf("42@gpu pos = %+v, want cluster 1/4 (same job as 42@cpu), gpu 1/3", p)
	}
	if p := ranked[3].Pos; p.Cluster != 3 || p.Partition != 3 || p.PartitionTotal != 3 {
		t.Errorf("1000@gpu pos = %+v, want cluster 3/4 and last of 3 in gpu", p)
	}
	if p := ranked[4].Pos; p.Cluster != 4 || p.Partition != 2 || p.PartitionTotal != 2 {
		t.Errorf("7@cpu pos = %+v, want cluster 4/4 and 2/2 in cpu", p)
	}
	mine := UserPending(ranked, "alice")
	if len(mine) != 3 || mine[0].Entry.JobID != "42" {
		t.Errorf("alice rows = %+v, want her three rows in queue order", mine)
	}
	factors, total := SumFactors(mine)
	if total != 2200 || factors != (PriorityFactors{}) {
		t.Errorf("SumFactors = %+v/%d, want zero factors and total 2200", factors, total)
	}
}

// TestPartitionViews asserts the partition-centric readings of the queue: rows
// grouped by partition in queue order, and a user's per-partition standing with
// the best job's position and their job count there.
func TestPartitionViews(t *testing.T) {
	ranked := RankPending([]PriorityEntry{
		{JobID: "1000", User: "bob", Partition: "gpu", Priority: 500},
		{JobID: "999", User: "alice", Partition: "gpu", Priority: 500},
		{JobID: "42", User: "alice", Partition: "gpu", Priority: 800},
		{JobID: "7", User: "alice", Partition: "cpu", Priority: 100},
		{JobID: "5", User: "carol", Partition: "cpu", Priority: 900},
	})
	grouped := ByPartition(ranked)
	got := make([]string, len(grouped))
	for i, r := range grouped {
		got[i] = r.Entry.JobID + "@" + r.Entry.Partition
	}
	want := []string{"5@cpu", "7@cpu", "42@gpu", "999@gpu", "1000@gpu"}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("ByPartition = %v, want %v", got, want)
		}
	}

	standings := PartitionStandings(UserPending(ranked, "alice"))
	if len(standings) != 2 || standings[0].Partition != "gpu" || standings[1].Partition != "cpu" {
		t.Fatalf("standings = %+v, want gpu (better job) before cpu", standings)
	}
	if s := standings[0]; s.Jobs != 2 || s.Best.Partition != 1 || s.Best.PartitionTotal != 3 {
		t.Errorf("gpu standing = %+v, want 2 jobs with best at 1/3", s)
	}
	if s := standings[1]; s.Jobs != 1 || s.Best.Partition != 2 || s.Best.PartitionTotal != 2 {
		t.Errorf("cpu standing = %+v, want 1 job at 2/2", s)
	}
}
