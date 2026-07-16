package modals

import (
	"testing"

	tea "charm.land/bubbletea/v2"
)

// TestJobInputSubmitEmitsJobID asserts typing a job id and pressing Enter closes
// the prompt and emits a JobIDSubmittedMsg carrying the trimmed id — the seam
// the root relies on to open the job-detail modal for the "i" lookup flow.
func TestJobInputSubmitEmitsJobID(t *testing.T) {
	j := NewJobInput(testStyles())
	j.SetSize(80, 24)

	for _, r := range " 12345 " {
		j.Update(tea.KeyPressMsg{Code: r, Text: string(r)})
	}
	_, cmd, done := j.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if !done {
		t.Error("Enter with a job id should close the prompt")
	}
	msg := firstMsg(cmd)
	submitted, ok := msg.(JobIDSubmittedMsg)
	if !ok {
		t.Fatalf("submit produced %T; want JobIDSubmittedMsg", msg)
	}
	if submitted.JobID != "12345" {
		t.Errorf("JobID = %q; want the trimmed id 12345", submitted.JobID)
	}
}

// TestJobInputEmptyEnterClosesWithoutSubmit asserts Enter on an empty input
// closes the prompt without emitting a JobIDSubmittedMsg, so the root never
// opens a detail modal for a blank id.
func TestJobInputEmptyEnterClosesWithoutSubmit(t *testing.T) {
	j := NewJobInput(testStyles())
	j.SetSize(80, 24)

	_, cmd, done := j.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if !done {
		t.Error("Enter on an empty input should close the prompt")
	}
	if cmd != nil {
		t.Errorf("empty submit produced %v; want no message at all", firstMsg(cmd))
	}
}

// TestJobInputEscCancels asserts esc closes the prompt without submitting even
// when an id has already been typed — cancel must never trigger a lookup.
func TestJobInputEscCancels(t *testing.T) {
	j := NewJobInput(testStyles())
	j.SetSize(80, 24)

	for _, r := range "999" {
		j.Update(tea.KeyPressMsg{Code: r, Text: string(r)})
	}
	_, cmd, done := j.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
	if !done {
		t.Error("esc should close the prompt")
	}
	if cmd != nil {
		t.Errorf("esc produced %v; want no message (no submit on cancel)", firstMsg(cmd))
	}
}
