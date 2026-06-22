package ui

import "fmt"

// health is the binary health state of a data section, tracked by the notifier.
type health int

const (
	// healthUnknown is the initial state before the first observation.
	healthUnknown health = iota
	// healthOK means the section's last fetch succeeded.
	healthOK
	// healthFailing means the section's last fetch failed.
	healthFailing
)

// toastKind classifies an emitted notification.
type toastKind int

const (
	// toastFailed is emitted on a healthy/unknown -> failing transition.
	toastFailed toastKind = iota
	// toastRecovered is emitted on a failing -> healthy transition.
	toastRecovered
)

// toast is an edge-triggered notification produced by the healthNotifier. It is
// only ever returned on a state transition, never on a repeat of the same state
// (the CLAUDE.md no-spam rule, I9).
type toast struct {
	Section string
	Kind    toastKind
	Message string
}

// healthNotifier implements the edge-triggered notification state machine. It
// holds the last observed health per section key and emits a toast only when the
// observed health differs from the stored one. Repeated failures during an
// ongoing outage are silent; recovery emits exactly one "recovered" toast.
type healthNotifier struct {
	states map[string]health
}

// newHealthNotifier returns a ready-to-use notifier.
func newHealthNotifier() *healthNotifier {
	return &healthNotifier{states: map[string]health{}}
}

// Observe records the outcome of a fetch for section and returns a toast when the
// health transitioned. ok=true means the fetch succeeded. The boolean return
// reports whether a toast was produced.
//
// Transitions and emissions:
//   - unknown/ok  -> failing: toastFailed
//   - failing     -> ok:      toastRecovered
//   - same state (ok->ok, failing->failing): no emission
//   - first-ever ok observation: no emission (nothing was broken)
func (n *healthNotifier) Observe(section string, ok bool) (toast, bool) {
	prev := n.states[section]
	cur := healthOK
	if !ok {
		cur = healthFailing
	}
	n.states[section] = cur

	if cur == prev {
		return toast{}, false
	}

	switch {
	case cur == healthFailing:
		return toast{
			Section: section,
			Kind:    toastFailed,
			Message: fmt.Sprintf("%s: data refresh failed", section),
		}, true
	case cur == healthOK && prev == healthFailing:
		return toast{
			Section: section,
			Kind:    toastRecovered,
			Message: fmt.Sprintf("%s: data refresh recovered", section),
		}, true
	case cur == healthOK && prev == healthUnknown:
		// First-ever OK observation: nothing was broken, so stay silent.
		return toast{}, false
	default:
		return toast{}, false
	}
}
