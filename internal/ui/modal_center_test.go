package ui

import (
	"regexp"
	"strings"
	"testing"

	"github.com/pjhartout/stoei/internal/store"
)

var ansiSeq = regexp.MustCompile(`\x1b\[[0-9;]*m`)

// TestModalCentered asserts the modal overlay is centered on both axes. It is a
// regression for the lipgloss canvas bug where Canvas.Compose draws a layer at
// the full canvas bounds, ignoring its X/Y offset, which pinned every modal to
// the top-left (the fix composes through a Compositor instead). A width below the
// sidebar threshold hides the sidebar so only the modal contributes the marker.
func TestModalCentered(t *testing.T) {
	a := newTestApp(t, &store.FakeClient{UsernameStr: "alice"})
	a.width, a.height = 90, 40
	a.fanoutSize()

	body := strings.TrimRight(strings.Repeat("@@@@@@@@\n", 6), "\n") // an 8x6 block
	a.pushModal(&fakeModal{body: body})

	minRow, minCol := -1, 1<<30
	for i, ln := range strings.Split(a.View().Content, "\n") {
		plain := ansiSeq.ReplaceAllString(ln, "")
		if c := strings.IndexByte(plain, '@'); c >= 0 {
			if minRow < 0 {
				minRow = i
			}
			if c < minCol {
				minCol = c
			}
		}
	}

	wantRow, wantCol := (40-6)/2, (90-8)/2
	if minRow != wantRow || minCol != wantCol {
		t.Errorf("modal top-left at row=%d col=%d; want centered row=%d col=%d",
			minRow, minCol, wantRow, wantCol)
	}
}
