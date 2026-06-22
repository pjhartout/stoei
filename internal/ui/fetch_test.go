package ui

import (
	"context"
	"errors"
	"testing"

	"github.com/pjhartout/stoei/internal/store"
)

func TestFetchRunningJobsSuccess(t *testing.T) {
	client := &store.FakeClient{
		RunningJobsData: []store.RunningJob{{ID: "42"}},
	}
	msg := fetchRunningJobs(client, 7)()
	got, ok := msg.(runningJobsMsg)
	if !ok {
		t.Fatalf("msg type = %T; want runningJobsMsg", msg)
	}
	if got.gen != 7 {
		t.Errorf("gen = %d; want 7", got.gen)
	}
	if got.err != nil {
		t.Errorf("err = %v; want nil", got.err)
	}
	if len(got.jobs) != 1 || got.jobs[0].ID != "42" {
		t.Errorf("jobs = %+v", got.jobs)
	}
}

func TestFetchRunningJobsError(t *testing.T) {
	wantErr := errors.New("squeue failed")
	client := &store.FakeClient{RunningJobsErr: wantErr}
	msg := fetchRunningJobs(client, 3)()
	got := msg.(runningJobsMsg)
	if got.gen != 3 {
		t.Errorf("gen = %d; want 3", got.gen)
	}
	if !errors.Is(got.err, wantErr) {
		t.Errorf("err = %v; want %v", got.err, wantErr)
	}
}

func TestFetchHistoryCarriesStats(t *testing.T) {
	client := &store.FakeClient{
		HistoryJobsData:  []store.HistoryJob{{ID: "1"}},
		HistoryStatsData: store.HistoryStats{TotalJobs: 5, TotalRequeues: 2, MaxRequeues: 1},
	}
	got := fetchHistory(client, 1, 7)().(historyMsg)
	if got.stats.TotalJobs != 5 || got.stats.TotalRequeues != 2 || got.stats.MaxRequeues != 1 {
		t.Errorf("stats = %+v", got.stats)
	}
	if len(got.jobs) != 1 {
		t.Errorf("jobs = %+v", got.jobs)
	}
}

func TestFetchHistoryError(t *testing.T) {
	wantErr := errors.New("sacct down")
	client := &store.FakeClient{JobHistoryErr: wantErr}
	got := fetchHistory(client, 9, 7)().(historyMsg)
	if !errors.Is(got.err, wantErr) {
		t.Errorf("err = %v; want %v", got.err, wantErr)
	}
}

func TestFetchEachDatasetType(t *testing.T) {
	client := &store.FakeClient{
		NodesData:           []store.Node{{Name: "n01"}},
		AllUsersJobsData:    []store.AllUsersJob{{ID: "1"}},
		FairShareData:       []store.FairShareEntry{{Account: "acct"}},
		PendingPriorityData: []store.PriorityEntry{{JobID: "1"}},
		EnergyData:          []store.EnergyRecord{{JobID: "1"}},
		WaitTimeData:        []store.WaitTimeRecord{{JobID: "1"}},
	}

	if m := fetchNodes(client, 1)().(nodesMsg); m.gen != 1 || len(m.nodes) != 1 || m.err != nil {
		t.Errorf("nodes msg = %+v", m)
	}
	if m := fetchAllUsersJobs(client, 2)().(allUsersJobsMsg); m.gen != 2 || len(m.jobs) != 1 {
		t.Errorf("allUsers msg = %+v", m)
	}
	if m := fetchFairShare(client, 3)().(fairShareMsg); m.gen != 3 || len(m.entries) != 1 {
		t.Errorf("fairShare msg = %+v", m)
	}
	if m := fetchPendingPrio(client, 4)().(pendingPrioMsg); m.gen != 4 || len(m.entries) != 1 {
		t.Errorf("pendingPrio msg = %+v", m)
	}
	if m := fetchEnergy(client, 5, 3)().(energyMsg); m.gen != 5 || len(m.records) != 1 {
		t.Errorf("energy msg = %+v", m)
	}
	if m := fetchWaitTime(client, 6, 1)().(waitTimeMsg); m.gen != 6 || len(m.records) != 1 {
		t.Errorf("waitTime msg = %+v", m)
	}
}

// panicClient panics on RunningJobs to exercise the recover guard (I8).
type panicClient struct{ store.FakeClient }

func (*panicClient) RunningJobs(context.Context) ([]store.RunningJob, error) {
	panic("boom")
}

func TestFetchRecoversFromPanic(t *testing.T) {
	client := &panicClient{}
	msg := fetchRunningJobs(client, 1)()
	got, ok := msg.(runningJobsMsg)
	if !ok {
		t.Fatalf("msg type = %T; want runningJobsMsg", msg)
	}
	if got.err == nil {
		t.Fatal("err = nil; want recovered panic error")
	}
}
