package modals

import (
	"errors"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
)

// runningFields returns a plausible scontrol field map for a running job.
func runningFields() map[string]string {
	return map[string]string{
		"JobId":     "12345",
		"JobName":   "train",
		"JobState":  "RUNNING",
		"Partition": "p.hpcl91",
		"TimeLimit": "1-00:00:00",
		"QOS":       "normal",
		"Nice":      "0",
		"Priority":  "1000",
	}
}

// keyText builds a printable-character key press.
func keyText(s string) tea.KeyPressMsg {
	return tea.KeyPressMsg{Code: rune(s[0]), Text: s}
}

// selectRow moves the cursor to the row with the given label and returns false
// when no such row exists.
func selectRow(m *JobModify, label string) bool {
	for i, r := range m.rows {
		if r.label() == label {
			m.cursor = i
			return true
		}
	}
	return false
}

// TestModifyRowsCurated asserts the picker offers the curated fields plus Hold
// and Other, and no throttle row for a non-array job.
func TestModifyRowsCurated(t *testing.T) {
	m := NewJobModify(&store.FakeClient{}, testStyles(), "12345", runningFields())
	var labels []string
	for _, r := range m.rows {
		labels = append(labels, r.label())
	}
	got := strings.Join(labels, ",")
	want := "Partition,TimeLimit,QOS,Nice,JobName,Hold,Other…"
	if got != want {
		t.Errorf("rows = %s; want %s", got, want)
	}
}

// TestModifyRowsArrayAndHeld asserts an array job gets a throttle row targeting
// the array leader and a held job gets Release instead of Hold.
func TestModifyRowsArrayAndHeld(t *testing.T) {
	fields := runningFields()
	fields["ArrayJobId"] = "12345"
	fields["ArrayTaskThrottle"] = "4"
	fields["JobState"] = "PENDING"
	fields["Priority"] = "0"
	fields["Reason"] = "JobHeldUser"

	m := NewJobModify(&store.FakeClient{}, testStyles(), "12345_7", fields)
	if m.rows[0].key != "ArrayTaskThrottle" || m.rows[0].target != "12345" || m.rows[0].value != "4" {
		t.Errorf("throttle row = %+v; want key ArrayTaskThrottle targeting leader 12345 with value 4", m.rows[0])
	}
	if !selectRow(m, "Release") {
		t.Error("held job should offer Release")
	}
	if selectRow(m, "Hold") {
		t.Error("held job should not offer Hold")
	}
}

// TestModifyFieldEditApplies drives picking a field, editing the value, and
// applying: the FakeClient must receive the update and the modal must close with
// a ModifyRequestedMsg.
func TestModifyFieldEditApplies(t *testing.T) {
	fc := &store.FakeClient{}
	m := NewJobModify(fc, testStyles(), "12345", runningFields())
	m.SetSize(80, 24)

	if !selectRow(m, "Partition") {
		t.Fatal("no Partition row")
	}
	m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if !m.editing {
		t.Fatal("Enter on a field row should open the input step")
	}
	if m.input.Value() != "p.hpcl91" {
		t.Errorf("input pre-fill = %q; want current value p.hpcl91", m.input.Value())
	}

	m.input.SetValue("p.hpcl94g")
	_, cmd, done := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if !done {
		t.Error("applying should close the modal")
	}
	msg, ok := firstMsg(cmd).(ModifyRequestedMsg)
	if !ok {
		t.Fatalf("apply produced %T; want ModifyRequestedMsg", firstMsg(cmd))
	}
	if msg.JobID != "12345" || msg.Err != nil {
		t.Errorf("msg = %+v; want JobID 12345 with nil Err", msg)
	}
	if fc.LastUpdateJobID != "12345" || fc.LastUpdateKey != "Partition" || fc.LastUpdateValue != "p.hpcl94g" {
		t.Errorf("UpdateJob called with (%q, %q, %q); want (12345, Partition, p.hpcl94g)",
			fc.LastUpdateJobID, fc.LastUpdateKey, fc.LastUpdateValue)
	}
}

// TestModifyUnchangedValueStepsBack asserts submitting the unchanged value does
// not issue an update but returns to the picker.
func TestModifyUnchangedValueStepsBack(t *testing.T) {
	fc := &store.FakeClient{}
	m := NewJobModify(fc, testStyles(), "12345", runningFields())
	selectRow(m, "Partition")
	m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	_, cmd, done := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter}) // unchanged pre-fill
	if done || cmd != nil || m.editing {
		t.Errorf("unchanged submit: done=%v cmd=%v editing=%v; want back to picker with no update", done, cmd != nil, m.editing)
	}
	if fc.LastUpdateKey != "" {
		t.Error("unchanged submit must not call UpdateJob")
	}
}

// TestModifyThrottleTargetsArrayLeader asserts the throttle update is issued
// against the array leader id, not the task id the detail was opened for.
func TestModifyThrottleTargetsArrayLeader(t *testing.T) {
	fields := runningFields()
	fields["ArrayJobId"] = "12345"
	fields["ArrayTaskThrottle"] = "4"
	fc := &store.FakeClient{}
	m := NewJobModify(fc, testStyles(), "12345_7", fields)

	selectRow(m, "ArrayTaskThrottle")
	m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	m.input.SetValue("8")
	_, cmd, _ := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	firstMsg(cmd)
	if fc.LastUpdateJobID != "12345" {
		t.Errorf("throttle update targeted %q; want array leader 12345", fc.LastUpdateJobID)
	}
	if fc.LastUpdateKey != "ArrayTaskThrottle" || fc.LastUpdateValue != "8" {
		t.Errorf("update = %s=%s; want ArrayTaskThrottle=8", fc.LastUpdateKey, fc.LastUpdateValue)
	}
}

