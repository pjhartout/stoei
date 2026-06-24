// Package config loads and persists user configuration (theme, refresh
// intervals, history days, log-viewer lines, keybind mode). It
// exposes a pure Load function over bytes plus a thin file wrapper, with
// embedded defaults and an XDG config path.
package config
