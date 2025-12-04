"""Theme and CSS styles for the TUI.

Uses ANSI color references to inherit from terminal's color scheme.
This ensures compatibility with tmux and terminals configured with Nord or other themes.

ANSI color mapping (typical Nord):
  0/black     → nord1    8/bright_black   → nord3
  1/red       → nord11   9/bright_red     → nord11
  2/green     → nord14  10/bright_green   → nord14
  3/yellow    → nord13  11/bright_yellow  → nord13
  4/blue      → nord10  12/bright_blue    → nord9
  5/magenta   → nord15  13/bright_magenta → nord15
  6/cyan      → nord8   14/bright_cyan    → nord7
  7/white     → nord5   15/bright_white   → nord6
  background  → nord0   foreground        → nord4
"""

ANSI_CSS = """
/* Use terminal's configured colors via ANSI references */

Screen {
    background: $background;
}

Header {
    background: ansi_black;
    color: ansi_cyan;
}

Footer {
    background: ansi_black;
    color: $foreground;
}

Footer > .footer--key {
    background: ansi_bright_black;
    color: ansi_cyan;
}

Footer > .footer--description {
    color: $foreground;
}

#stats-container {
    height: auto;
    padding: 1;
    border: heavy ansi_bright_black;
    margin-bottom: 1;
    background: ansi_black;
}

JobStats {
    color: $foreground;
}

#running-table {
    height: 1fr;
    border: heavy ansi_blue;
    margin-bottom: 1;
    background: $background;
}

#history-table {
    height: 2fr;
    border: heavy ansi_bright_black;
    background: $background;
}

#running-table Static, #history-table Static {
    color: ansi_cyan;
    background: ansi_black;
    padding: 0 1;
}

DataTable {
    height: 1fr;
    width: 100%;
    background: $background;
}

DataTable > .datatable--header {
    text-style: bold;
    background: ansi_black;
    color: ansi_cyan;
}

DataTable > .datatable--cursor {
    background: ansi_bright_black;
    color: ansi_bright_white;
}

DataTable > .datatable--hover {
    background: ansi_black;
}

DataTable > .datatable--even-row {
    background: $background;
}

DataTable > .datatable--odd-row {
    background: ansi_black;
}

VerticalScroll {
    scrollbar-background: ansi_black;
    scrollbar-color: ansi_bright_black;
    scrollbar-color-hover: ansi_bright_blue;
    scrollbar-color-active: ansi_cyan;
}

/* Modal screens for job info */
JobInputScreen {
    align: center middle;
    background: rgba(0, 0, 0, 0.7);
}

JobInputScreen > Vertical {
    width: 70;
    height: auto;
    padding: 2 3;
    background: ansi_black;
    border: double ansi_cyan;
}

JobInputScreen #input-title {
    width: 100%;
    content-align: center middle;
    padding: 1;
    margin-bottom: 1;
    color: ansi_cyan;
    text-style: bold;
    border-bottom: solid ansi_bright_black;
}

JobInputScreen #input-hint {
    width: 100%;
    content-align: center middle;
    color: ansi_bright_black;
    margin-bottom: 1;
}

JobInputScreen Input {
    width: 100%;
    margin: 1 0;
    border: tall ansi_cyan;
    background: $background;
}

JobInputScreen Input:focus {
    border: tall ansi_bright_cyan;
}

JobInputScreen #button-row {
    width: 100%;
    height: auto;
    layout: horizontal;
    margin-top: 1;
}

JobInputScreen Button {
    width: 1fr;
    margin: 0 1;
}

JobInputScreen #submit-btn {
    background: ansi_blue;
}

JobInputScreen #cancel-btn {
    background: ansi_bright_black;
}

JobInfoScreen {
    align: center middle;
    background: rgba(0, 0, 0, 0.8);
}

JobInfoScreen > Vertical {
    width: 95%;
    max-width: 120;
    height: 90%;
    padding: 0;
    background: ansi_black;
    border: double ansi_cyan;
}

JobInfoScreen #job-info-header {
    width: 100%;
    height: auto;
    padding: 1 2;
    background: ansi_black;
    border-bottom: heavy ansi_cyan;
}

JobInfoScreen #job-info-title {
    width: 100%;
    content-align: center middle;
    color: ansi_cyan;
    text-style: bold;
}

JobInfoScreen #job-info-subtitle {
    width: 100%;
    content-align: center middle;
    color: ansi_bright_black;
    margin-top: 1;
}

JobInfoScreen #job-info-content {
    height: 1fr;
    padding: 1 2;
    background: $background;
}

JobInfoScreen #job-info-text {
    width: 100%;
    color: $foreground;
}

JobInfoScreen #error-container {
    height: 1fr;
    padding: 2;
    content-align: center middle;
    background: $background;
}

JobInfoScreen #error-icon {
    width: 100%;
    content-align: center middle;
    color: ansi_red;
    text-style: bold;
}

JobInfoScreen #error-text {
    width: 100%;
    content-align: center middle;
    color: ansi_red;
    margin-top: 1;
}

JobInfoScreen #job-info-footer {
    width: 100%;
    height: auto;
    padding: 1 2;
    background: ansi_black;
    border-top: solid ansi_bright_black;
    layout: horizontal;
    align: center middle;
}

JobInfoScreen #close-button {
    width: auto;
    min-width: 20;
    background: ansi_bright_black;
}

JobInfoScreen #hint-text {
    width: 1fr;
    content-align: right middle;
    color: ansi_bright_black;
    margin-right: 2;
}
"""
