package modals

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"regexp"
	"strings"

	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/spinner"
	"charm.land/bubbles/v2/textinput"
	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"

	"github.com/pjhartout/stoei/internal/ui/theme"
)

// defaultLogViewerLines is the tail window for large files. Ports the default
// settings.log_viewer_lines.
const defaultLogViewerLines = 1000

// LogToastMsg asks the root to show a transient message from the log viewer
// (copy-path feedback, $EDITOR result, markup fallback notice).
type LogToastMsg struct {
	// Text is the message to toast.
	Text string
}

// logLoadedMsg carries the result of an off-loop file read back into the viewer.
type logLoadedMsg struct {
	// lines are the (possibly tailed) raw file lines.
	lines []string
	// totalLines is the file's full line count (for the truncation header).
	totalLines int
	// startLine is the 1-based line number of the first loaded line.
	startLine int
	// truncated reports whether only the tail was loaded.
	truncated bool
	// err is a load error message, or empty on success.
	err string
}

// editorDoneMsg is returned after the $EDITOR child process exits (via
// tea.ExecProcess). It carries any launch/run error.
type editorDoneMsg struct{ err error }

// LogViewer is the scrollable log-file modal. It reads the file in a Cmd (never
// in Update — a big/slow-FS file must not freeze the UI; a spinner shows while
// loading, and large files are tailed to the last N lines), shows line numbers
// via the viewport gutter, supports in-pane search (/ then n/N), reload (r), copy
// path (c), and open in $EDITOR (e) via tea.ExecProcess. Long lines pre-wrap to
// the viewport width (SoftWrap). Ports LogViewerScreen.
type LogViewer struct {
	styles theme.Styles

	path     string
	label    string
	maxLines int

	vp   viewport.Model
	spin spinner.Model

	loading    bool
	loadErr    string
	rawLines   []string
	totalLines int
	startLine  int
	truncated  bool

	showLineNums bool

	// search state
	search       textinput.Model
	searching    bool
	searchTerm   string
	matchCount   int
	currentMatch int

	width  int
	height int
}

// NewLogViewer builds a log viewer for path with the given label ("stdout" or
// "stderr"). maxLines caps the tail window for large files; pass 0 for the
// default.
func NewLogViewer(styles theme.Styles, path, label string, maxLines int) *LogViewer {
	if maxLines <= 0 {
		maxLines = defaultLogViewerLines
	}
	sp := spinner.New()
	sp.Spinner = spinner.Dot

	vp := viewport.New()
	vp.SoftWrap = true

	si := textinput.New()
	si.Placeholder = "Search…"

	v := &LogViewer{
		styles:       styles,
		path:         path,
		label:        label,
		maxLines:     maxLines,
		vp:           vp,
		spin:         sp,
		search:       si,
		showLineNums: true,
		currentMatch: -1,
	}
	v.applyGutter()
	return v
}

// Init starts the file load and the spinner. Ports LogViewerScreen.on_mount.
func (v *LogViewer) Init() tea.Cmd {
	v.loading = true
	return tea.Batch(v.loadCmd(), v.spin.Tick)
}

// loadCmd reads the file off the main loop (I1). For files longer than maxLines
// only the last maxLines lines are loaded (tail), matching
// LogViewerScreen._load_file / _load_truncated_file.
func (v *LogViewer) loadCmd() tea.Cmd {
	path := v.path
	maxLines := v.maxLines
	return func() tea.Msg {
		return readLogFile(path, maxLines)
	}
}

