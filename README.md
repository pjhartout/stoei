# Stoei

A Slurm TUI (Terminal User Interface) for monitoring SLURM jobs. Keep track of your HPC cluster jobs with an intuitive, auto-refreshing interface.

[![GitHub release](https://img.shields.io/github/v/tag/pjhartout/stoei?label=version)](https://github.com/pjhartout/stoei/releases)
[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/pjhartout/stoei)](https://github.com/pjhartout/stoei/blob/main/LICENSE)

## Features

- 🏃 **Real-time monitoring** - Auto-refreshes every 2 seconds
- 📊 **Job statistics** - View total jobs, requeues, and running/pending counts at a glance
- 📜 **Job history** - See your job history from the last 24 hours
- 🔍 **Detailed job info** - Press Enter or 'i' to view comprehensive job details
- 🎨 **Terminal-native colors** - Inherits your terminal's color scheme (works with Nord, Dracula, etc.)

## Installation

### Using uvx (Recommended)

```bash
uvx stoei
```

### Using pip

```bash
pip install stoei
```

### From source

```bash
git clone https://github.com/pjhartout/stoei.git
cd stoei
uv sync
uv run stoei
```

## Usage

Simply run:

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

## Requirements

- Python 3.11+
- Access to a SLURM cluster (with `squeue`, `sacct`, and `scontrol` commands available)

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
│   ├── logging.py            # Loguru configuration
│   ├── slurm/
│   │   ├── commands.py       # SLURM command execution
│   │   ├── formatters.py     # Output formatting
│   │   ├── parser.py         # Output parsing
│   │   └── validation.py     # Input validation
│   ├── styles/
│   │   └── theme.py          # CSS styling
│   └── widgets/
│       ├── job_stats.py      # Statistics widget
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

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please ensure:

1. All tests pass (`uv run pytest`)
2. Code is formatted (`uv run ruff format .`)
3. No linting errors (`uv run ruff check .`)
4. Type hints are correct (`uv run ty check stoei/`)

> **What's in a name?** *Stoei* is a Dutch verb meaning "wrestle" — because managing SLURM jobs can feel like a struggle! It's also an alternative spelling for **S**lurm**TUI**.
