---
title: "Intuitive Priority Interface"
type: enhancement
date: 2026-02-25
---

# Intuitive Priority Interface

## Overview

Redesign the Priority tab to make it immediately obvious where the current user stands in scheduling priority, how other users compare, and how their account (institute) is consuming its allocated resources. The current Priority tab shows raw sshare/sprio numbers in three flat tables with no visual differentiation, no current-user highlighting, and no relative context.

## Problem Statement

The current Priority tab (`stoei/widgets/priority_overview.py`) has three sub-tabs -- Users, Accounts, Jobs -- that display raw SLURM data as plain text tables. Users must:

1. **Visually scan** a potentially large list to find their own username (no highlighting)
2. **Interpret raw numbers** like `FairShare: 0.450000` with no context for what that means relative to peers
3. **Switch between sub-tabs** to cross-reference their user priority with their account priority
4. **Understand SLURM internals** (FairShare, EffectvUsage, NormShares) without any guidance

The result is a data dump, not a usable interface for answering the questions users actually have: "Will my job run soon?" and "Is my group using its fair share?"

## Proposed Solution

Restructure the Priority tab into four sub-tabs with a focus-first-then-explore information hierarchy:

| Sub-tab | Key | Purpose |
|---------|-----|---------|
| **My Priority** | `m` | Current user's priority summary + their pending jobs |
| **All Users** | `u` | All users ranked by FairShare with current user highlighted |
| **Accounts** | `a` | Account/institute usage comparison with user's account highlighted |
| **Jobs** | `j` | All pending jobs priority factors (existing, enhanced) |

### Key Enhancements

1. **Current user row highlighting** -- bold + accent color markup on the user's row in all tables
2. **Rank column** -- "3/42" showing position in the sorted list (pre-computed, stable across re-sorts)
3. **FairShare color-coding** -- green (>= 0.5, under-served), yellow (>= 0.2, fair), red (< 0.2, over-served) using existing `_FAIR_SHARE_SUCCESS_THRESHOLD` / `_FAIR_SHARE_WARNING_THRESHOLD` from `stoei/slurm/formatters.py:471-472`
4. **Status column** -- human-readable label: "Under-served" / "Fair" / "Over-served"
5. **"My Priority" summary sub-tab** -- composite view showing the user's rank, FairShare, account context, and their pending jobs in one place

## Technical Approach

### Phase 1: Color-Coding and User Highlighting

Enhance existing tables without structural changes. Low risk, high value.

**Files to modify:**

- `stoei/widgets/priority_overview.py` -- Add `current_username` parameter, apply Rich markup to FairShare cells and current user rows
- `stoei/app.py` -- Pass `self._current_username` when building priority cache and calling update methods

**Changes to `priority_overview.py`:**

```python
# Add current_username to __init__
def __init__(self, *, current_username: str = "", ...):
    self._current_username = current_username

# Add Status column to USER_PRIORITY_COLUMNS
ColumnConfig(name="Status", key="status", sortable=True, filterable=True, width=12)

# Color-code FairShare and highlight current user row in update_user_priorities()
def update_user_priorities(self, priorities: list[UserPriority]) -> None:
    colors = get_theme_colors(self.app)
    for p in sorted_priorities:
        is_me = p.username == self._current_username
        fs_color = _fair_share_color(p.fair_share, colors)
        status = _fair_share_status(p.fair_share)
        if is_me:
            style = f"bold {colors.accent}"
            row = (f"[{style}]>> {p.username}[/{style}]", ...)
        else:
            row = (p.username, ..., f"[{fs_color}]{p.fair_share}[/{fs_color}]", status)
```

**Changes to `app.py`:**

```python
# Pass current_username when creating PriorityOverviewTab
PriorityOverviewTab(current_username=self._current_username, id="priority-overview")

# Pass current_username in cache computation
def _compute_priority_overview_cache(self):
    # Add rank computation (position in FairShare-sorted list)
    for i, p in enumerate(sorted_user_priorities, 1):
        p.rank = f"{i}/{len(sorted_user_priorities)}"
```

### Phase 2: Rank Column

Add a pre-computed rank column to Users and Accounts tables.

**Files to modify:**