// readLogFile loads (and tails) the file, returning a logLoadedMsg. It never
// panics: any error is returned as a message field.
func readLogFile(path string, maxLines int) (msg logLoadedMsg) {
	defer func() {
		if r := recover(); r != nil {
			msg = logLoadedMsg{err: fmt.Sprintf("unexpected error reading file: %v", r)}
		}
	}()

	info, err := os.Stat(path)
	if err != nil {
		if os.IsNotExist(err) {
			return logLoadedMsg{err: "File does not exist: " + path}
		}
		return logLoadedMsg{err: "Error reading file: " + err.Error()}
	}
	if info.IsDir() {
		return logLoadedMsg{err: "Not a regular file: " + path}
	}

	f, err := os.Open(path)
	if err != nil {
		if os.IsPermission(err) {
			return logLoadedMsg{err: "Permission denied: " + path}
		}
		return logLoadedMsg{err: "Error reading file: " + err.Error()}
	}
	defer func() { _ = f.Close() }()

	var all []string
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 64*1024), 8*1024*1024)
	for sc.Scan() {
		all = append(all, sc.Text())
	}
	if err := sc.Err(); err != nil {
		return logLoadedMsg{err: "Error reading file: " + err.Error()}
	}

	total := len(all)
	if total <= maxLines {
		return logLoadedMsg{lines: all, totalLines: total, startLine: 1, truncated: false}
	}
	tail := all[total-maxLines:]
	return logLoadedMsg{
		lines:      tail,
		totalLines: total,
		startLine:  total - maxLines + 1,
		truncated:  true,
	}
}

// applyGutter wires the line-number gutter into the viewport when line numbers
// are enabled, else clears it. The gutter renders the absolute line number
// (offset by startLine for tailed files), porting LogViewerScreen's line-number
// formatting.
func (v *LogViewer) applyGutter() {
	if !v.showLineNums {
		v.vp.LeftGutterFunc = viewport.NoGutter
		return
	}
	start := v.startLine
	total := v.startLine + len(v.rawLines) - 1
	width := len(fmt.Sprintf("%d", max(total, 1)))
	v.vp.LeftGutterFunc = func(ctx viewport.GutterContext) string {
		if ctx.Soft {
			return strings.Repeat(" ", width) + " │ "
		}
		return fmt.Sprintf("%*d │ ", width, start+ctx.Index)
	}
}

// Update handles the load result, spinner ticks, search, reload, copy, editor,
// scrolling, and dismissal.
func (v *LogViewer) Update(msg tea.Msg) (Modal, tea.Cmd, bool) {
	switch msg := msg.(type) {
	case logLoadedMsg:
		v.applyLoaded(msg)
		return v, nil, false

	case editorDoneMsg:
		if msg.err != nil {
			return v, toast("Failed to open $EDITOR: " + msg.err.Error()), false
		}
		return v, toast("Closed editor"), false

	case spinner.TickMsg:
		if !v.loading {
			return v, nil, false
		}
		var cmd tea.Cmd
		v.spin, cmd = v.spin.Update(msg)
		return v, cmd, false

	case tea.KeyPressMsg:
		return v.handleKey(msg)
	}
	return v, nil, false
}

// handleKey routes a key press: search input first, then the viewer shortcuts.
func (v *LogViewer) handleKey(msg tea.KeyPressMsg) (Modal, tea.Cmd, bool) {
	if v.searching {
		return v.handleSearchKey(msg)
	}
	switch msg.String() {
	case "esc", "q":
		return v, nil, true
	case "r":
		return v, v.reload(), false
	case "c":
		return v, v.copyPath(), false
	case "e":
		return v, v.openInEditor(), false
	case "g":
		v.vp.GotoTop()
		return v, nil, false
	case "G":
		v.vp.GotoBottom()
		return v, nil, false
	case "l":
		v.showLineNums = !v.showLineNums
		v.applyGutter()
		state := "off"
		if v.showLineNums {
			state = "on"
		}
		return v, toast("Line numbers " + state), false
	case "/":
		if v.loadErr != "" {
			return v, nil, false
		}
		v.searching = true
		v.search.SetValue(v.searchTerm)
		v.search.Focus()
		return v, textinput.Blink, false
	case "n":
		v.vp.HighlightNext()
		return v, nil, false
	case "N":
		v.vp.HighlightPrevious()
		return v, nil, false
	}
	var cmd tea.Cmd
	v.vp, cmd = v.vp.Update(msg)
	return v, cmd, false
}

