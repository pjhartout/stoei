---
title: "feat: Set terminal/tmux tab title to stoei"
type: feat
date: 2026-03-24
---

# Set terminal/tmux tab title to "stoei"

## Overview

When running `stoei`, the tmux tab (and terminal title bar) shows "python3" because that's the interpreter name. This change sets the terminal title to "stoei" on startup and restores default title behavior on exit.

## Proposed Solution

Add two functions in `stoei/__main__.py` following the existing `_ensure_truecolor()` pattern:

- `_set_terminal_title(title: str)` — emits escape sequences to set the title
- `_restore_terminal_title()` — emits empty title sequences to restore default behavior

Call them in `run()` with a try/finally around the `main()` call.

## Technical Approach

### Escape sequences

Emit **both** of the following:

1. **OSC 2** (`\033]2;stoei\033\\`) — standard xterm window title, works in most terminal emulators
2. **tmux window name** (`\033kstoei\033\\`) — sets the tmux tab name in the status bar. Only emit when `$TMUX` is set.

### Restore strategy

On exit, emit the same sequences with an empty title string:
- `\033]2;\033\\` — clears xterm title (terminal resumes default)
- `\033k\033\\` — clears tmux window name (tmux resumes `automatic-rename` behavior)

This avoids the need to query/save the original title (which is unreliable across terminals).

### Guards

- **TTY check**: Skip all escape sequences if `sys.stdout.isatty()` is `False` (piped/redirected output)
- **Write target**: Write to `sys.stdout` and flush — safe because sequences are emitted before Textual takes over the terminal and after it returns

### Placement in `run()`

```
stoei/__main__.py::run()
```

```
1. _ensure_truecolor()
2. _set_terminal_title("stoei")    # NEW
3. try:
4.     main()
5. finally:
6.     _restore_terminal_title()   # NEW
```

The existing `except Exception` block in `run()` stays inside the try/finally, so the title is restored on both clean exit and crash.

### Out of scope

- Querying/saving the original terminal title (unreliable, unnecessary)
- GNU screen support (`$STY`)
- Title toggle on app suspend/resume
- Re-enabling tmux `automatic-rename` via subprocess call (empty title achieves the same effect)

## Acceptance Criteria

- [x] Running `stoei` in tmux sets the tab name to "stoei"
- [x] Running `stoei` in a regular terminal sets the window title to "stoei"
- [x] Exiting stoei (clean quit or crash) restores default terminal title behavior
- [x] No escape sequences emitted when stdout is not a TTY
- [x] tmux-specific escape only emitted when `$TMUX` is set
- [x] Unit tests cover: TTY vs non-TTY, tmux vs non-tmux, normal exit, exception exit

## Files to modify

| File | Change |
|------|--------|
| `stoei/__main__.py` | Add `_set_terminal_title()`, `_restore_terminal_title()`, wrap `main()` call in try/finally |
| `tests/unit/test_main.py` | Add tests for the two new functions and the try/finally behavior |

## References

- Existing pattern: `_ensure_truecolor()` in `stoei/__main__.py:15`
- OSC escape sequences: [XTerm Control Sequences](https://invisible-island.net/xterm/ctlseqs/ctlseqs.html)
- tmux window naming: `\033k...\033\\` (DCS passthrough)
