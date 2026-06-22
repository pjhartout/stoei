package modals

import (
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
)

// TestCancelConfirmDefaultsToNo asserts focus starts on the safe "No" option, so
// pressing Enter immediately aborts without cancelling.
func TestCancelConfirmDefaultsToNo(t *testing.T) {
	fc := &store.FakeClient{}
	c := NewCancelConfirm(fc, testStyles(), "12345", "train")
	if c.choice != choiceNo {
		t.Fatalf("default focus = %v; want choiceNo (safe)", c.choice)
	}

	_, cmd, done := c.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if !done {
		t.Error("Enter on the default should close the modal")
	}
	if cmd != nil {
		// The abort path must not issue a cancel Cmd.
		if _, ok := firstMsg(cmd).(CancelRequestedMsg); ok {
			t.Error("Enter on the default (No) must not cancel the job")
		}
	}
	if fc.LastCancelJobID != "" {
		t.Error("aborting must not call CancelJob")
	}
}

// TestCancelConfirmConfirmCallsCancelJob asserts moving to Yes and pressing Enter
// issues a CancelJob Cmd for the job.
func TestCancelConfirmConfirmCallsCancelJob(t *testing.T) {
	fc := &store.FakeClient{}
	c := NewCancelConfirm(fc, testStyles(), "12345", "train")

	c.Update(tea.KeyPressMsg{Code: tea.KeyRight}) // No -> Yes
	_, cmd, done := c.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if !done {
		t.Error("confirming should close the modal")
	}
	msg := firstMsg(cmd)
	req, ok := msg.(CancelRequestedMsg)
	if !ok {
		t.Fatalf("confirm produced %T; want CancelRequestedMsg", msg)
	}
	if req.JobID != "12345" {
		t.Errorf("CancelRequestedMsg.JobID = %q; want 12345", req.JobID)
	}
	if fc.LastCancelJobID != "12345" {
		t.Errorf("CancelJob called with %q; want 12345", fc.LastCancelJobID)
	}
}

// TestCancelConfirmEscAborts asserts esc aborts without cancelling.
func TestCancelConfirmEscAborts(t *testing.T) {
	fc := &store.FakeClient{}
	c := NewCancelConfirm(fc, testStyles(), "1", "")
	c.Update(tea.KeyPressMsg{Code: tea.KeyRight}) // even if focused on Yes
	_, cmd, done := c.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
	if !done {
		t.Error("esc should close the modal")
	}
	if cmd != nil {
		if _, ok := firstMsg(cmd).(CancelRequestedMsg); ok {
			t.Error("esc must abort, not cancel")
		}
	}
}

// TestCancelConfirmRendersJob asserts the job id and name appear in the view.
func TestCancelConfirmRendersJob(t *testing.T) {
	c := NewCancelConfirm(&store.FakeClient{}, testStyles(), "777", "myjob")
	view := c.View()
	if !strings.Contains(view, "777") || !strings.Contains(view, "myjob") {
		t.Errorf("confirm view missing job id/name, got:\n%s", view)
	}
}
