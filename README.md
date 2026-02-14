# Stoei

A terminal UI for monitoring Slurm jobs. It auto-refreshes every 5 seconds and summarizes jobs, nodes, and users.

[![GitHub release](https://img.shields.io/github/v/tag/pjhartout/stoei?label=version)](https://github.com/pjhartout/stoei/releases)
[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/pjhartout/stoei)](https://github.com/pjhartout/stoei/blob/main/LICENSE)

### Install & Launch

<video src="demo/install.mp4" autoplay loop muted playsinline></video>

### Jobs

<video src="demo/jobs.mp4" autoplay loop muted playsinline></video>

### Nodes

<video src="demo/nodes.mp4" autoplay loop muted playsinline></video>

### Users

<video src="demo/users.mp4" autoplay loop muted playsinline></video>

### Priority

<video src="demo/priority.mp4" autoplay loop muted playsinline></video>

### Filtering

<video src="demo/filtering.mp4" autoplay loop muted playsinline></video>

## Features

- Auto-refreshing job list (5s)
- Job stats (running, pending, requeues)
- Job history (last 24 hours)
- Job detail view (Enter or `i`)
- Tabs for Jobs, Nodes, Users, and Priority
- Quick filtering (`/`)

## Installation

### Run with uvx (no install)

Prerequisite: install [uv](https://github.com/astral-sh/uv#installation).

```bash
uvx git+https://github.com/pjhartout/stoei.git
```

Specific version:
```bash
uvx git+https://github.com/pjhartout/stoei.git@v0.2.7
```

Optional alias:
```bash
alias stoei='uvx git+https://github.com/pjhartout/stoei.git'
```

### Install as a tool (uv)

```bash
uv tool install git+https://github.com/pjhartout/stoei.git
```

Upgrade or uninstall:
```bash
uv tool install --upgrade git+https://github.com/pjhartout/stoei.git
uv tool uninstall stoei
```

### From source

```bash
git clone https://github.com/pjhartout/stoei.git
cd stoei
uv sync
uv run stoei
```

### Alternative: pip

```bash
pip install git+https://github.com/pjhartout/stoei.git
```

## Usage

```bash
stoei
```

If you are using `uvx` directly:
```bash
uvx git+https://github.com/pjhartout/stoei.git
```

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Refresh |
| `i` | Enter job ID |
| `Enter` | View selected job details |
| `↑/↓` | Navigate jobs |
| `Tab` | Switch tables |
| `1` | Jobs tab |
| `2` | Nodes tab |
| `3` | Users tab |

## Requirements

- Python 3.11+
- Slurm commands available: `squeue`, `sacct`, `scontrol`

## Development

```bash
git clone https://github.com/pjhartout/stoei.git
cd stoei
uv sync --all-extras
uv run pre-commit install
```

Run tests:
```bash
uv run pytest
```

Lint and format:
```bash
uv run ruff format --check .
uv run ruff check .
```

Type check:
```bash
uv run ty check stoei/
```

Mock Slurm data:
```bash
./scripts/run_with_mocks.sh
```

If you run the TUI during development, use `timeout 10 stoei` to avoid hanging.

## Logging

Logs are written to stdout and `~/.stoei/logs/`. Files rotate daily and are kept for 1 week.

## Releases

Tags on GitHub create releases. See the [releases page](https://github.com/pjhartout/stoei/releases).

## License

MIT License - see LICENSE for details.

## Contributing

Before opening a PR, run tests, lint, format, and type checks as described in [CONTRIBUTING.md](CONTRIBUTING.md).

## Related projects

GitHub is full of related projects. Fundamentally I just wanted a way to easily look at my logs, cancel and monitor requeued jobs, which I don't think is supported by existing solutions.

## What's in a name? 

`stoei` is a Dutch verb meaning "wrestle", because that's what it feels like sometimes to manage these jobs... it's also an alternative spelling for SLURM Terminal User Interface (STUI).
