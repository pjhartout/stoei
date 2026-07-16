package modals

import (
	"fmt"
	"strconv"
	"strings"

	"charm.land/bubbles/v2/textinput"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/config"
	"github.com/pjhartout/stoei/internal/ui/theme"
)

// SettingsAppliedMsg is emitted when the user saves the settings form. The root
// handles it by persisting the config, swapping the theme/keymap, and updating
// the refresh intervals, history days, and log-viewer line count
// live. The config it carries is already clamped to the config package's bounds.
type SettingsAppliedMsg struct {
	// Config is the new, clamped configuration to apply and persist.
	Config config.Config
}

// SettingsToastMsg asks the root to show a toast, used for invalid-input feedback
// when a field cannot be parsed.
type SettingsToastMsg struct {
	// Text is the toast message.
	Text string
}

// fieldKind distinguishes a free-text (numeric) field from a cycling enum field.
type fieldKind int

const (
	// fieldText is a numeric text-input field (refresh, history, lines).
	fieldText fieldKind = iota
	// fieldEnum is a left/right cycling selector (theme, keybind mode).
	fieldEnum
)

// settingField is one editable row of the settings form.
type settingField struct {
	label string
	kind  fieldKind

	// input backs a fieldText row.
	input textinput.Model

	// options/selected back a fieldEnum row; labels parallels options for display.
	options  []string
	labels   []string
	selected int
}

// Field indices in the form, in display/focus order.
const (
	fThemeIdx = iota
	fRefreshIdx
	fHistoryIdx
	fLinesIdx
	fKeybindIdx
	numFields
)

// Settings is the hand-rolled settings form modal (huh has no v2). It edits a
// config.Config in place: up/down move between fields, left/right cycle enum and
// bool fields, text fields are edited inline. Save (ctrl+s or enter on the last
// field) emits a SettingsAppliedMsg; esc cancels without applying.
type Settings struct {
	styles theme.Styles
	fields []settingField
	focus  int

	width  int
	height int
}

// NewSettings builds the form pre-populated from cfg.
func NewSettings(styles theme.Styles, cfg config.Config) *Settings {
	themeOpts := theme.Names()
	keybindOpts := []string{config.KeybindVim, config.KeybindEmacs}

	fields := make([]settingField, numFields)
	fields[fThemeIdx] = settingField{
		label:    "Theme",
		kind:     fieldEnum,
		options:  themeOpts,
		labels:   themeOpts,
		selected: indexOf(themeOpts, cfg.Theme),
	}
	fields[fRefreshIdx] = numericField(
		fmt.Sprintf("Refresh interval (seconds, %.0f-%.0f)", config.MinRefreshInterval, config.MaxRefreshInterval),
		strconv.FormatFloat(cfg.RefreshInterval, 'f', -1, 64),
	)
	fields[fHistoryIdx] = numericField(
		fmt.Sprintf("Job history days (%d-%d)", config.MinJobHistoryDays, config.MaxJobHistoryDays),
		strconv.Itoa(cfg.JobHistoryDays),
	)
	fields[fLinesIdx] = numericField(
		fmt.Sprintf("Log viewer lines (%d-%d)", config.MinLogViewerLines, config.MaxLogViewerLines),
		strconv.Itoa(cfg.LogViewerLines),
	)
	fields[fKeybindIdx] = settingField{
		label:    "Keybind mode",
		kind:     fieldEnum,
		options:  keybindOpts,
		labels:   []string{"Vim", "Emacs"},
		selected: indexOf(keybindOpts, cfg.KeybindMode),
	}

	s := &Settings{styles: styles, fields: fields}
	s.focusField(fThemeIdx)
	return s
}

// numericField builds a text-input settings row pre-filled with value.
func numericField(label, value string) settingField {
	ti := textinput.New()
	ti.SetValue(value)
	return settingField{label: label, kind: fieldText, input: ti}
}

// indexOf returns the index of v in opts, or 0 when absent so an unknown value
// lands on the first option rather than failing.
func indexOf(opts []string, v string) int {
	for i, o := range opts {
		if o == v {
			return i
		}
	}
	return 0
}

// Init starts the text cursor blink.
func (s *Settings) Init() tea.Cmd { return textinput.Blink }

// Update handles navigation, inline editing, save, and cancel. Returns done=true
// on a successful save or cancel so the root pops the modal; invalid input
// toasts and keeps the modal open so the user can fix the field.
func (s *Settings) Update(msg tea.Msg) (Modal, tea.Cmd, bool) {
	km, ok := msg.(tea.KeyPressMsg)
	if !ok {
		return s, s.forwardToInput(msg), false
	}

	switch km.String() {
	case "esc":
		return s, nil, true
	case "ctrl+s":
		cmd, saved := s.save()
		return s, cmd, saved
	case "up", "shift+tab":
		s.moveFocus(-1)
		return s, nil, false
	case "down", "tab":
		s.moveFocus(1)
		return s, nil, false
	case "left":
		s.cycleCurrent(-1)
		return s, nil, false
	case "right":
		s.cycleCurrent(1)
		return s, nil, false
	case "enter":
		// Enter saves from the last field, otherwise advances.
		if s.focus == numFields-1 {
			cmd, saved := s.save()
			return s, cmd, saved
		}
		s.moveFocus(1)
		return s, nil, false
	}

	return s, s.forwardToInput(km), false
}

