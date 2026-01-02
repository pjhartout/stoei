# Stoei

A Slurm TUI (Terminal User Interface) for monitoring SLURM jobs. Keep track of your HPC cluster jobs with an intuitive, auto-refreshing interface.

[![GitHub release](https://img.shields.io/github/v/tag/pjhartout/stoei?label=version)](https://github.com/pjhartout/stoei/releases)
[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/pjhartout/stoei)](https://github.com/pjhartout/stoei/blob/main/LICENSE)

## Features

- 🏃 **Real-time monitoring** - Auto-refreshes every 5 seconds
- 📊 **Job statistics** - View total jobs, requeues, and running/pending counts at a glance
- 📜 **Job history** - See your job history from the last 24 hours
- 🔍 **Detailed job info** - Press Enter or 'i' to view comprehensive job details
- 🎨 **Terminal-native colors** - Inherits your terminal's color scheme (works with Nord, Dracula, etc.)

## Installation

### Using uvx (Recommended - No Installation Required)

`uvx` allows you to run `stoei` without installing it. This is perfect for trying out the tool or running it on systems where you don't want to install packages globally.

**Prerequisites:**
- Install `uv` first: [Installation instructions](https://github.com/astral-sh/uv#installation)

**Run the latest version:**
```bash
uvx git+https://github.com/pjhartout/stoei.git
```

**Run a specific version:**
```bash
uvx git+https://github.com/pjhartout/stoei.git@v0.2.3
```

**Benefits of using `uvx`:**
- ✅ No installation required - runs in an isolated environment
- ✅ Always uses the latest version (or specified version)
- ✅ No conflicts with system Python packages
- ✅ Works from any directory
- ✅ Automatic dependency management

**How it works:**
`uvx` creates a temporary virtual environment, installs `stoei` and its dependencies, runs the command, and cleans up afterward. The first run may take a moment to download dependencies, but subsequent runs are faster due to caching.

**Creating an alias (optional):**
If you use `uvx` frequently, you can create a shell alias:
```bash
# Add to your ~/.bashrc or ~/.zshrc
alias stoei='uvx git+https://github.com/pjhartout/stoei.git'
```

### Using uv tool install (Permanent Installation)

Install `stoei` as a global tool that's available in your PATH:

```bash
uv tool install git+https://github.com/pjhartout/stoei.git
```

After installation, you can run `stoei` from anywhere:
```bash
stoei
```

**Install a specific version:**
```bash
uv tool install git+https://github.com/pjhartout/stoei.git@v0.2.3
```

**Update to the latest version:**
```bash
uv tool install --upgrade git+https://github.com/pjhartout/stoei.git
```

**Uninstall:**
```bash
uv tool uninstall stoei
```

**Where is it installed?**
- The `stoei` command is installed to `~/.local/bin/stoei` (or `$HOME/.local/bin/stoei`)
- Make sure `~/.local/bin` is in your `PATH` environment variable

### Using pip from GitHub

Install the latest release:

```bash
pip install git+https://github.com/pjhartout/stoei.git
```

Or install a specific version (see [releases](https://github.com/pjhartout/stoei/releases) for available versions):

```bash
pip install git+https://github.com/pjhartout/stoei.git@v0.2.3
```

### Using uv in a project

Add `stoei` as a dependency to your project:

```bash
uv add git+https://github.com/pjhartout/stoei.git
```

Then run it with:
```bash
uv run stoei
```

### From source

```bash
git clone https://github.com/pjhartout/stoei.git
cd stoei
uv sync
uv run stoei
```

## Usage

**If installed via `uv tool install` or `pip`:**
```bash
stoei
```

**If using `uvx` (no installation):**
```bash
uvx git+https://github.com/pjhartout/stoei.git
```

Or with an alias (if you set one up):
```bash
stoei
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit the application |
| `r` | Manually refresh data |
| `i` | Enter a job ID to view details |
| `Enter` | View details of selected job |
| `↑/↓` | Navigate between jobs |
| `Tab` | Switch between tables |
| `1` | Switch to Jobs tab |
| `2` | Switch to Nodes tab |
| `3` | Switch to Users tab |

## Requirements

- Python 3.11+
- Access to a SLURM cluster (with `squeue`, `sacct`, and `scontrol` commands available)
- For `uvx` installation method: [uv](https://github.com/astral-sh/uv) must be installed

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/pjhartout/stoei.git
cd stoei

# Install with dev dependencies
uv sync --all-extras

# Install pre-commit hooks
uv run pre-commit install
```

### Installing Development Binary

To install a development binary that automatically uses your local codebase (editable installation):

```bash
# From the project root directory
uv tool install -e . --force
```

This installs `stoei` as an editable package, so any changes you make to the code will be immediately reflected when you run `stoei` from anywhere. The `--force` flag overwrites any existing installation.

**Note**: When testing the app during development, always use `timeout 10 stoei` to prevent the agent from getting stuck, as `stoei` is an interactive TUI application.

### Running Tests

```bash
uv run pytest
```

### Running Tests with Coverage

```bash
uv run pytest --cov=stoei --cov-report=html
```

### Testing Without a SLURM Cluster

Mock SLURM executables are provided for testing without a real cluster:

```bash
# Run the app with mock data
./scripts/run_with_mocks.sh

# The mocks are also available as a pytest fixture
# Just use mock_slurm_path fixture in your tests
```

The mocks simulate:
- **squeue**: Returns 2-5 random running/pending jobs
- **sacct**: Returns 10 jobs with various states (COMPLETED, FAILED, TIMEOUT, etc.)
- **scontrol**: Returns detailed info for specific job IDs

### Linting

```bash
# Check formatting
uv run ruff format --check .

# Check linting
uv run ruff check .

# Auto-fix issues
uv run ruff check --fix .
uv run ruff format .
```

### Type Checking

```bash
uv run ty check stoei/
```

## Project Structure

```
stoei/
├── stoei/
│   ├── __init__.py
│   ├── __main__.py          # Entry point
│   ├── app.py                # Main Textual application
│   ├── editor.py             # External editor integration
│   ├── logging.py            # Loguru configuration
│   ├── slurm/
│   │   ├── commands.py       # SLURM command execution
│   │   ├── formatters.py     # Output formatting
│   │   ├── parser.py         # Output parsing
│   │   └── validation.py     # Input validation
│   ├── styles/
│   │   ├── app.tcss          # Main app styles
│   │   ├── modals.tcss       # Modal screen styles
│   │   └── theme.py          # Theme configuration
│   └── widgets/
│       ├── job_stats.py      # Statistics widget
│       ├── log_pane.py       # Log display widget
│       └── screens.py        # Modal screens
├── tests/
│   ├── conftest.py           # Shared fixtures
│   ├── test_slurm/           # SLURM module tests
│   └── test_widgets/         # Widget tests
├── pyproject.toml
└── README.md
```

## Logging

Logs are stored in `~/.stoei/logs/` and kept for 1 week. Each day gets a new log file which is compressed after rotation.

## Releases

New releases are created automatically when tags are pushed to the repository. You can install any release version by specifying the tag:

```bash
pip install git+https://github.com/pjhartout/stoei.git@v0.2.3
```

See all available releases on the [releases page](https://github.com/pjhartout/stoei/releases).

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please ensure:

1. All tests pass (`uv run pytest`)
2. Code is formatted (`uv run ruff format .`)
3. No linting errors (`uv run ruff check .`)
4. Type hints are correct (`uv run ty check stoei/`)

> **What's in a name?** *Stoei* is a Dutch verb meaning "wrestle" — because managing SLURM jobs can feel like a struggle! It's also an alternative spelling for **S**lurm**TUI**.
