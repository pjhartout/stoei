# Stoei

A terminal UI for monitoring Slurm jobs. It auto-refreshes, summarizes jobs, nodes, users, and cluster load, and lets you inspect, filter, and cancel jobs without leaving the terminal.

[![GitHub release](https://img.shields.io/github/v/release/pjhartout/stoei?label=version)](https://github.com/pjhartout/stoei/releases)
[![Rust](https://img.shields.io/badge/Rust-1.89%2B-orange)](https://www.rust-lang.org/)
[![License](https://img.shields.io/github/license/pjhartout/stoei)](https://github.com/pjhartout/stoei/blob/main/LICENSE)

## Features

- Auto-refreshing job list with running/pending/requeue stats
- Completed-job history merged into the Jobs tab
- Job detail view (`Enter` or `i`) with live/final CPU, RAM, GPU, and disk
  efficiency, plus a log viewer with search and `$EDITOR`
- On-demand per-GPU utilization and VRAM snapshots (`v` in job details)
- Tabs for Jobs, Nodes, Users, Priority, and Logs — the Logs tab records every
  Slurm command stoei runs (with size and timing), fetch failures and
  recoveries, and the feedback from your own actions
- Resizable, collapsible cluster-load sidebar: free vs. allocated nodes/CPU/memory/GPU, and the pending queue
- Quick filtering (`/`), sorting (`o`), and job cancellation (`c`)
- Job modification from the detail view (`m`): array throttle, partition, time
  limit, QOS, hold/release, or any raw `scontrol update` field
- Partition changes check current state and apply only to selected jobs or array
  tasks that are still pending
- Configurable themes and vim/emacs keybindings

The UI uses [Ratatui](https://ratatui.rs/). It redraws when input or data changes
and sleeps between events and refresh deadlines. Four threads serve the app
session: the UI, input and signals, and two I/O workers with bounded queues.
Shutdown wakes input and cancels work; update downloads run in temporary,
deadline-limited helper processes. Log tails and caches have fixed memory limits.

## Installation

stoei runs on Linux login nodes, where the Slurm CLIs it drives (`squeue`,
`scontrol`, …) work. Pick one of the methods below, then check with
`stoei --version`.

### Prebuilt binary (recommended)

Prebuilt releases ship statically linked binaries only for Linux x86-64 (`amd64`)
and AArch64 (`arm64`), in `.tar.gz` archives with `checksums.txt`. Choose the login
node's architecture, not the compute nodes':
MPCDF's [Raven](https://docs.mpcdf.mpg.de/doc/computing/raven-user-guide.html#login-and-interactive-nodes)
and [Viper](https://docs.mpcdf.mpg.de/doc/computing/viper-user-guide.html#login-and-interactive-nodes)
use x86-64, while EuroHPC's [JUPITER](https://apps.fz-juelich.de/jsc/hps/jupiter/configuration.html#jupiter-booster-design)
uses ARM64 login nodes.

Login nodes rarely allow `sudo`, so this installs into `~/.local/bin`:

```bash
case "$(uname -s):$(uname -m)" in
  Linux:x86_64 | Linux:amd64) arch=amd64 ;;
  Linux:aarch64 | Linux:arm64) arch=arm64 ;;
  *) echo "Prebuilt binaries require Linux x86-64 or AArch64." >&2; exit 1 ;;
esac
version=$(curl -fsSL https://api.github.com/repos/pjhartout/stoei/releases/latest | sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p')
archive="stoei_${version}_linux_${arch}.tar.gz"

curl -fsSLO "https://github.com/pjhartout/stoei/releases/download/v${version}/${archive}"
curl -fsSL "https://github.com/pjhartout/stoei/releases/download/v${version}/checksums.txt" | grep "${archive}" | sha256sum -c -
mkdir -p ~/.local/bin && tar -xzf "${archive}" -C ~/.local/bin stoei && rm "${archive}"
```

If `stoei` is not found afterwards, `~/.local/bin` is not on your `PATH`; add
`export PATH="$HOME/.local/bin:$PATH"` to your shell rc and open a new shell.
For a system-wide install, extract into `/usr/local/bin` instead
(`sudo tar -xzf "${archive}" -C /usr/local/bin stoei`).

You can also download the archive by hand from the
[latest release](https://github.com/pjhartout/stoei/releases/latest) and copy
the `stoei` binary anywhere on your `PATH`.

### Cargo

With a Rust 1.89+ toolchain:

```bash
cargo install --git https://github.com/pjhartout/stoei --locked
```

This installs `stoei` into `~/.cargo/bin`; make sure that directory is on your
`PATH`.

### From source

```bash
git clone https://github.com/pjhartout/stoei.git
cd stoei
cargo build --release --locked
mkdir -p ~/.local/bin
install -m 755 target/release/stoei ~/.local/bin/stoei
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for a live-reloading dev build.

### Updating

```bash
stoei update
```

It downloads the latest release for your platform, verifies the checksum, and
atomically replaces the running binary in place (so it needs write access to
wherever `stoei` lives). This also turns a Cargo or source build (which
reports `dev` from `stoei --version`) into the latest release. The TUI checks
for a newer release once a day (silently, cached) and shows a hint in the
status bar when one exists; `dev` builds skip that check and never phone home.
The same command upgrades existing Go installations to Rust releases. Restart
stoei after updating to use the new binary.

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

Opening a completed job performs an indexed, single-job `sacct` lookup. If the
controller has already purged the job, entering its ID with `i` falls back to
that accounting record, including for other users when cluster privacy policy
allows it. Live efficiency remains visible only to the job's owner because
Slurm restricts non-root `sstat` queries.

Reopening your running job refreshes its runtime and allocation before sampling
usage again. CPU efficiency is relative to all allocated CPUs, not a single core;
disk throughput is averaged over the refreshed runtime.

For a current GPU snapshot, open your running job with `Enter`, then press `v`.
The popup shows utilization and VRAM used/total for each allocated NVIDIA GPU.
Press `r` to take another snapshot and `Esc` to return to job details. Snapshots
run only on request, using non-interactive SSH to the allocated compute nodes;
SSH access and `nvidia-smi` on those nodes are required. Readings cover the whole
GPU, so shared devices include other processes. Unsupported device mappings and
MIG allocations report an unavailable message.

> [!WARNING]
> stoei polls `slurmctld` for live state. Automatic personal-job refreshes run at
> most once every two minutes; cluster-wide queries run less often, are staggered, and
> back off after failures. Each session polls independently, so administrators
> may still ask users to select a longer refresh interval on busy clusters.

Press `r` (`C-r` in emacs mode) to refresh immediately. Requests already in flight
are shared, and “Refreshing…” stays visible until they finish. Your resource totals
update together with your personal job list.

### Keyboard shortcuts

The table shows the default **vim** preset; in **emacs** mode the global, filter,
and sort keys are rebound to their `ctrl`-prefixed equivalents (`C-r`, `C-s`,
`C-o`, …). Press `?` in-app for the full, always-current list.

| Key | Action |
|-----|--------|
| `1`–`5` | Switch tab: Jobs / Nodes / Users / Priority / Logs |
| `Tab` / `Shift+Tab` | Next / previous tab |
| `↑` / `↓` (`k` / `j`) | Navigate rows |
| `←` / `→` | Scroll the table horizontally when columns overflow |
| `Enter` | View the selected row's details |
| `v` | Job details: current GPU utilization and VRAM snapshot |
| `i` | Enter a job ID to view (Jobs tab) |
| `c` | Cancel the selected job (Jobs tab) |
| `/` | Filter (`col:value` or substring) |
| `Esc` | Close / clear the filter |
| `o` | Cycle sort order |
| `r` / `p` | Users tab: Running / Pending pane |
| `m` / `u` / `a` / `j` | Priority tab: My / Active Users / Accounts / Jobs pane |
| `r` | Refresh now (on the Users tab, `r` switches pane instead) |
| `L` | Cluster load (scrollable popup) |
| `b` | Collapse / restore the cluster sidebar |
| `[` / `]` | Narrow / widen the sidebar by four columns |
| `=` | Restore automatic sidebar width |
| `Alt` + `↑` / `↓` | Scroll the sidebar vertically |
| `s` | Settings |
| `?` | Help |
| `q` | Quit |

The sidebar starts at roughly one third of the terminal width, capped at 44
columns, rather than expanding to fit long GPU or partition names. Resizing
always leaves at least 60 columns for the active tab. Width and collapse choices
last for the current session and survive terminal resizing; `=` resumes automatic
sizing. On narrow or short terminals the sidebar auto-hides. Long lines are
clipped; widen the sidebar or press `L` for the full cluster-load popup, which
supports arrow-key scrolling in both directions.

Config lives at `${XDG_CONFIG_HOME:-~/.config}/stoei/config.yaml` (theme, 120–300 second refresh interval, history window, keybindings) and can be edited in-app via `s`.

### Reading the Priority tab

Why is my job waiting, and when will that change? The **My Priority** pane
(`4`, then `m`) answers that from `sshare`, `sprio`, and the cluster's priority
settings:

- **Fair-share factor** is the number Slurm actually ranks you on, with your
  rank among the users who used the cluster recently ("147 of 171 active users").
- **Usage vs share** is recent usage divided by your configured share: `1×`
  means you used exactly your share, `12.5×` means twelve times it, which is why
  the factor is low. Usage decays with the cluster's half-life, so the pane
  estimates how long an idle account needs to get back to `1×`.
- **How priority is computed here** lists the factor weights the cluster
  configured and what share of your jobs' priority each factor contributes. On
  most clusters fair-share dominates and age or job size barely matter.
- **Your Pending Jobs** is read per partition, because that is how Slurm
  schedules: each partition is filled from its own queue and the partition
  factor differs between them, so only jobs in the same partition compete. For
  every partition you are queued in it shows where your best job sits and how
  many jobs are ahead of it, then each job's queue position and the weighted
  breakdown of its priority.

**Active Users** ranks everyone with recent usage (idle users are hidden, since
the scheduler parks them all at the top with the same factor); **Accounts**
ranks accounts best-served first; **Jobs** lists every pending job grouped by
partition in queue order (with the cluster-wide rank as a secondary column).
`Enter` on a user or account opens the same summary for them.

## Requirements

- Linux on x86-64 or AArch64
- Slurm CLIs on `PATH`: `squeue`, `scontrol` (plus `sshare`/`sprio`/`scancel` for the Priority tab and cancellation)
- A login node where those commands talk to your cluster

Job history comes from the controller (a per-user `squeue -t all` snapshot plus `scontrol show jobid` completion records) accumulated into a persistent journal at `${XDG_DATA_HOME:-~/.local/share}/stoei/jobs.jsonl`. Once per day — shared across sessions via a stamp file next to the journal, so frequent restarts don't repeat it — the journal is reconciled against a single per-user `sacct` query, which backfills jobs that finished (or ran entirely) while stoei was not watching; when `sacct` is unavailable stoei warns once and the history reflects only jobs stoei has observed. Run `stoei reset` to clear the journal.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for building from source, the local debug
build, the checks to run, and the release process.

## License

MIT License — see [LICENSE](LICENSE) for details.
