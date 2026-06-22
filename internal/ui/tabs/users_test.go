package tabs

import (
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

func seedUsers(t *testing.T, all []store.AllUsersJob, energy []store.EnergyRecord) *Users {
	t.Helper()
	st := store.New()
	st.SetAllUsersJobs(all, st.NextGen(store.SectionAllUsersJobs), nil)
	st.SetEnergy(energy, st.NextGen(store.SectionEnergy), nil)
	u := NewUsers(st, theme.BuildStyles(theme.Charm(), true), 6)
	u.SetSize(120, 30)
	return u
}

func keyMsg(s string) tea.KeyPressMsg {
	if len(s) == 1 {
		return tea.KeyPressMsg{Code: rune(s[0]), Text: s}
	}
	return tea.KeyPressMsg{Text: s}
}

func TestUsersRunningPaneRendersGPUCount(t *testing.T) {
	all := []store.AllUsersJob{
		{ID: "1", User: "alice", State: "RUNNING", NumNodes: "1", NodeList: "n01", TRES: "cpu=8,mem=16G,gres/gpu:h200=4"},
	}
	u := seedUsers(t, all, nil)
	view := u.View()

	if !strings.Contains(view, "alice") {
		t.Fatalf("running pane missing user; view:\n%s", view)
	}
	if !strings.Contains(view, "4") {
		t.Errorf("running pane missing GPU count 4; view:\n%s", view)
	}
	if !strings.Contains(view, "8x H200") && !strings.Contains(view, "4x H200") {
		t.Errorf("running pane missing GPU types; view:\n%s", view)
	}
}

func TestUsersSwitchToPendingPane(t *testing.T) {
	all := []store.AllUsersJob{
		{ID: "1", User: "alice", State: "RUNNING", NumNodes: "1", NodeList: "n01", TRES: "cpu=8,mem=16G"},
		{ID: "9000_[0-9]", User: "bob", State: "PENDING", TRES: "cpu=2,mem=4G"},
	}
	u := seedUsers(t, all, nil)

	if u.activeSubtab != subtabRunning {
		t.Fatalf("default subtab = %v; want running", u.activeSubtab)
	}

	u2, _ := u.Update(keyMsg("p"))
	if u2.activeSubtab != subtabPending {
		t.Fatalf("after 'p' subtab = %v; want pending", u2.activeSubtab)
	}

	view := u2.View()
	if !strings.Contains(view, "bob") {
		t.Errorf("pending pane should show bob; view:\n%s", view)
	}
	// bob's pending array of 10 tasks → 10 pending jobs.
	if !strings.Contains(view, "10") {
		t.Errorf("pending pane should show 10 pending jobs (array expanded); view:\n%s", view)
	}
}

func TestUsersSwitchToEnergyPane(t *testing.T) {
	energy := []store.EnergyRecord{
		{JobID: "1", User: "carol", Elapsed: "01:00:00", NCPUS: "4", AllocTRES: "cpu=4", State: "COMPLETED"},
	}
	u := seedUsers(t, nil, energy)

	u2, _ := u.Update(keyMsg("e"))
	if u2.activeSubtab != subtabEnergy {
		t.Fatalf("after 'e' subtab = %v; want energy", u2.activeSubtab)
	}
	view := u2.View()
	if !strings.Contains(view, "carol") {
		t.Errorf("energy pane should show carol; view:\n%s", view)
	}
	// 4 CPUs * 1h at 10W/core = 40 Wh.
	if !strings.Contains(view, "40 Wh") {
		t.Errorf("energy pane should show 40 Wh; view:\n%s", view)
	}
}
