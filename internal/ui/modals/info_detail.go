package modals

import (
	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// InfoDetail is a generic scrollable detail modal whose content is rendered
// synchronously from the store (no async fetch). It backs the user and account
// detail modals.
type InfoDetail struct {
	box scrollBox
}

// NewUserDetail builds a user-detail modal from the store. The content is
// aggregated against the store's already-fetched all-users, fair-share, and
// priority data, so no further IO is needed.
func NewUserDetail(st *store.Store, styles theme.Styles, username string) *InfoDetail {
	d := &InfoDetail{box: newScrollBox(styles)}
	d.box.SetTitle("User Details — " + username)
	d.box.SetFooter("↑/↓ scroll   Esc close")
	d.box.SetContent(formatUserInfo(username, st, styles))
	return d
}

// NewAccountDetail builds an account-detail modal from the store's already-fetched
// data.
func NewAccountDetail(st *store.Store, styles theme.Styles, account string) *InfoDetail {
	d := &InfoDetail{box: newScrollBox(styles)}
	d.box.SetTitle("Account Details — " + account)
	d.box.SetFooter("↑/↓ scroll   Esc close")
	d.box.SetContent(formatAccountInfo(account, st, styles))
	return d
}

// Init has nothing to start (content is rendered at construction).
func (d *InfoDetail) Init() tea.Cmd { return nil }

// Update handles scrolling and dismissal.
func (d *InfoDetail) Update(msg tea.Msg) (Modal, tea.Cmd, bool) {
	if km, ok := msg.(tea.KeyPressMsg); ok {
		if isCloseKey(km) {
			return d, nil, true
		}
		cmd := d.box.ScrollUpdate(km)
		return d, cmd, false
	}
	return d, nil, false
}

// View renders the info box.
func (d *InfoDetail) View() string { return d.box.View() }

// SetSize lays out the info box.
func (d *InfoDetail) SetSize(w, h int) { d.box.SetSize(w, h) }

// SetStyles re-themes the modal (content keeps its pre-rendered styling).
func (d *InfoDetail) SetStyles(styles theme.Styles) { d.box.SetStyles(styles) }

// ShortHelp returns the modal's dismissal binding.
func (d *InfoDetail) ShortHelp() []key.Binding {
	return []key.Binding{key.NewBinding(key.WithKeys("esc"), key.WithHelp("esc", "close"))}
}

// FullHelp returns the expanded bindings.
func (d *InfoDetail) FullHelp() [][]key.Binding { return [][]key.Binding{d.ShortHelp()} }

// Compile-time assertion that InfoDetail satisfies Modal.
var _ Modal = (*InfoDetail)(nil)
