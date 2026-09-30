# Project description

stoei is a terminal UI for monitoring Slurm jobs. Users browse, filter, inspect,
and cancel jobs, and see cluster load — all without leaving the terminal.

# Tech stack

- Rust **1.89+**, Ratatui, and Crossterm. Use the Cargo toolchain.
- Build with `cargo build --release --locked`.
- Format with `cargo fmt`; lint with Clippy.
- Support Linux and macOS. Release single binaries via GitHub Actions; Linux
  releases use static musl and macOS builds use its native toolchain.
  `cargo install` also works.
- **Stale-binary trap:** when a bug looks already-fixed in source, suspect the
  installed binary is old before re-debugging. `stoei update` pulls the latest
  *release*, which can lag unreleased local commits. Compare the binary mtime
  against the fixing commit's date, then rebuild
  (`cargo build --release --locked` followed by
  `install -m 755 target/release/stoei ~/.local/bin/stoei`).

## Architecture

Dependencies flow one way: `ui → store → slurm`. The store never imports the UI;
Slurm never imports the store. `engine` connects UI effects to bounded IO workers.
Tests use fake `slurm::Runner`, injected clocks, store datasets, and Ratatui's
`TestBackend`.

Lowest idle CPU/RAM is the design priority. The UI blocks between input, data,
resize, and actual deadlines; do not add frame or animation timers. Keep queues,
logs, caches, command output, and log tails bounded. All disk, network, and
scheduler IO happens on workers. Interactive and background requests use separate
queues; generation tags reject stale refreshes and tokens reject stale modals.
Every thread needs a defined purpose and a lifetime tied to the app session or
an operation. Bound thread counts and request queues; stop and join workers on
shutdown. Keep blocking DNS inside cancellable helper processes, not detached
resolver threads in the app.

## Maintainability

Easily maintainable, minimal coupling. If a pattern fits this project, apply it;
otherwise favor functionality over pattern purity.

## Testing

- Standard `cargo test --all-targets --locked`. Tests **must never reach a real
  scheduler** — use fake `slurm::Runner` implementations and golden fixtures under
  `tests/fixtures/`.
- No sleeps, no wall-clock; inject clocks where time matters.
- The suite must stay fast (well under 20s) — fix slow tests at the root cause,
  never paper over them with timeouts.
- **Do NOT run the TUI itself** (`cargo run`) in development/testing — it
  blocks on a terminal. Verify with the test suite instead.

## Docstrings

Use standard Rust documentation comments for public interfaces where useful.
Comments explain *why*, not *what*.

## Documentation

Prefer self-explanatory code. The README is the user's getting-started guide.

## Notifications

**Never show the same error notification repeatedly.** If a background refresh
fails on a recurring cycle, notify the user once (edge-triggered); only re-notify
after it recovers and then fails again. Manual user-triggered actions always get
feedback regardless.

## Code style

- Format with `cargo fmt`; keep `cargo clippy --all-targets --locked -- -D warnings` clean.
- No useless comments. No section-separator comments. No dead code.
- Imports grouped stdlib / third-party / local.

## Agent Auto-run Commands

**CRITICAL: After making ANY code change, automatically run:**

```bash
cargo fmt --all
cargo clippy --all-targets --locked -- -D warnings
cargo test --all-targets --locked
cargo build --release --locked
```

**Do NOT ask the user — just run these after code changes.**

## Pull Requests

PR descriptions contain only a summary of the changes. No test plan, checklist, or
any other sections beyond the summary.

## Commit Attribution

AI agents (Claude, Cursor, etc.) must NOT add themselves as co-authors. Do not use
`Co-Authored-By` trailers or any other form of AI attribution. Commits should only
attribute human contributors.
