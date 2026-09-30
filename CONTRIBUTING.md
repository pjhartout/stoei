# Contributing to Stoei

Install Rust 1.89 or newer on Linux or macOS, including rustfmt and Clippy.

```bash
git clone https://github.com/pjhartout/stoei.git
cd stoei
cargo build --locked
```

For a local build on your PATH:

```bash
cargo build --release --locked
mkdir -p ~/.local/bin
install -m 755 target/release/stoei ~/.local/bin/stoei
```

Rebuild after source changes. Alternatively, symlink `scripts/stoei-dev` onto
your PATH to build the current checkout on launch.

The dependency direction is `ui → store → slurm`. `src/engine` wires the event
loop and bounded background workers; `src/config` and `src/update` handle
persistence and releases. The UI changes plain data and emits effects; workers
perform disk, network, and scheduler IO. Rendering runs only after a visible
state change. Keep the main loop free of polling and animation timers.

Run the checks before pushing:

```bash
cargo fmt --all -- --check
cargo clippy --all-targets --locked -- -D warnings
cargo test --all-targets --locked
cargo build --release --locked
```

Tests must use fake `Runner` implementations and the golden fixtures in
`tests/fixtures`; they must never reach a real scheduler. Inject time into
scheduling decisions. Do not run the TUI in automation; use Ratatui's
`TestBackend` to verify rendered screens.

Use `scripts/release <version>` to check a clean, gated `main`, create the tag,
and push it. The release workflow builds Linux static musl binaries and macOS
binaries for amd64 and arm64. Archive names and `checksums.txt` remain compatible
with the self-updater.

PR descriptions contain only a summary. Keep commits focused and attribute
them solely to the human author.
