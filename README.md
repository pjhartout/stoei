# Stoei

A terminal UI for monitoring Slurm jobs. It auto-refreshes, summarizes jobs, nodes, users, and cluster load, and lets you inspect, filter, and cancel jobs without leaving the terminal.

[![GitHub release](https://img.shields.io/github/v/release/pjhartout/stoei?label=version)](https://github.com/pjhartout/stoei/releases)
[![Go Version](https://img.shields.io/github/go-mod/go-version/pjhartout/stoei)](https://go.dev/)
[![License](https://img.shields.io/github/license/pjhartout/stoei)](https://github.com/pjhartout/stoei/blob/main/LICENSE)

## Features

- Auto-refreshing job list with running/pending/requeue stats
- Completed-job history merged into the Jobs tab
- Job detail view (`Enter` or `i`) and a log viewer with search and `$EDITOR`
- Tabs for Jobs, Nodes, Users, Priority, and Logs
- Cluster-load sidebar: free vs. allocated nodes/CPU/memory/GPU, and the pending queue
- Quick filtering (`/`), sorting (`o`), and job cancellation (`c`)
- Job modification from the detail view (`m`): array throttle, partition, time
  limit, QOS, hold/release, or any raw `scontrol update` field
- Configurable themes and vim/emacs keybindings

## Installation

stoei is a single static binary with no runtime dependencies. Install it on a
login node: that is where the Slurm CLIs it drives (`squeue`, `scontrol`, …)
work. Pick one of the methods below, then check with `stoei --version`.

### Prebuilt binary (recommended)

Releases ship for Linux and macOS (amd64, arm64) as `.tar.gz` and for Windows as
`.zip`, with a `checksums.txt`. Login nodes rarely allow `sudo`, so this installs
into `~/.local/bin`:

```bash
version=$(curl -fsSL https://api.github.com/repos/pjhartout/stoei/releases/latest | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p')
os=$(uname -s | tr '[:upper:]' '[:lower:]')                 # linux or darwin
arch=$(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')  # amd64 or arm64
archive="stoei_${version}_${os}_${arch}.tar.gz"

curl -fsSLO "https://github.com/pjhartout/stoei/releases/download/v${version}/${archive}"
curl -fsSL "https://github.com/pjhartout/stoei/releases/download/v${version}/checksums.txt" | grep "${archive}" | sha256sum -c -
mkdir -p ~/.local/bin && tar -xzf "${archive}" -C ~/.local/bin stoei && rm "${archive}"
```

On macOS use `shasum -a 256 -c -` in place of `sha256sum -c -`. If `stoei` is not
found afterwards, `~/.local/bin` is not on your `PATH`; add
`export PATH="$HOME/.local/bin:$PATH"` to your shell rc and open a new shell.
For a system-wide install, extract into `/usr/local/bin` instead
(`sudo tar -xzf "${archive}" -C /usr/local/bin stoei`).

You can also download the archive by hand from the
[latest release](https://github.com/pjhartout/stoei/releases/latest) and copy
the `stoei` binary anywhere on your `PATH`.

### go install

With a Go 1.25+ toolchain:

```bash
go install github.com/pjhartout/stoei/cmd/stoei@latest
```

This installs `stoei` into `$(go env GOPATH)/bin` (usually `~/go/bin`); make sure
that directory is on your `PATH`.

### From source

```bash
git clone https://github.com/pjhartout/stoei.git
cd stoei
go build -o ~/.local/bin/stoei ./cmd/stoei
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for a live-reloading dev build.

### Updating

```bash
stoei update
```

It downloads the latest release for your platform, verifies the checksum, and
atomically replaces the running binary in place (so it needs write access to
wherever `stoei` lives). This also turns a `go install` or source build (which
reports `dev` from `stoei --version`) into the latest release. The TUI checks
for a newer release once a day (silently, cached) and shows a hint in the
status bar when one exists; `dev` builds skip that check and never phone home.

### Uninstalling

Delete the binary plus stoei's config, job journal, and update cache:

```bash
rm -f ~/.local/bin/stoei
rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/stoei" "${XDG_DATA_HOME:-$HOME/.local/share}/stoei" "${XDG_CACHE_HOME:-$HOME/.cache}/stoei"
```

## Usage

```bash
stoei
```

stoei runs the Slurm CLIs (`squeue`, `scontrol`, `sshare`, `sprio`, `scancel`) as the current user, so run it from a login node where those commands work. It queries `sacct`/slurmdbd at most once a night to reconcile the job-history journal, at a per-user minute between 01:00 and 05:00 local time so many users' sessions do not hit the accounting database together (or at the next launch, if stoei was not running then). Check the version with `stoei --version`.

> [!WARNING]
> stoei polls the Slurm controller (headnode) directly on every refresh, since
> it reads live state via `squeue`/`scontrol` rather than the accounting
> database. On busy clusters a short refresh interval multiplied across many
> users adds load to slurmctld — raise the refresh interval if your admins ask.

### Keyboard shortcuts

The table shows the default **vim** preset; in **emacs** mode the global, filter,
and sort keys are rebound to their `ctrl`-prefixed equivalents (`C-r`, `C-s`,
`C-o`, …). Press `?` in-app for the full, always-current list.

| Key | Action |
|-----|--------|
| `1`–`5` | Switch tab: Jobs / Nodes / Users / Priority / Logs |
| `Tab` / `Shift+Tab` | Next / previous tab |
| `↑` / `↓` (`k` / `j`) | Navigate rows |
| `Enter` | View the selected row's details |
| `i` | Enter a job ID to view (Jobs tab) |
| `c` | Cancel the selected job (Jobs tab) |
| `/` | Filter (`col:value` or substring) |
| `Esc` | Close / clear the filter |
| `o` | Cycle sort order |
| `r` / `p` | Users tab: Running / Pending pane |
| `m` / `u` / `a` / `j` | Priority tab: My / All Users / Accounts / Jobs pane |
| `r` | Refresh now (on the Users tab, `r` switches pane instead) |
| `L` | Cluster load (scrollable popup) |
| `s` | Settings |
| `?` | Help |
| `q` | Quit |

Config lives at `${XDG_CONFIG_HOME:-~/.config}/stoei/config.yaml` (theme, refresh interval, history window, keybindings) and can be edited in-app via `s`.

## Requirements

- Slurm CLIs on `PATH`: `squeue`, `scontrol` (plus `sshare`/`sprio`/`scancel` for the Priority tab and cancellation)
- A login node where those commands talk to your cluster

Job history comes from the controller (a per-user `squeue -t all` snapshot plus `scontrol show jobid` completion records) accumulated into a persistent journal at `${XDG_DATA_HOME:-~/.local/share}/stoei/jobs.jsonl`. Once per day — shared across sessions via a stamp file next to the journal, so frequent restarts don't repeat it — the journal is reconciled against a single per-user `sacct` query, which backfills jobs that finished (or ran entirely) while stoei was not watching; when `sacct` is unavailable stoei warns once and the history reflects only jobs stoei has observed. Run `stoei reset` to clear the journal.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for building from source, the local debug
build, the checks to run, and the release process.

## License

MIT License — see [LICENSE](LICENSE) for details.
