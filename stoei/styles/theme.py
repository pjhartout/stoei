"""Theme documentation for the stoei TUI.

The actual CSS styles are in the .tcss files in this directory:
- app.tcss: Main application styles
- modals.tcss: Modal screen styles

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
