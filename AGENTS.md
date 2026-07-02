# Project description

stoei is a terminal UI for monitoring Slurm jobs. Users browse, filter, inspect,
and cancel jobs, and see cluster load — all without leaving the terminal.

# Tech stack

- TUI on the Charm stack: **Bubble Tea v2** (`charm.land/bubbletea/v2`), Lip Gloss
  v2, Bubbles v2. These require **Go >= 1.25**.
- Build and run with the Go toolchain (`go build ./...`, `go run ./cmd/stoei`).
- Lint with `golangci-lint` (config in `.golangci.yml`); format with `gofmt`.
- Ship as a single static binary via GoReleaser; `go install` also works.

## Architecture

Dependencies flow one way: `ui → store → slurm`, enforced by depguard. The store
never imports the UI; the slurm package never imports the store. Three test seams:
`slurm.Runner`, `store.SlurmClient`, and the UI `Modal`/`Component` interfaces.

Async responsiveness is the #1 design driver. All IO happens inside `tea.Cmd`
closures, never on the Update path. Refresh is two-tier (fast `squeue`, slow
journal/nodes); each ticker re-arms once from its own handler; store setters drop
stale results by generation tag so the UI never blocks or shows out-of-order data.

## Maintainability

Easily maintainable, minimal coupling. If a pattern fits this project, apply it;
otherwise favor functionality over pattern purity.

## Testing

- Standard `go test ./... -race`. Tests **must never reach a real scheduler** — use
  the `slurm.Runner` / `store.SlurmClient` fakes and the golden fixtures under
  `internal/slurm/testdata/`.
- No sleeps, no wall-clock; inject clocks where time matters.
- The suite must stay fast (well under 20s) — fix slow tests at the root cause,
  never paper over them with timeouts.
- **Do NOT run the TUI itself** (`go run ./cmd/stoei`) in development/testing — it
  blocks on a terminal. Verify with the test suite instead.

## Docstrings

Use standard Go doc comments (full sentences starting with the identifier name).
Comments explain *why*, not *what*.

## Documentation

Prefer self-explanatory code. The README is the user's getting-started guide.

## Notifications

**Never show the same error notification repeatedly.** If a background refresh
fails on a recurring cycle, notify the user once (edge-triggered); only re-notify
after it recovers and then fails again. Manual user-triggered actions always get
feedback regardless.

## Code style

- Format with `gofmt`; keep `golangci-lint run` clean.
- No useless comments. No section-separator comments. No dead code.
- Imports grouped stdlib / third-party / local.

## Agent Auto-run Commands

**CRITICAL: After making ANY code change, automatically run:**

```bash
gofmt -w .
go vet ./...
golangci-lint run
go test ./... -race
```

**Do NOT ask the user — just run these after code changes.**

## Pull Requests

PR descriptions contain only a summary of the changes. No test plan, checklist, or
any other sections beyond the summary.

## Commit Attribution

AI agents (Claude, Cursor, etc.) must NOT add themselves as co-authors. Do not use
`Co-Authored-By` trailers or any other form of AI attribution. Commits should only
attribute human contributors.
