package theme

import "testing"

// TestMutedForegroundIsVisible asserts the Muted style foreground is blended off
// the palette's raw Muted value — which on most of the dark themes is the
// background color — so cancelled/inactive text is not rendered invisibly
// (background on background).
func TestMutedForegroundIsVisible(t *testing.T) {
	for _, name := range Names() {
		th := ByName(name)
		rr, rg, rb, _ := th.Muted.Resolve(true).RGBA()
		gr, gg, gb, _ := BuildStyles(th, true).Muted.GetForeground().RGBA()
		if rr == gr && rg == gg && rb == gb {
			t.Errorf("theme %q: Muted foreground equals the raw palette value (often the background); "+
				"it should be blended toward Text so cancelled text stays visible", name)
		}
	}
}
