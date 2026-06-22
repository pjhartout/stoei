package ui

import "testing"

func TestHealthNotifierEdgeTriggered(t *testing.T) {
	n := newHealthNotifier()

	// First-ever OK observation: nothing was broken, so no toast.
	if _, emitted := n.Observe("nodes", true); emitted {
		t.Error("first OK emitted a toast; want silent")
	}

	// healthy -> failing: one "failed" toast.
	toast, emitted := n.Observe("nodes", false)
	if !emitted {
		t.Fatal("healthy->failing did not emit")
	}
	if toast.Kind != toastFailed || toast.Section != "nodes" {
		t.Errorf("toast = %+v; want failed/nodes", toast)
	}

	// failing -> failing: silent re-arm during the ongoing outage.
	if _, emitted := n.Observe("nodes", false); emitted {
		t.Error("repeat failure emitted a toast; want silent")
	}
	if _, emitted := n.Observe("nodes", false); emitted {
		t.Error("second repeat failure emitted a toast; want silent")
	}

	// failing -> healthy: one "recovered" toast.
	rec, emitted := n.Observe("nodes", true)
	if !emitted {
		t.Fatal("failing->healthy did not emit")
	}
	if rec.Kind != toastRecovered || rec.Section != "nodes" {
		t.Errorf("toast = %+v; want recovered/nodes", rec)
	}

	// healthy -> healthy: silent.
	if _, emitted := n.Observe("nodes", true); emitted {
		t.Error("repeat OK emitted a toast; want silent")
	}
}

func TestHealthNotifierFirstObservationFailingEmits(t *testing.T) {
	n := newHealthNotifier()
	// A section that fails on its very first observation should emit once
	// (unknown -> failing is a real transition into an error state).
	toast, emitted := n.Observe("history", false)
	if !emitted {
		t.Fatal("first failing observation did not emit")
	}
	if toast.Kind != toastFailed {
		t.Errorf("kind = %v; want failed", toast.Kind)
	}
}

func TestHealthNotifierIndependentSections(t *testing.T) {
	n := newHealthNotifier()
	n.Observe("a", true)
	n.Observe("b", true)

	// Failing "a" must not affect "b".
	if _, emitted := n.Observe("a", false); !emitted {
		t.Error("a healthy->failing did not emit")
	}
	if _, emitted := n.Observe("b", true); emitted {
		t.Error("b stayed healthy but emitted")
	}
}
