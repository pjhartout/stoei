package ui

import (
	"fmt"
	"testing"
	"time"

	"github.com/pjhartout/stoei/internal/store"
)

// benchApp builds an App over a realistically sized store (300 jobs, 80 nodes).
func benchApp() App {
	st := store.New()
	st.SetClock(func() time.Time { return time.Date(2026, 7, 6, 12, 0, 0, 0, time.UTC) })
	jobs := make([]store.RunningJob, 300)
	all := make([]store.AllUsersJob, 300)
	for i := range jobs {
		id := fmt.Sprintf("51%05d", i)
		jobs[i] = store.RunningJob{ID: id, Name: fmt.Sprintf("experiment-%d", i), State: "RUNNING",
			Time: "2:10:11", Nodes: "1", NodeList: fmt.Sprintf("hpcl9%03d", i%80)}
		all[i] = store.AllUsersJob{ID: id, User: fmt.Sprintf("user%02d", i%20), State: "RUNNING",
			NumNodes: "1", NodeList: jobs[i].NodeList, TRES: "cpu=8,mem=100G,gres/gpu=1,gres/gpu:h100=1"}
	}
	nodes := make([]store.Node, 80)
	for i := range nodes {
		name := fmt.Sprintf("hpcl9%03d", i)
		nodes[i] = store.Node{Name: name, State: "MIXED", CPUTot: "152", CPUAlloc: "76",
			RealMem: "1000000", AllocMem: "500000",
			CfgTRES:   "cpu=152,mem=1000000M,gres/gpu=4,gres/gpu:h100=4",
			AllocTRES: "cpu=76,mem=500000M,gres/gpu=2,gres/gpu:h100=2",
			Gres:      "gpu:h100:4", Fields: map[string]string{"NodeName": name}}
	}
	st.SetRunningJobs(jobs, st.NextGen(store.SectionRunningJobs), nil)
	st.SetAllUsersJobs(all, st.NextGen(store.SectionAllUsersJobs), nil)
	st.SetNodes(nodes, st.NextGen(store.SectionNodes), nil)

	a := New(st, &store.FakeClient{UsernameStr: "hartout"})
	a.availChecked = true
	a.width, a.height = 200, 50
	a.fanoutSize()
	return a
}

// BenchmarkAnimFrame measures one animation frame as the anim tier produces it:
// advance the phase, dirty the frame, re-render the full base view.
func BenchmarkAnimFrame(b *testing.B) {
	a := benchApp()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		a.animPhase++
		a.frame.dirty = true
		a.View()
	}
}