// TestModifyHoldApplies asserts Enter on the Hold row calls HoldJob(true)
// without an input step.
func TestModifyHoldApplies(t *testing.T) {
	fc := &store.FakeClient{}
	m := NewJobModify(fc, testStyles(), "12345", runningFields())
	if !selectRow(m, "Hold") {
		t.Fatal("no Hold row")
	}
	_, cmd, done := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if !done {
		t.Error("hold should close the modal")
	}
	msg, ok := firstMsg(cmd).(ModifyRequestedMsg)
	if !ok || msg.Desc != "hold" {
		t.Fatalf("hold produced %v; want ModifyRequestedMsg with Desc hold", firstMsg(cmd))
	}
	if fc.LastHoldJobID != "12345" || !fc.LastHold {
		t.Errorf("HoldJob called with (%q, %v); want (12345, true)", fc.LastHoldJobID, fc.LastHold)
	}
}

// TestModifyRawParsesKeyValue asserts the freeform row splits Key=Value and
// rejects input without "=" with an inline error, staying open.
func TestModifyRawParsesKeyValue(t *testing.T) {
	fc := &store.FakeClient{}
	m := NewJobModify(fc, testStyles(), "12345", runningFields())
	selectRow(m, "Other…")
	m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})

	m.input.SetValue("Requeue")
	_, _, done := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if done || m.errMsg == "" {
		t.Error("raw input without = should stay open with an inline error")
	}

	m.input.SetValue("Requeue=1")
	_, cmd, done := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if !done {
		t.Error("valid raw input should apply and close")
	}
	if _, ok := firstMsg(cmd).(ModifyRequestedMsg); !ok {
		t.Fatalf("raw apply produced %T; want ModifyRequestedMsg", firstMsg(cmd))
	}
	if fc.LastUpdateKey != "Requeue" || fc.LastUpdateValue != "1" {
		t.Errorf("update = %s=%s; want Requeue=1", fc.LastUpdateKey, fc.LastUpdateValue)
	}
}

// TestModifyEscBehavior asserts esc steps back from the input to the picker and
// closes from the picker, and typed keys reach the input (q must type, not quit).
func TestModifyEscBehavior(t *testing.T) {
	m := NewJobModify(&store.FakeClient{}, testStyles(), "12345", runningFields())
	selectRow(m, "JobName")
	m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})

	m.Update(keyText("q"))
	if !m.editing || !strings.Contains(m.input.Value(), "q") {
		t.Error("typing q in the input step must edit the value, not close")
	}

	_, _, done := m.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
	if done || m.editing {
		t.Error("esc in the input step should return to the picker, not close")
	}
	_, _, done = m.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
	if !done {
		t.Error("esc in the picker should close the modal")
	}
}

// TestModifyErrorPropagates asserts a client error rides back in the msg.
func TestModifyErrorPropagates(t *testing.T) {
	fc := &store.FakeClient{UpdateJobErr: errors.New("scontrol update error")}
	m := NewJobModify(fc, testStyles(), "12345", runningFields())
	selectRow(m, "QOS")
	m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	m.input.SetValue("high")
	_, cmd, _ := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	msg := firstMsg(cmd).(ModifyRequestedMsg)
	if msg.Err == nil {
		t.Error("client error must propagate in ModifyRequestedMsg.Err")
	}
}

// TestModifyReleaseApplies asserts Enter on the Release row of a held job calls
// HoldJob(id, false), and that a HoldJob error propagates in the msg.
func TestModifyReleaseApplies(t *testing.T) {
	fields := runningFields()
	fields["JobState"] = "PENDING"
	fields["Priority"] = "0"
	fields["Reason"] = "JobHeldUser"
	fc := &store.FakeClient{HoldJobErr: errors.New("scontrol release error")}
	m := NewJobModify(fc, testStyles(), "12345", fields)
	if !selectRow(m, "Release") {
		t.Fatal("no Release row on a held job")
	}
	_, cmd, done := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if !done {
		t.Error("release should close the modal")
	}
	msg, ok := firstMsg(cmd).(ModifyRequestedMsg)
	if !ok || msg.Desc != "release" {
		t.Fatalf("release produced %v; want ModifyRequestedMsg with Desc release", firstMsg(cmd))
	}
	if fc.LastHoldJobID != "12345" || fc.LastHold {
		t.Errorf("HoldJob called with (%q, %v); want (12345, false)", fc.LastHoldJobID, fc.LastHold)
	}
	if msg.Err == nil {
		t.Error("HoldJob error must propagate in ModifyRequestedMsg.Err")
	}
}

// TestModifyPasteReachesInput asserts a bracketed-paste message inserts text
// into the focused input instead of being dropped.
func TestModifyPasteReachesInput(t *testing.T) {
	m := NewJobModify(&store.FakeClient{}, testStyles(), "12345", runningFields())
	selectRow(m, "QOS")
	m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	m.input.SetValue("")
	m.Update(tea.PasteMsg{Content: "high"})
	if m.input.Value() != "high" {
		t.Errorf("pasted value = %q; want %q", m.input.Value(), "high")
	}
}
