package tabs

import (
	"time"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// spinnerDebounce is the grace period before a loading spinner is shown, so a
// fast squeue tick that completes quickly never flashes a spinner.
const spinnerDebounce = 100 * time.Millisecond

// spinnerFrames are the braille dot frames used for the per-section loading
// indicator, matching the bubbles spinner.Dot set so the look is consistent with
// the modal spinners.
var spinnerFrames = []string{"⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"}

// spinnerInterval is the per-frame duration used to pick a frame from wall-clock
// time, so the indicator animates on every re-render without a dedicated ticker.
const spinnerInterval = 100 * time.Millisecond

// sectionStatus tracks the load state of one (or more) store sections backing a
// tab and renders a debounced spinner while loading-with-no-data or an inline
// error badge on a failed fetch. It is embedded by each tab; the tab calls
// observe with the section's current state on every Refresh and asks statusLine
// whether to render a status line in place of a bare empty table.
type sectionStatus struct {
	// loadingSince marks when the backing section entered loading-with-no-data, so
	// the spinner can be debounced. Zero means "not loading".
	loadingSince time.Time
	// now is the injectable clock (tests pin it); defaults to time.Now.
	now func() time.Time
}

// newSectionStatus returns a status tracker using the real clock.
func newSectionStatus() sectionStatus {
	return sectionStatus{now: time.Now}
}

// clock returns the current time, defaulting to time.Now for a zero-value tracker.
func (s *sectionStatus) clock() time.Time {
	if s.now == nil {
		return time.Now()
	}
	return s.now()
}

// observe records that the backing section is in state st with hasData rows
// already present. It starts or clears the debounce timer for the spinner. It
// must be called whenever the tab refreshes from the store.
func (s *sectionStatus) observe(st store.State, hasData bool) {
	if st == store.StateLoading && !hasData {
		if s.loadingSince.IsZero() {
			s.loadingSince = s.clock()
		}
		return
	}
	s.loadingSince = time.Time{}
}

// statusLine returns the status line to render in place of an empty table, and
// true when one should be shown. It renders an error badge for StateError (with
// no data), and a debounced spinner for loading-with-no-data once the debounce
// has elapsed. Otherwise it returns ("", false) so the tab renders its table.
func (s *sectionStatus) statusLine(st store.State, hasData bool, err error, styles theme.Styles) (string, bool) {
	if hasData {
		return "", false
	}
	if st == store.StateError {
		msg := "✗ failed to load"
		if err != nil {
			msg += ": " + err.Error()
		}
		return styles.Error.Render(msg), true
	}
	if st == store.StateLoading && !s.loadingSince.IsZero() {
		if s.clock().Sub(s.loadingSince) < spinnerDebounce {
			return "", false // still within the debounce window: no flash
		}
		frame := s.spinnerFrame()
		return styles.Subtle.Render(frame + " Loading…"), true
	}
	return "", false
}

// spinnerFrame picks an animation frame from wall-clock time so the indicator
// advances on each re-render without an extra ticker.
func (s *sectionStatus) spinnerFrame() string {
	idx := (s.clock().UnixNano() / int64(spinnerInterval)) % int64(len(spinnerFrames))
	if idx < 0 {
		idx = 0
	}
	return spinnerFrames[idx]
}
