# Project description

I want to build an app that enables its users to understand their slurm jobs in a TUI. 

## Start page

# Tech stack

- I want to use rich/Textual to build the TUI. 
- I want to use `uv` for package management. Use the web to look for the latest uv interface. You will need to use `uv run` for executing each command in the environment.
- I want to use `ruff` for linting. Be strict with linting unless absolutely necessary.
- Use `ty` for type hints. Be as specific as possible, avoid Any and similarly nebulous types unless absolutely necessary.
- In the end I want to use uvx to have the command to start the app anywhere.

## Maintainability

I want a codebase that is easily maintainable. I want minimal coupling. If a pattern is particularly applicable in this project, apply it, otherwise focus on the functionality over the purity of how those patterns are applied.


## Testing

I want a full `pytest`-based test suite. I want to make extensive use of fixtures, instead of setup and teardowns.

I want to run this test suite on each push and opened PR on github workflows. I also want to have precommit hook to check for uv formatting and ty respecting the project rules.

**Important**: Do NOT run interactive commands like `stoei` itself during development/testing as it is a TUI application that requires user interaction. If you must run it for verification, always use `timeout` to interrupt it after 10 seconds (e.g., `timeout 10 stoei`). Prefer using the pytest test suite for verification instead.

**Performance**: The test suite must execute in under 20 seconds. To achieve this:
- Mock `_start_refresh_worker` and `check_slurm_available` in tests using `app.run_test()`
- Use `size=(80, 24)` for Textual app tests to reduce rendering overhead
- Avoid `await pilot.pause()` unless absolutely necessary
- Do not add `pytest-timeout` as a band-aid - fix slow tests at the root cause

## Logging

Use loguru for logging, I want to use the logs for 1 week. I want the logs to be in a logs/ folders. I want the logs in the standard output and a file. Use f-strings for all log messages (e.g., `logger.info(f"Loaded {count} items")`) instead of loguru's deferred `{}` formatting or `%` style formatting.

## Docstrings

I want to use google-style docstrings.

## Documentation

I want to have mostly self-explanatory code. Use the Readme to show the user how to get started.

## Code structure

I want to have a clear code structure. In the end, I want the main source code for the package repository

## Code style

- **All imports must be hoisted to the top of the file** - no imports inside functions, methods, or conditional blocks. This is enforced by ruff rule PLC0415.

## Agent Auto-run Commands

**CRITICAL: You MUST automatically run these commands after making ANY code changes:**

1. **After editing Python files, ALWAYS run:**
   ```bash
   uv run ruff format .
   uv run ruff check --fix .
   uv run ty check stoei/
   ```

2. **After making significant changes, ALSO run:**
   ```bash
   uv run pytest
   ```

3. **Before completing any task, verify with:**
   ```bash
   uv run ruff format --check .
   uv run ruff check .
   uv run ty check stoei/
   ```

**Do NOT ask the user - just run these commands automatically after code changes.**
