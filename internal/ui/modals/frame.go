package modals

import (
	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/ui/theme"
)

// modalFraction is the share of the terminal a centered modal occupies. The
// overlay compositor in app.go centers whatever the modal renders, so sizing the
// modal to a fraction of the screen keeps a margin of base content visible around
// it rather than letting the modal fill the whole screen.
const modalFraction = 0.85

// modalMinWidth / modalMinHeight are the terminal dimensions below which a modal
// fills the whole screen instead of scaling to modalFraction.
const (
	modalMinWidth  = 20
	modalMinHeight = 6
)

// modalSize returns the modal's outer width/height for a terminal of w x h,
// clamped to a sensible minimum so a tiny terminal still renders something.
func modalSize(w, h int) (int, int) {
	mw := int(float64(w) * modalFraction)
	mh := int(float64(h) * modalFraction)
	if mw < modalMinWidth {
		mw = w
	}
	if mh < modalMinHeight {
		mh = h
	}
	return mw, mh
}

// scrollBox is a reusable bordered, titled, scrollable content area shared by the
// job/node/user/account detail modals and the help modal. It wraps a bubbles/v2
// viewport for the scrollable body and renders a title header and a footer hint
// inside a rounded border. Content is set once (the detail text) and the viewport
// owns the scroll state; arrow/page keys are forwarded to it by the owner.
type scrollBox struct {
	styles theme.Styles
	vp     viewport.Model

	title  string
	footer string

	width  int
	height int
}

// newScrollBox returns a scrollBox with the given styles. SoftWrap is disabled so
// a line longer than the viewport is not wrapped but can be scrolled horizontally
// (←/→) instead, which keeps tabular detail content aligned.
func newScrollBox(styles theme.Styles) scrollBox {
	vp := viewport.New()
	vp.SoftWrap = false
	return scrollBox{styles: styles, vp: vp}
}

// SetStyles re-themes the box.
func (b *scrollBox) SetStyles(styles theme.Styles) { b.styles = styles }

// SetTitle sets the header title text.
func (b *scrollBox) SetTitle(title string) { b.title = title }

// SetFooter sets the footer hint text.
func (b *scrollBox) SetFooter(footer string) { b.footer = footer }

// SetContent replaces the scrollable body text.
func (b *scrollBox) SetContent(content string) { b.vp.SetContent(content) }

// SetSize lays the box out for a w x h terminal, sizing the inner viewport to the
// modal interior (less the border, padding, title and footer rows).
func (b *scrollBox) SetSize(w, h int) {
	mw, mh := modalSize(w, h)
	b.width = mw
	b.height = mh

	// The Modal style adds a 1-cell rounded border and 1x2 padding on each side.
	innerW := mw - modalChromeWidth
	innerH := mh - modalChromeHeight
	if innerW < 1 {
		innerW = 1
	}
	if innerH < 1 {
		innerH = 1
	}
	b.vp.SetWidth(innerW)
	b.vp.SetHeight(innerH)
}

const (
	// modalChromeWidth is the horizontal space the border (2) and padding (2*2)
	// consume.
	modalChromeWidth = 6
	// modalChromeHeight is the vertical space the border (2), padding (2), title
	// row + blank (2), and footer row + blank (2) consume.
	modalChromeHeight = 8
)

// ScrollUpdate forwards a message to the inner viewport so arrow/page keys
// scroll the content, returning any produced Cmd.
func (b *scrollBox) ScrollUpdate(msg tea.Msg) tea.Cmd {
	var cmd tea.Cmd
	b.vp, cmd = b.vp.Update(msg)
	return cmd
}

// GotoTop scrolls the content to the top.
func (b *scrollBox) GotoTop() { b.vp.GotoTop() }

// GotoBottom scrolls the content to the bottom.
func (b *scrollBox) GotoBottom() { b.vp.GotoBottom() }

// View renders the titled, footed, bordered box. The border color/padding come
// from the Modal style.
func (b *scrollBox) View() string {
	title := b.styles.Title.Render(b.title)
	body := b.vp.View()
	footer := b.styles.Subtle.Render(b.footer)

	inner := lipgloss.JoinVertical(lipgloss.Left, title, "", body, "", footer)
	return b.styles.Modal.Render(inner)
}