// forwardToInput routes a message to the focused text field's input (if any).
func (s *Settings) forwardToInput(msg tea.Msg) tea.Cmd {
	f := &s.fields[s.focus]
	if f.kind != fieldText {
		return nil
	}
	var cmd tea.Cmd
	f.input, cmd = f.input.Update(msg)
	return cmd
}

// moveFocus moves the focus by delta with wraparound and updates input focus.
func (s *Settings) moveFocus(delta int) {
	next := (s.focus + delta + numFields) % numFields
	s.focusField(next)
}

// focusField focuses field i, blurring all text inputs except the focused one.
func (s *Settings) focusField(i int) {
	s.focus = i
	for idx := range s.fields {
		if s.fields[idx].kind != fieldText {
			continue
		}
		if idx == i {
			s.fields[idx].input.Focus()
		} else {
			s.fields[idx].input.Blur()
		}
	}
}

// cycleCurrent cycles the focused enum/bool field by direction.
func (s *Settings) cycleCurrent(direction int) {
	f := &s.fields[s.focus]
	switch f.kind {
	case fieldEnum:
		n := len(f.options)
		if n == 0 {
			return
		}
		f.selected = (f.selected + direction + n) % n
	default:
		// fieldText edits through its input, not by cycling.
	}
}

// save builds, clamps, and emits the new config. On invalid input it returns a
// toast Cmd and saved=false so the modal stays open for the user to fix the
// field.
func (s *Settings) save() (cmd tea.Cmd, saved bool) {
	cfg := config.Default()
	cfg.Theme = s.fields[fThemeIdx].options[s.fields[fThemeIdx].selected]
	cfg.KeybindMode = s.fields[fKeybindIdx].options[s.fields[fKeybindIdx].selected]

	refresh, err := parseFloat(s.fields[fRefreshIdx].input.Value())
	if err != nil {
		return toastCmd("Refresh interval must be a number"), false
	}
	cfg.RefreshInterval = refresh

	history, err := parseInt(s.fields[fHistoryIdx].input.Value())
	if err != nil {
		return toastCmd("Job history days must be a number"), false
	}
	cfg.JobHistoryDays = history

	lines, err := parseInt(s.fields[fLinesIdx].input.Value())
	if err != nil {
		return toastCmd("Log viewer lines must be a number"), false
	}
	cfg.LogViewerLines = lines

	// Clamp through the pure config path so out-of-range fields fall back to the
	// defaults rather than persisting invalid values.
	clamped, _ := config.Load(mustMarshalRaw(cfg))
	return func() tea.Msg { return SettingsAppliedMsg{Config: clamped} }, true
}

// mustMarshalRaw serializes cfg to YAML without clamping so config.Load can do
// the clamping. config.Marshal already clamps, which would mask the fallback
// behavior; here we want Load to be the single clamp seam.
func mustMarshalRaw(cfg config.Config) []byte {
	return []byte(fmt.Sprintf(
		"theme: %q\nrefresh_interval: %v\njob_history_days: %d\nlog_viewer_lines: %d\nkeybind_mode: %q\n",
		cfg.Theme, cfg.RefreshInterval, cfg.JobHistoryDays, cfg.LogViewerLines,
		cfg.KeybindMode,
	))
}

// parseFloat parses a trimmed float.
func parseFloat(v string) (float64, error) {
	return strconv.ParseFloat(strings.TrimSpace(v), 64)
}

// parseInt parses a trimmed int.
func parseInt(v string) (int, error) {
	return strconv.Atoi(strings.TrimSpace(v))
}

// toastCmd returns a Cmd emitting a SettingsToastMsg.
func toastCmd(text string) tea.Cmd {
	return func() tea.Msg { return SettingsToastMsg{Text: text} }
}

// View renders the form: a title, one row per field (focused row highlighted),
// and a footer hint.
func (s *Settings) View() string {
	rows := make([]string, 0, len(s.fields)+3)
	rows = append(rows, s.styles.Title.Render("Settings"), "")

	for i := range s.fields {
		rows = append(rows, s.renderField(i))
	}

	rows = append(rows, "", s.styles.Subtle.Render("↑/↓ move   ←/→ change   Ctrl+S save   Esc cancel"))
	return s.styles.Modal.Render(lipgloss.JoinVertical(lipgloss.Left, rows...))
}

// renderField renders one form row, marking the focused field.
func (s *Settings) renderField(i int) string {
	f := &s.fields[i]
	marker := "  "
	labelStyle := s.styles.Subtle
	if i == s.focus {
		marker = "> "
		labelStyle = s.styles.Text.Bold(true)
	}

	var value string
	switch f.kind {
	case fieldText:
		value = f.input.View()
	case fieldEnum:
		value = "‹ " + f.labels[f.selected] + " ›"
	}

	label := labelStyle.Render(f.label + ":")
	return marker + label + "  " + s.styles.Text.Render(value)
}

// SetSize records the area and sizes the text inputs to fit the modal interior.
func (s *Settings) SetSize(w, h int) {
	s.width = w
	s.height = h
	mw, _ := modalSize(w, h)
	iw := max(mw-modalChromeWidth-24, 10)
	for idx := range s.fields {
		if s.fields[idx].kind == fieldText {
			s.fields[idx].input.SetWidth(iw)
		}
	}
}

// SetStyles re-themes the form.
func (s *Settings) SetStyles(styles theme.Styles) { s.styles = styles }

// Compile-time assertion that Settings satisfies Modal.
var _ Modal = (*Settings)(nil)