// handleSearchKey handles input while the search bar is focused: Enter performs
// the search, Esc cancels it.
func (v *LogViewer) handleSearchKey(msg tea.KeyPressMsg) (Modal, tea.Cmd, bool) {
	switch msg.String() {
	case "esc":
		v.searching = false
		v.search.Blur()
		return v, nil, false
	case "enter":
		v.searching = false
		v.search.Blur()
		v.searchTerm = strings.TrimSpace(v.search.Value())
		return v, v.performSearch(), false
	}
	var cmd tea.Cmd
	v.search, cmd = v.search.Update(msg)
	return v, cmd, false
}

// performSearch finds all case-insensitive matches and highlights them in the
// viewport. Ports LogViewerScreen._perform_search/_highlight_matches.
func (v *LogViewer) performSearch() tea.Cmd {
	if v.searchTerm == "" {
		v.vp.ClearHighlights()
		v.matchCount = 0
		v.currentMatch = -1
		return nil
	}
	content := strings.Join(v.rawLines, "\n")
	re, err := regexp.Compile("(?i)" + regexp.QuoteMeta(v.searchTerm))
	if err != nil {
		return toast("Invalid search")
	}
	matches := re.FindAllStringIndex(content, -1)
	v.matchCount = len(matches)
	if v.matchCount == 0 {
		v.vp.ClearHighlights()
		v.currentMatch = -1
		return toast("No matches found")
	}
	v.vp.SetHighlights(matches)
	v.currentMatch = 0
	return toast(fmt.Sprintf("Found %d matches", v.matchCount))
}

// applyLoaded renders the loaded file (or error) into the viewport, adds a
// truncation header when tailed, and scrolls to the bottom. Ports
// _on_load_complete and the truncation-header text.
func (v *LogViewer) applyLoaded(msg logLoadedMsg) {
	v.loading = false
	if msg.err != "" {
		v.loadErr = msg.err
		v.rawLines = nil
		v.vp.SetContent(v.styles.Error.Render("Error: " + msg.err))
		return
	}
	v.loadErr = ""
	v.rawLines = msg.lines
	v.totalLines = msg.totalLines
	v.startLine = msg.startLine
	v.truncated = msg.truncated
	v.applyGutter()

	body := strings.Join(msg.lines, "\n")
	if len(msg.lines) == 0 {
		body = "(empty file)"
	}
	if v.truncated {
		header := fmt.Sprintf("File truncated: showing last %d of %d lines\n%s\n\n",
			len(msg.lines), v.totalLines, strings.Repeat("─", 40))
		body = header + body
	}
	v.vp.SetContent(body)
	v.vp.GotoBottom()

	// Re-apply an active search against the new content.
	if v.searchTerm != "" {
		v.performSearch()
	}
}

// copyPath copies the file path to the system clipboard off the main loop (I1)
// and toasts the outcome. When no clipboard tool is on PATH it falls back to the
// plain "Path: …" toast so the path is still surfaced. Ports
// LogViewerScreen.action_copy_path (which calls _copy_to_clipboard in a worker).
func (v *LogViewer) copyPath() tea.Cmd {
	path := v.path
	if !clipboardAvailable() {
		return toast("Path: " + path)
	}
	return func() tea.Msg {
		if copyToClipboard(path) {
			return LogToastMsg{Text: "Copied path to clipboard"}
		}
		return LogToastMsg{Text: "Path: " + path}
	}
}

// reload re-reads the file. Ports LogViewerScreen.action_reload.
func (v *LogViewer) reload() tea.Cmd {
	v.loading = true
	v.loadErr = ""
	return tea.Batch(v.loadCmd(), v.spin.Tick, toast("Reloading file…"))
}

