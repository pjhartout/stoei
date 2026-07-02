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
- Configurable themes and vim/emacs keybindings

## Installation

stoei is a single static binary with no runtime dependencies.

### Prebuilt binary (recommended)

Download the archive for your platform from the [latest release](https://github.com/pjhartout/stoei/releases/latest), extract it, and put `stoei` on your `PATH`:

```bash
# Linux x86_64 example — adjust the URL for your OS/arch
curl -L https://github.com/pjhartout/stoei/releases/latest/download/stoei_<version>_linux_amd64.tar.gz | tar xz
sudo install stoei /usr/local/bin/
```

Binaries are published for Linux, macOS, and Windows (amd64 and arm64).

### go install

With a Go 1.25+ toolchain:

```bash
go install github.com/pjhartout/stoei/cmd/stoei@latest
```

This installs `stoei` into `$(go env GOPATH)/bin`.

### From source

```bash
git clone https://github.com/pjhartout/stoei.git
cd stoei
go build -o stoei ./cmd/stoei
./stoei
```

## Usage

```bash
stoei
```

stoei runs the Slurm CLIs (`squeue`, `scontrol`, `sshare`, `sprio`, `scancel`) as the current user, so run it from a login node where those commands work. It never queries `sacct`/slurmdbd. Check the version with `stoei --version`.

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

Job history comes from the controller (a per-user `squeue -t all` snapshot plus `scontrol show jobid` completion records) accumulated into a persistent journal at `${XDG_DATA_HOME:-~/.local/share}/stoei/jobs.jsonl` — `sacct`/`slurmdbd` is never queried, so the history reflects jobs stoei has observed (running, pending, and recently finished), building up over time. Run `stoei reset` to clear the journal.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for building from source, the local debug
build, the checks to run, and the release process.

## License

MIT License — see [LICENSE](LICENSE) for details.
