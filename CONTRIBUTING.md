# Contributing to Stoei

Thank you for your interest in contributing to Stoei! This document provides guidelines and instructions for contributing to the project.

## Development Setup

### Prerequisites

- Python 3.11 or higher
- [uv](https://github.com/astral-sh/uv) for package management
- Access to a SLURM cluster (for integration testing)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/pjhartout/stoei.git
   cd stoei
   ```

2. Install dependencies with uv:
   ```bash
   uv sync
   ```

3. Install pre-commit hooks:
   ```bash
   uv run pre-commit install
   ```

### Running the Application

```bash
uv run stoei
```

For development with mock SLURM commands:
```bash
./scripts/run_with_mocks.sh
```

## Code Style

### Formatting and Linting

We use [Ruff](https://docs.astral.sh/ruff/) for both formatting and linting:

```bash
# Format code
uv run ruff format .

# Check for linting issues
uv run ruff check .

# Fix auto-fixable issues
uv run ruff check --fix .
```

### Type Checking

We use [ty](https://github.com/astral-sh/ty) for type checking:

```bash
uv run ty check stoei/
```

### Docstrings

Use Google-style docstrings for all public functions, methods, and classes:

```python
def function_name(arg1: str, arg2: int) -> bool:
    """Short description of the function.

    Longer description if needed.

    Args:
        arg1: Description of arg1.
        arg2: Description of arg2.

    Returns:
        Description of return value.

    Raises:
        ValueError: When something is wrong.
    """
    pass
```

### Import Style

All imports must be at the top of the file (enforced by Ruff rule PLC0415). No imports inside functions or conditional blocks.

## Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_slurm/test_commands.py

# Run specific test class
uv run pytest tests/test_slurm/test_commands.py::TestGetJobInfo
```

### Test Guidelines

1. **Use fixtures** instead of setup/teardown methods
2. **Mock SLURM commands** - Tests use mock executables in `tests/mocks/`
3. **Keep tests fast** - The test suite should complete in under 20 seconds
4. **Use `size=(80, 24)`** for Textual app tests to reduce rendering overhead

### Writing Tests

- Place tests in the appropriate directory under `tests/`
- Name test files with `test_` prefix
- Name test classes with `Test` prefix
- Name test methods with `test_` prefix

Example:
```python
class TestFeatureName:
    """Tests for FeatureName."""

    def test_basic_functionality(self) -> None:
        """Test that basic case works."""
        result = my_function("input")
        assert result == "expected"

    def test_edge_case(self) -> None:
        """Test edge case handling."""
        with pytest.raises(ValueError):
            my_function(None)
```

## Pull Request Process

1. **Fork the repository** and create a feature branch
2. **Make your changes** following the code style guidelines
3. **Add tests** for new functionality
4. **Run the full test suite** to ensure nothing is broken:
   ```bash
   uv run ruff format --check .
   uv run ruff check .
   uv run ty check stoei/
   uv run pytest
   ```
5. **Submit a pull request** with a clear description of your changes

### PR Title Convention

Use clear, descriptive titles:
- `Add: feature description` for new features
- `Fix: bug description` for bug fixes
- `Update: what was updated` for improvements
- `Refactor: what was refactored` for code restructuring
- `Docs: what was documented` for documentation changes

## Project Structure

```
stoei/
├── stoei/                  # Main package
│   ├── __init__.py
│   ├── __main__.py        # Entry point
│   ├── app.py             # Main Textual application
│   ├── editor.py          # External editor integration
│   ├── logger.py          # Logging configuration
│   ├── slurm/             # SLURM interaction module
│   │   ├── cache.py       # Job caching
│   │   ├── commands.py    # SLURM command execution
│   │   ├── formatters.py  # Output formatting
│   │   ├── gpu_parser.py  # GPU information parsing
│   │   ├── parser.py      # Output parsing
│   │   └── validation.py  # Input validation
│   ├── styles/            # Textual CSS styles
│   │   ├── app.tcss
│   │   └── modals.tcss
│   └── widgets/           # Textual widgets
│       ├── cluster_sidebar.py
│       ├── help_screen.py
│       ├── job_stats.py
│       ├── log_pane.py
│       ├── node_overview.py
│       ├── screens.py
│       ├── slurm_error_screen.py
│       ├── tabs.py
│       └── user_overview.py
├── tests/                 # Test suite
│   ├── mocks/            # Mock SLURM executables
│   └── test_*/           # Test modules
├── scripts/              # Development scripts
├── pyproject.toml        # Project configuration
└── README.md             # User documentation
```

## Adding New Features

### Adding a New Widget

1. Create a new file in `stoei/widgets/`
2. Follow the existing widget patterns
3. Add CSS styles in `stoei/styles/`
4. Add tests in `tests/test_widgets/`
5. Integrate into the main app

### Adding SLURM Commands

1. Add the command function in `stoei/slurm/commands.py`
2. Add parsers in `stoei/slurm/parser.py` if needed
3. Add formatters in `stoei/slurm/formatters.py` if needed
4. Add mock output in `tests/mocks/` for testing
5. Add tests in `tests/test_slurm/`

## Questions?

If you have questions or need help, please open an issue on GitHub.