- `stoei/widgets/priority_overview.py` -- Add `Rank` column config, add `rank` field to `UserPriority` and `AccountPriority` dataclasses
- `stoei/app.py` -- Compute ranks in `_compute_priority_overview_cache()`

**Rank computation:**

```python
# Dense ranking (ties share the same rank)
def _compute_ranks(values: list[float]) -> list[str]:
    total = len(values)
    ranks: list[str] = []
    prev_val = None
    rank = 0
    for val in values:  # already sorted descending
        if val != prev_val:
            rank += 1
        ranks.append(f"{rank}/{total}")
        prev_val = val
    return ranks
```

**Column additions:**

```python
USER_PRIORITY_COLUMNS = [
    ColumnConfig(name="Rank", key="rank", sortable=False, filterable=False, width=8),
    ColumnConfig(name="User", ...),
    # ... existing columns ...
    ColumnConfig(name="Status", key="status", sortable=True, filterable=True, width=12),
]
```

### Phase 3: "My Priority" Sub-tab

Add a new default sub-tab showing the current user's priority summary.

**Files to modify:**

- `stoei/widgets/priority_overview.py` -- Add new sub-tab container, new `PrioritySubtabName` literal, compose changes
- `stoei/styles/app.tcss` -- Styling for summary panel (if needed)

**"My Priority" sub-tab content (composite Static + FilterableDataTable):**

```
┌─ Your Priority ──────────────────────────────────────────────┐
│  FairShare: 0.650000   Status: Under-served   Rank: 5/42    │
│  Account: physics      Account Rank: 2/8                     │
│  Shares: 50 (12.5% of cluster)                               │
└──────────────────────────────────────────────────────────────┘

Your Pending Jobs (3)
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────┐
│ JobID    │ Priority │ Age      │ FairShare│ Partition│ QOS  │
├──────────┼──────────┼──────────┼──────────┼──────────┼──────┤
│ 47441    │ 1500     │ 100      │ 800      │ 300      │ 100  │
│ 47434    │ 1400     │ 80       │ 750      │ 270      │ 100  │
│ 47420    │ 1200     │ 50       │ 700      │ 250      │ 100  │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────┘
```

**Implementation approach:**

- Top section: `Static` widget with Rich Panel showing summary, updated via `update()` on each refresh
- Bottom section: `FilterableDataTable` filtered to only the current user's pending jobs from sprio
- If user not found in sshare data: show `[dim]No fair-share data found for 'username'. This may occur if you have not submitted jobs recently.[/dim]`

**Sub-tab layout after Phase 3:**

```python
PrioritySubtabName = Literal["mine", "users", "accounts", "jobs"]

BINDINGS = [
    Binding("m", "switch_subtab_mine", "My Priority", show=False),
    Binding("u", "switch_subtab_users", "All Users", show=False),
    Binding("a", "switch_subtab_accounts", "Accounts", show=False),
    Binding("j", "switch_subtab_jobs", "Jobs", show=False),
]
```

Default active sub-tab changes from `"users"` to `"mine"`.

### Phase 4 (Optional): Weight Info and Account Hierarchy

Lower priority enhancements that can be done in a follow-up.

- **`sprio -w` weights**: Fetch once on initial load, display as dim header text on the Jobs sub-tab (e.g., `[dim]Weights: Age=1000 FairShare=10000 JobSize=0 Partition=5000 QOS=5000[/dim]`)
- **Account parent column**: Add `Parent` column to Accounts table by fetching account hierarchy from `sacctmgr show account format=Account,ParentName -P --noheader` (one-time fetch)

## Acceptance Criteria

### Functional Requirements