// openInEditor launches $EDITOR on the file via tea.ExecProcess, the only place
// in stoei that suspends the program for an interactive child. Ports
// LogViewerScreen._open_in_editor (which wraps app.suspend()). On no editor it is
// a toast no-op.
func (v *LogViewer) openInEditor() tea.Cmd {
	if v.loadErr != "" {
		return toast("Cannot open file: " + v.loadErr)
	}
	editor := resolveEditor()
	if editor == "" {
		return toast("No editor found (set $EDITOR)")
	}
	// #nosec G204 -- editor comes from $EDITOR/a fixed fallback list, path is a
	// validated log path from scontrol/sacct.
	cmd := exec.Command(editor, v.path)
	return tea.ExecProcess(cmd, func(err error) tea.Msg {
		return editorDoneMsg{err: err}
	})
}

// resolveEditor returns $EDITOR when set and on PATH, else the first available
// fallback. Ports editor.get_editor.
func resolveEditor() string {
	if ed := strings.TrimSpace(os.Getenv("EDITOR")); ed != "" {
		if _, err := exec.LookPath(ed); err == nil {
			return ed
		}
	}
	for _, ed := range []string{"vim", "nano", "vi"} {
		if _, err := exec.LookPath(ed); err == nil {
			return ed
		}
	}
	return ""
}

// toast returns a Cmd that emits a LogToastMsg.
func toast(text string) tea.Cmd {
	return func() tea.Msg { return LogToastMsg{Text: text} }
}

// View renders the spinner while loading, otherwise the titled, bordered viewer
// with the path, optional search bar, the content, and a footer hint.
func (v *LogViewer) View() string {
	title := v.styles.Title.Render(strings.ToUpper(v.label) + " Log")
	path := v.styles.Subtle.Render(v.path)

	var body string
	switch {
	case v.loading:
		body = v.spin.View() + " Loading file…"
	default:
		body = v.vp.View()
	}

	footer := v.styles.Subtle.Render(
		"c copy path   g/G top/bot   / search   n/N next/prev   l line#   r reload   e editor   Esc close")
	if v.matchCount > 0 {
		footer = v.styles.Text.Render(fmt.Sprintf("%d matches", v.matchCount)) + "   " + footer
	}

	parts := []string{title, path, ""}
	if v.searching {
		parts = append(parts, v.styles.Text.Render(v.search.View()))
	}
	parts = append(parts, body, "", footer)
	return v.styles.Modal.Render(lipgloss.JoinVertical(lipgloss.Left, parts...))
}

// SetSize sizes the viewer and its inner viewport.
func (v *LogViewer) SetSize(w, h int) {
	mw, mh := modalSize(w, h)
	v.width, v.height = mw, mh

	innerW := mw - modalChromeWidth
	innerH := mh - modalChromeHeight - 2 // path row + search/footer slack
	if innerW < 1 {
		innerW = 1
	}
	if innerH < 1 {
		innerH = 1
	}
	v.vp.SetWidth(innerW)
	v.vp.SetHeight(innerH)
	v.search.SetWidth(max(innerW-2, 10))
}

// SetStyles re-themes the viewer.
func (v *LogViewer) SetStyles(styles theme.Styles) {
	v.styles = styles
	v.vp.HighlightStyle = styles.Warning.Reverse(true)
	v.vp.SelectedHighlightStyle = styles.Success.Reverse(true)
}

// ShortHelp returns the viewer's bindings.
func (v *LogViewer) ShortHelp() []key.Binding {
	return []key.Binding{
		key.NewBinding(key.WithKeys("/"), key.WithHelp("/", "search")),
		key.NewBinding(key.WithKeys("n", "N"), key.WithHelp("n/N", "next/prev")),
		key.NewBinding(key.WithKeys("r"), key.WithHelp("r", "reload")),
		key.NewBinding(key.WithKeys("e"), key.WithHelp("e", "editor")),
		key.NewBinding(key.WithKeys("esc"), key.WithHelp("esc", "close")),
	}
}

// FullHelp returns the expanded bindings.
func (v *LogViewer) FullHelp() [][]key.Binding { return [][]key.Binding{v.ShortHelp()} }

// Compile-time assertion that LogViewer satisfies Modal.
var _ Modal = (*LogViewer)(nil)
