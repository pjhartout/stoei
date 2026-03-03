---
status: complete
priority: p2
issue_id: "005"
tags: [code-review, testing, quality]
dependencies: []
---

# 005 · No unit tests for new progressive-rendering methods

## Problem Statement

PR #52 introduced seven new methods and significantly rewrote three others, but no new unit tests
were added beyond updating a single assertion count.  The six branches of `_apply_fetch_result`,
the five targeted UI update helpers, and `_on_refresh_complete` are all untested at the unit level.

## Findings

- `tests/unit/test_app.py` — only `TestRefreshDataAsync::test_refresh_data_calls_multiple_call_from_thread` was updated (assertion `>= 6`)
- New methods with no test coverage:
  - `_apply_fetch_result` (6 branches: `user_jobs`, `nodes`, `all_jobs`, `wait_time`, `priority`, `energy`)
  - `_update_nodes_and_sidebar`
  - `_update_all_jobs_widgets`
  - `_update_priority_tab`
  - `_update_energy_tab`
  - `_on_refresh_complete`
- All review agents flagged the test gap.

## Proposed Solutions

### Option A — Unit tests per `_apply_fetch_result` branch (Recommended, Medium effort)

Add a `TestApplyFetchResult` class in `tests/unit/test_app.py` that:
1. Creates a minimal `StoeiApp` instance using `app.run_test()` (or mocks).
2. Calls `_apply_fetch_result(label, mock_result)` for each of the 6 labels.
3. Asserts that the correct `call_from_thread` callback was posted and the correct state was updated.

For `_on_refresh_complete`:
- Test first-cycle path: asserts `_initial_background_complete` is set, timer is started, `notify` called.
- Test subsequent-cycle path: asserts only `logger.debug` is called.

Pros: targeted; fast; covers most regression risk.
Cons: requires careful mocking of `call_from_thread` and query_one.
Effort: Medium | Risk: Low

### Option B — Integration-style smoke test (Small effort)

Add an integration test that runs a full refresh cycle with mocked SLURM commands and asserts:
- The jobs table is populated after the first `call_from_thread` callback fires.
- The cluster sidebar shows non-zero stats before the priority tab receives data.

Pros: tests end-to-end progressive rendering behaviour.
Cons: slower; harder to pin down exactly which method failed.
Effort: Small-Medium | Risk: Low

## Recommended Action

_To be filled during triage._

## Technical Details

- **Affected files**: `tests/unit/test_app.py`
- **New methods to cover**: `_apply_fetch_result` (×6 branches), `_update_nodes_and_sidebar`, `_update_all_jobs_widgets`, `_update_priority_tab`, `_update_energy_tab`, `_on_refresh_complete`

## Acceptance Criteria

- [ ] `TestApplyFetchResult` class exists with at least one test per label
- [ ] `_on_refresh_complete` tested for both first-cycle and subsequent-cycle paths
- [ ] Test suite runs in ≤ 20 seconds (project requirement)
- [ ] `uv run pytest` passes

## Work Log

- 2026-03-02 — Identified by code review of PR #52

## Resources

- PR #52: feat/progressive-rendering
- Existing test patterns: `tests/unit/test_app.py::TestRefreshDataAsync`