- [ ] Priority tab default sub-tab is "My Priority" showing current user's summary
- [ ] Current user's row is highlighted (bold + accent color) in All Users and Jobs tables
- [ ] FairShare values are color-coded: green (>= 0.5), yellow (>= 0.2), red (< 0.2)
- [ ] "Status" column shows human-readable label in Users and Accounts tables
- [ ] "Rank" column shows dense-ranked position (e.g., "3/42") in Users and Accounts tables
- [ ] Rank values are stable (pre-computed by FairShare sort order, not affected by user's current sort)
- [ ] "My Priority" sub-tab shows user's FairShare, status, rank, account info, and pending jobs
- [ ] "My Priority" shows graceful empty state when user is not in sshare data
- [ ] Sub-tab keybindings: `m` (My Priority), `u` (All Users), `a` (Accounts), `j` (Jobs)
- [ ] Current user's account row is highlighted in Accounts table
- [ ] All existing Enter/click-to-detail interactions still work (UserInfoScreen, AccountInfoScreen)

### Non-Functional Requirements

- [ ] No new SLURM commands in Phase 1-3 (reuses existing sshare + sprio data)
- [ ] Test suite passes and stays under 20 seconds
- [ ] Rank computation happens in background worker thread (in `_compute_priority_overview_cache`)
- [ ] Color-coding uses existing `ThemeColors` infrastructure from `stoei/colors.py`
- [ ] FairShare thresholds use existing constants from `stoei/slurm/formatters.py`

## Dependencies

- Uses existing `get_fair_share_priority()` and `get_pending_job_priority()` commands -- no new SLURM calls needed for Phases 1-3
- Uses existing `_FAIR_SHARE_SUCCESS_THRESHOLD` (0.5) and `_FAIR_SHARE_WARNING_THRESHOLD` (0.2) from `stoei/slurm/formatters.py:471-472`
- Uses existing `ThemeColors.pct_color()` pattern from `stoei/colors.py`
- Uses existing `self._current_username` from `stoei/app.py:183`
- Uses existing `FilterableDataTable` for all table views
- Phase 4 would require new `sacctmgr` and `sprio -w` commands

## Files to Create/Modify

| File | Action | Phase | Description |
|------|--------|-------|-------------|
| `stoei/widgets/priority_overview.py` | Modify | 1-3 | Add current_username, color-coding, rank, Status column, "My Priority" sub-tab |
| `stoei/app.py` | Modify | 1-3 | Pass current_username to widget, compute ranks in cache, update sub-tab handling |
| `stoei/slurm/formatters.py` | Modify | 1 | Extract `_fair_share_color()` and `_fair_share_status()` as reusable functions |
| `tests/unit/widgets/test_priority_overview.py` | Modify | 1-3 | Update for new columns, sub-tab names, highlighting, rank |
| `tests/unit/slurm/test_priority.py` | Modify | 2 | Test rank computation |
| `tests/mocks/sprio` | No change | - | Existing mock data is sufficient |
| `tests/mocks/sshare` | No change | - | Existing mock data is sufficient |

## Design Decisions

**Why not a separate dashboard screen?** The Priority tab already exists with sub-tabs. Adding "My Priority" as the default sub-tab keeps navigation consistent (still tab 4) and avoids a new screen that users must discover.

**Why dense ranking for ties?** If two users have the same FairShare, they should show the same rank. Dense ranking (1, 2, 2, 3) is more intuitive than competition ranking (1, 2, 2, 4) for "where do I stand?" questions.

**Why keep the Jobs sub-tab?** The "My Priority" sub-tab will show only the current user's pending jobs. The Jobs sub-tab shows ALL pending jobs across all users, which sysadmins need for fairshare validation.

**Why use existing FairShare thresholds (0.5/0.2) instead of the 1.0 boundary?** The sshare FairShare value is already normalized to [0.0, 1.0] on most SLURM clusters. The existing thresholds in `formatters.py` are already validated in the UserInfoScreen and AccountInfoScreen, so reusing them ensures consistency.

## References

- Current widget: `stoei/widgets/priority_overview.py`
- FairShare thresholds: `stoei/slurm/formatters.py:471-472`
- App priority orchestration: `stoei/app.py:817` (`_fetch_priority`), `stoei/app.py:1568` (`_compute_priority_overview_cache`)
- Current username: `stoei/app.py:183` (`self._current_username`)
- Theme colors: `stoei/colors.py` (`ThemeColors`, `get_theme_colors`, `pct_color`)
- SLURM sshare docs: https://slurm.schedmd.com/sshare.html
- SLURM sprio docs: https://slurm.schedmd.com/sprio.html
- SLURM Fair Tree algorithm: https://slurm.schedmd.com/fair_tree.html
