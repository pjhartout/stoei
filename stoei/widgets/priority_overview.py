"""Priority overview tab widget with sub-tabs for user, account, and job priority views."""

from dataclasses import dataclass, field
from typing import ClassVar, Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from stoei.colors import ThemeColors, get_theme_colors
from stoei.logger import get_logger
from stoei.settings import load_settings
from stoei.slurm.formatters import fair_share_color, fair_share_status
from stoei.slurm.parser import parse_sprio_output, parse_sshare_output
from stoei.widgets.filterable_table import ColumnConfig, FilterableDataTable

logger = get_logger(__name__)


def compute_dense_ranks(values: list[float]) -> list[str]:
    """Compute dense ranks for a descending-sorted list of values.

    Tied values share the same rank (e.g., 1, 2, 2, 3).

    Args:
        values: List of float values, already sorted descending.

    Returns:
        List of rank strings like "1/42", "2/42", etc.
    """
    total = len(values)
    if total == 0:
        return []
    ranks: list[str] = []
    prev_val: float | None = None
    rank = 0
    for val in values:
        if val != prev_val:
            rank += 1
        ranks.append(f"{rank}/{total}")
        prev_val = val
    return ranks


@dataclass
class UserPriority:
    """User-level priority statistics from sshare."""

    username: str
    account: str
    raw_shares: str
    norm_shares: str
    raw_usage: str
    norm_usage: str
    effective_usage: str
    fair_share: str
    rank: str = field(default="")


@dataclass
class AccountPriority:
    """Account/institute-level priority statistics from sshare."""

    account: str
    raw_shares: str
    norm_shares: str
    raw_usage: str
    norm_usage: str
    effective_usage: str
    fair_share: str
    rank: str = field(default="")


@dataclass
class JobPriority:
    """Pending job priority factors from sprio."""

    job_id: str
    user: str
    account: str
    priority: str
    age: str
    fair_share: str
    job_size: str
    partition: str
    qos: str


class PrioritySubtabSwitched(Message):
    """Message sent when a sub-tab within the priority overview is switched."""

    def __init__(self, subtab_name: str) -> None:
        """Initialize the PrioritySubtabSwitched message.

        Args:
            subtab_name: Name of the sub-tab that was switched to.
        """
        super().__init__()
        self.subtab_name = subtab_name


# Type alias for subtab names
PrioritySubtabName = Literal["mine", "users", "accounts", "jobs"]

# Container IDs for each sub-tab
_SUBTAB_CONTAINER_IDS: list[str] = [
    "priority-subtab-mine",
    "priority-subtab-users",
    "priority-subtab-accounts",
    "priority-subtab-jobs",
]


def _style_cell(value: str, style: str) -> str:
    """Wrap a cell value in Rich markup style.

    Args:
        value: The cell text.
        style: The Rich style string (e.g., "bold #a3be8c").

    Returns:
        Styled Rich markup string.
    """
    return f"[{style}]{value}[/{style}]"


def _format_fs_cell(fair_share: str, colors: ThemeColors) -> str:
    """Format a FairShare cell with color coding.

    Args:
        fair_share: FairShare value as string.
        colors: Theme colors.

    Returns:
        Rich markup string with appropriate color.
    """
    color = fair_share_color(fair_share, colors)
    return f"[bold {color}]{fair_share}[/bold {color}]"


def _format_status_cell(fair_share: str, colors: ThemeColors) -> str:
    """Format a Status cell with color coding.

    Args:
        fair_share: FairShare value as string.
        colors: Theme colors.

    Returns:
        Rich markup string with status label and color.
    """
    status = fair_share_status(fair_share)
    if not status:
        return ""
    color = fair_share_color(fair_share, colors)
    return f"[{color}]{status}[/{color}]"


def _build_my_priority_summary(
    current_username: str,
    user_priorities: list[UserPriority],
    account_priorities: list[AccountPriority],
    job_priorities: list[JobPriority],
    colors: ThemeColors,
) -> str:
    """Build the Rich markup for the 'My Priority' summary panel.

    Args:
        current_username: The current user's username.
        user_priorities: Sorted user priority list.
        account_priorities: Sorted account priority list.
        job_priorities: All pending job priorities.
        colors: Theme colors.

    Returns:
        Rich markup string for the summary Static widget.
    """
    my_priority = next((p for p in user_priorities if p.username == current_username), None)
    if my_priority is None:
        return (
            f"[{colors.text_muted}]No fair-share data found for '{current_username}'. "
            f"This may occur if you have not submitted jobs recently "
            f"or if fair-share is not configured on this cluster.[/{colors.text_muted}]"
        )

    # User's FairShare with color
    fs_color = fair_share_color(my_priority.fair_share, colors)
    status = fair_share_status(my_priority.fair_share)
    rank = my_priority.rank or "?"

    # Find account info
    my_account_priority = next((a for a in account_priorities if a.account == my_priority.account), None)
    account_rank = my_account_priority.rank if my_account_priority else "?"

    # Count my pending jobs
    my_jobs = [j for j in job_priorities if j.user == current_username]
    pending_count = len(my_jobs)

    lines = [
        "[bold]Your Priority[/bold]",
        "",
        f"  FairShare: [bold {fs_color}]{my_priority.fair_share}[/bold {fs_color}]"
        f"   Status: [{fs_color}]{status}[/{fs_color}]"
        f"   Rank: [bold]{rank}[/bold]",
        f"  Account: [bold]{my_priority.account}[/bold]   Account Rank: [bold]{account_rank}[/bold]",
        f"  Shares: {my_priority.raw_shares} ({my_priority.norm_shares} of cluster)",
        "",
        f"  Pending Jobs: [bold]{pending_count}[/bold]",
    ]
    return "\n".join(lines)


class PriorityOverviewTab(VerticalScroll):
    """Tab widget displaying priority overview with sub-tabs."""

    DEFAULT_CSS: ClassVar[str] = """
    PriorityOverviewTab {
        height: 100%;
        width: 100%;
    }

    #priority-subtab-header {
        height: 1;
        width: 100%;
        margin-bottom: 1;
    }

    .priority-subtab-content {
        height: 1fr;
        width: 100%;
    }

    .priority-subtab-hidden {
        display: none;
    }

    #priority-info-text {
        margin-bottom: 1;
        color: $text-muted;
    }

    #my-priority-summary {
        margin-bottom: 1;
    }

    #my-priority-jobs-header {
        margin-bottom: 0;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("m", "switch_subtab_mine", "My Priority", show=False),
        Binding("u", "switch_subtab_users", "All Users", show=False),
        Binding("a", "switch_subtab_accounts", "Accounts", show=False),
        Binding("j", "switch_subtab_jobs", "Jobs", show=False),
    ]

    # Column configs for each priority table
    USER_PRIORITY_COLUMNS: ClassVar[list[ColumnConfig]] = [
        ColumnConfig(name="Rank", key="rank", sortable=False, filterable=False, width=8),
        ColumnConfig(name="User", key="user", sortable=True, filterable=True, width=15),
        ColumnConfig(name="Account", key="account", sortable=True, filterable=True, width=15),
        ColumnConfig(name="RawShares", key="raw_shares", sortable=True, filterable=True, width=12),
        ColumnConfig(name="NormShares", key="norm_shares", sortable=True, filterable=True, width=12),
        ColumnConfig(name="RawUsage", key="raw_usage", sortable=True, filterable=True, width=12),
        ColumnConfig(name="EffectvUsage", key="effective_usage", sortable=True, filterable=True, width=12),
        ColumnConfig(name="FairShare", key="fair_share", sortable=True, filterable=True, width=10),
        ColumnConfig(name="Status", key="status", sortable=True, filterable=True, width=12),
    ]

    ACCOUNT_PRIORITY_COLUMNS: ClassVar[list[ColumnConfig]] = [
        ColumnConfig(name="Rank", key="rank", sortable=False, filterable=False, width=8),
        ColumnConfig(name="Account", key="account", sortable=True, filterable=True, width=20),
        ColumnConfig(name="RawShares", key="raw_shares", sortable=True, filterable=True, width=12),
        ColumnConfig(name="NormShares", key="norm_shares", sortable=True, filterable=True, width=12),
        ColumnConfig(name="RawUsage", key="raw_usage", sortable=True, filterable=True, width=14),
        ColumnConfig(name="EffectvUsage", key="effective_usage", sortable=True, filterable=True, width=12),
        ColumnConfig(name="FairShare", key="fair_share", sortable=True, filterable=True, width=10),
        ColumnConfig(name="Status", key="status", sortable=True, filterable=True, width=12),
    ]

    MY_JOB_PRIORITY_COLUMNS: ClassVar[list[ColumnConfig]] = [
        ColumnConfig(name="JobID", key="job_id", sortable=True, filterable=True, width=12),
        ColumnConfig(name="Priority", key="priority", sortable=True, filterable=True, width=10),
        ColumnConfig(name="Age", key="age", sortable=True, filterable=True, width=10),
        ColumnConfig(name="FairShare", key="fair_share", sortable=True, filterable=True, width=10),
        ColumnConfig(name="JobSize", key="job_size", sortable=True, filterable=True, width=10),
        ColumnConfig(name="Partition", key="partition", sortable=True, filterable=True, width=10),
        ColumnConfig(name="QOS", key="qos", sortable=True, filterable=True, width=10),
    ]

    JOB_PRIORITY_COLUMNS: ClassVar[list[ColumnConfig]] = [
        ColumnConfig(name="JobID", key="job_id", sortable=True, filterable=True, width=12),
        ColumnConfig(name="User", key="user", sortable=True, filterable=True, width=12),
        ColumnConfig(name="Account", key="account", sortable=True, filterable=True, width=12),
        ColumnConfig(name="Priority", key="priority", sortable=True, filterable=True, width=10),
        ColumnConfig(name="Age", key="age", sortable=True, filterable=True, width=10),
        ColumnConfig(name="FairShare", key="fair_share", sortable=True, filterable=True, width=10),
        ColumnConfig(name="JobSize", key="job_size", sortable=True, filterable=True, width=10),
        ColumnConfig(name="Partition", key="partition", sortable=True, filterable=True, width=10),
        ColumnConfig(name="QOS", key="qos", sortable=True, filterable=True, width=10),
    ]

    def __init__(
        self,
        *,
        current_username: str = "",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        """Initialize the PriorityOverviewTab widget.

        Args:
            current_username: The current user's username for highlighting.
            name: The name of the widget.
            id: The ID of the widget in the DOM.
            classes: The CSS classes for the widget.
            disabled: Whether the widget is disabled.
        """
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self._current_username = current_username
        self.user_priorities: list[UserPriority] = []
        self.account_priorities: list[AccountPriority] = []
        self.job_priorities: list[JobPriority] = []
        self._active_subtab: PrioritySubtabName = "mine"
        self._settings = load_settings()

    def compose(self) -> ComposeResult:
        """Create the priority overview layout with sub-tabs."""
        # Sub-tab header with keyboard shortcuts
        with Horizontal(id="priority-subtab-header"):
            yield Static(
                "[bold]Priority[/bold]  "
                "[bold reverse] m [/bold reverse]My Priority  "
                "[dim]u[/dim] All Users  "
                "[dim]a[/dim] Accounts  "
                "[dim]j[/dim] Jobs",
                id="priority-subtab-header-text",
            )

        # My Priority sub-tab (default visible)
        with Container(id="priority-subtab-mine", classes="priority-subtab-content"):
            yield Static(
                "[dim]Loading priority data...[/dim]",
                id="my-priority-summary",
            )
            yield Static(
                "[bold]Your Pending Jobs[/bold]",
                id="my-priority-jobs-header",
            )
            yield FilterableDataTable(
                columns=self.MY_JOB_PRIORITY_COLUMNS,
                keybind_mode=self._settings.keybind_mode,
                table_id="my_job_priority_table",
                id="my-job-priority-filterable-table",
            )

        # All Users priority sub-tab (hidden by default)
        with Container(id="priority-subtab-users", classes="priority-subtab-content priority-subtab-hidden"):
            yield Static(
                "[dim]Fair-share priority per user (higher FairShare = higher scheduling priority)[/dim]",
                id="priority-info-text",
            )
            yield FilterableDataTable(
                columns=self.USER_PRIORITY_COLUMNS,
                keybind_mode=self._settings.keybind_mode,
                table_id="user_priority_table",
                id="user-priority-filterable-table",
            )

        # Accounts priority sub-tab (hidden by default)
        with Container(id="priority-subtab-accounts", classes="priority-subtab-content priority-subtab-hidden"):
            yield Static(
                "[dim]Fair-share priority per account/institute (higher FairShare = higher scheduling priority)[/dim]",
                id="account-priority-info-text",
            )
            yield FilterableDataTable(
                columns=self.ACCOUNT_PRIORITY_COLUMNS,
                keybind_mode=self._settings.keybind_mode,
                table_id="account_priority_table",
                id="account-priority-filterable-table",
            )

        # Jobs priority sub-tab (hidden by default)
        with Container(id="priority-subtab-jobs", classes="priority-subtab-content priority-subtab-hidden"):
            yield Static(
                "[dim]Priority factors for pending jobs (higher values = higher scheduling priority)[/dim]",
                id="job-priority-info-text",
            )
            yield FilterableDataTable(
                columns=self.JOB_PRIORITY_COLUMNS,
                keybind_mode=self._settings.keybind_mode,
                table_id="job_priority_table",
                id="job-priority-filterable-table",
            )

    def on_mount(self) -> None:
        """Initialize the data tables."""
        if self.user_priorities:
            self.update_user_priorities(self.user_priorities)
        if self.account_priorities:
            self.update_account_priorities(self.account_priorities)
        if self.job_priorities:
            self.update_job_priorities(self.job_priorities)

    @property
    def active_subtab(self) -> PrioritySubtabName:
        """Get the currently active sub-tab name."""
        return self._active_subtab

    def switch_subtab(self, subtab: PrioritySubtabName) -> None:
        """Switch to a different sub-tab.

        Args:
            subtab: Name of the sub-tab to switch to.
        """
        if subtab == self._active_subtab:
            return

        logger.debug(f"Switching priority overview subtab from {self._active_subtab} to {subtab}")

        # Update header to show active tab
        self._update_subtab_header(subtab)

        # Hide all subtab containers
        for container_id in _SUBTAB_CONTAINER_IDS:
            try:
                container = self.query_one(f"#{container_id}", Container)
                container.add_class("priority-subtab-hidden")
            except Exception as exc:
                logger.debug(f"Failed to hide container {container_id}: {exc}")

        # Show the active subtab container
        active_container_id = f"priority-subtab-{subtab}"
        try:
            active_container = self.query_one(f"#{active_container_id}", Container)
            active_container.remove_class("priority-subtab-hidden")

            # Focus the appropriate filterable table
            filterable_ids: dict[PrioritySubtabName, str] = {
                "mine": "my-job-priority-filterable-table",
                "users": "user-priority-filterable-table",
                "accounts": "account-priority-filterable-table",
                "jobs": "job-priority-filterable-table",
            }
            filterable_id = filterable_ids.get(subtab)
            if filterable_id:
                filterable_table = self.query_one(f"#{filterable_id}", FilterableDataTable)
                filterable_table.focus()
        except Exception as exc:
            logger.debug(f"Failed to show container {active_container_id}: {exc}")

        self._active_subtab = subtab
        self.post_message(PrioritySubtabSwitched(subtab))

    def _update_subtab_header(self, active: PrioritySubtabName) -> None:
        """Update the sub-tab header to highlight the active tab.

        Args:
            active: The active sub-tab name.
        """
        try:
            header = self.query_one("#priority-subtab-header-text", Static)

            def _tab_style(key: str, label: str, tab_name: PrioritySubtabName) -> str:
                if active == tab_name:
                    return f"[bold reverse] {key} [/bold reverse]{label}"
                return f"[dim]{key}[/dim] {label}"

            mine = _tab_style("m", "My Priority", "mine")
            users = _tab_style("u", "All Users", "users")
            accounts = _tab_style("a", "Accounts", "accounts")
            jobs = _tab_style("j", "Jobs", "jobs")

            header.update(f"[bold]Priority[/bold]  {mine}  {users}  {accounts}  {jobs}")
        except Exception as exc:
            logger.debug(f"Failed to update subtab header: {exc}")

    def action_switch_subtab_mine(self) -> None:
        """Switch to the My Priority sub-tab."""
        self.switch_subtab("mine")

    def action_switch_subtab_users(self) -> None:
        """Switch to the All Users sub-tab."""
        self.switch_subtab("users")

    def action_switch_subtab_accounts(self) -> None:
        """Switch to the Accounts sub-tab."""
        self.switch_subtab("accounts")

    def action_switch_subtab_jobs(self) -> None:
        """Switch to the Jobs sub-tab."""
        self.switch_subtab("jobs")

    def _get_current_user_account(self) -> str:
        """Get the current user's account from the user priorities.

        Returns:
            The account name, or empty string if not found.
        """
        my_priority = next((p for p in self.user_priorities if p.username == self._current_username), None)
        return my_priority.account if my_priority else ""

    def update_my_priority_summary(self) -> None:
        """Update the 'My Priority' summary panel."""
        try:
            summary = self.query_one("#my-priority-summary", Static)
        except Exception:
            return

        colors = get_theme_colors(self.app)
        markup = _build_my_priority_summary(
            self._current_username,
            self.user_priorities,
            self.account_priorities,
            self.job_priorities,
            colors,
        )
        summary.update(markup)

    def update_my_job_priorities(self) -> None:
        """Update the 'My Priority' pending jobs table."""
        try:
            filterable = self.query_one("#my-job-priority-filterable-table", FilterableDataTable)
        except Exception:
            return

        my_jobs = [j for j in self.job_priorities if j.user == self._current_username]

        # Sort by priority descending
        def sort_key(p: JobPriority) -> float:
            try:
                return float(p.priority)
            except ValueError:
                return 0.0

        my_jobs.sort(key=sort_key, reverse=True)

        rows: list[tuple[str, ...]] = []
        for p in my_jobs:
            rows.append(
                (
                    p.job_id,
                    p.priority,
                    p.age,
                    p.fair_share,
                    p.job_size,
                    p.partition,
                    p.qos,
                )
            )

        filterable.set_data(rows)

        # Update header with count
        try:
            header = self.query_one("#my-priority-jobs-header", Static)
            header.update(f"[bold]Your Pending Jobs ({len(my_jobs)})[/bold]")
        except Exception as exc:
            logger.debug(f"Failed to update my-priority jobs header: {exc}")

    def update_user_priorities(self, priorities: list[UserPriority]) -> None:
        """Update the user priority data table.

        Args:
            priorities: List of user priority statistics to display.
        """
        try:
            filterable = self.query_one("#user-priority-filterable-table", FilterableDataTable)
        except Exception:
            self.user_priorities = priorities
            return

        # Sort by fair share descending (highest priority first)
        def sort_key(p: UserPriority) -> float:
            try:
                return float(p.fair_share)
            except ValueError:
                return 0.0

        sorted_priorities = sorted(priorities, key=sort_key, reverse=True)

        # Compute dense ranks
        fs_values = [sort_key(p) for p in sorted_priorities]
        ranks = compute_dense_ranks(fs_values)
        for p, rank in zip(sorted_priorities, ranks, strict=True):
            p.rank = rank

        self.user_priorities = sorted_priorities

        # Build row data with color-coding and highlighting
        colors = get_theme_colors(self.app)
        rows: list[tuple[str, ...]] = []
        for p in sorted_priorities:
            is_me = p.username == self._current_username
            if is_me:
                # Highlight current user's row
                style = f"bold {colors.accent}"
                rows.append(
                    (
                        _style_cell(p.rank, style),
                        _style_cell(f">> {p.username}", style),
                        _style_cell(p.account, style),
                        _style_cell(p.raw_shares, style),
                        _style_cell(p.norm_shares, style),
                        _style_cell(p.raw_usage, style),
                        _style_cell(p.effective_usage, style),
                        _format_fs_cell(p.fair_share, colors),
                        _format_status_cell(p.fair_share, colors),
                    )
                )
            else:
                rows.append(
                    (
                        p.rank,
                        p.username,
                        p.account,
                        p.raw_shares,
                        p.norm_shares,
                        p.raw_usage,
                        p.effective_usage,
                        _format_fs_cell(p.fair_share, colors),
                        _format_status_cell(p.fair_share, colors),
                    )
                )

        filterable.set_data(rows)

        # Also update my priority summary and jobs if mounted
        self.update_my_priority_summary()
        self.update_my_job_priorities()

    def update_account_priorities(self, priorities: list[AccountPriority]) -> None:
        """Update the account priority data table.

        Args:
            priorities: List of account priority statistics to display.
        """
        try:
            filterable = self.query_one("#account-priority-filterable-table", FilterableDataTable)
        except Exception:
            self.account_priorities = priorities
            return

        # Sort by fair share descending (highest priority first)
        def sort_key(p: AccountPriority) -> float:
            try:
                return float(p.fair_share)
            except ValueError:
                return 0.0

        sorted_priorities = sorted(priorities, key=sort_key, reverse=True)

        # Compute dense ranks
        fs_values = [sort_key(p) for p in sorted_priorities]
        ranks = compute_dense_ranks(fs_values)
        for p, rank in zip(sorted_priorities, ranks, strict=True):
            p.rank = rank

        self.account_priorities = sorted_priorities

        # Build row data with color-coding and highlighting
        colors = get_theme_colors(self.app)
        my_account = self._get_current_user_account()
        rows: list[tuple[str, ...]] = []
        for p in sorted_priorities:
            is_mine = p.account == my_account and my_account != ""
            if is_mine:
                style = f"bold {colors.accent}"
                rows.append(
                    (
                        _style_cell(p.rank, style),
                        _style_cell(p.account, style),
                        _style_cell(p.raw_shares, style),
                        _style_cell(p.norm_shares, style),
                        _style_cell(p.raw_usage, style),
                        _style_cell(p.effective_usage, style),
                        _format_fs_cell(p.fair_share, colors),
                        _format_status_cell(p.fair_share, colors),
                    )
                )
            else:
                rows.append(
                    (
                        p.rank,
                        p.account,
                        p.raw_shares,
                        p.norm_shares,
                        p.raw_usage,
                        p.effective_usage,
                        _format_fs_cell(p.fair_share, colors),
                        _format_status_cell(p.fair_share, colors),
                    )
                )

        filterable.set_data(rows)

        # Also update my priority summary
        self.update_my_priority_summary()

    def update_job_priorities(self, priorities: list[JobPriority]) -> None:
        """Update the job priority data table.

        Args:
            priorities: List of job priority factors to display.
        """
        try:
            filterable = self.query_one("#job-priority-filterable-table", FilterableDataTable)
        except Exception:
            self.job_priorities = priorities
            return

        # Sort by priority descending (highest priority first)
        def sort_key(p: JobPriority) -> float:
            try:
                return float(p.priority)
            except ValueError:
                return 0.0

        sorted_priorities = sorted(priorities, key=sort_key, reverse=True)
        self.job_priorities = sorted_priorities

        # Build row data with current user highlighting
        colors = get_theme_colors(self.app)
        rows: list[tuple[str, ...]] = []
        for p in sorted_priorities:
            is_me = p.user == self._current_username
            if is_me:
                style = f"bold {colors.accent}"
                rows.append(
                    (
                        _style_cell(p.job_id, style),
                        _style_cell(p.user, style),
                        _style_cell(p.account, style),
                        _style_cell(p.priority, style),
                        _style_cell(p.age, style),
                        _style_cell(p.fair_share, style),
                        _style_cell(p.job_size, style),
                        _style_cell(p.partition, style),
                        _style_cell(p.qos, style),
                    )
                )
            else:
                rows.append(
                    (
                        p.job_id,
                        p.user,
                        p.account,
                        p.priority,
                        p.age,
                        p.fair_share,
                        p.job_size,
                        p.partition,
                        p.qos,
                    )
                )

        filterable.set_data(rows)

        # Also update my pending jobs
        self.update_my_job_priorities()

    def update_from_sshare_data(self, entries: list[tuple[str, ...]]) -> None:
        """Update user and account priorities from raw sshare data.

        Args:
            entries: Raw sshare output tuples from get_fair_share_priority().
        """
        user_data, account_data = parse_sshare_output(entries)

        user_priorities = [
            UserPriority(
                username=d["User"],
                account=d["Account"],
                raw_shares=d["RawShares"],
                norm_shares=d["NormShares"],
                raw_usage=d["RawUsage"],
                norm_usage=d["NormUsage"],
                effective_usage=d["EffectvUsage"],
                fair_share=d["FairShare"],
            )
            for d in user_data
        ]

        account_priorities = [
            AccountPriority(
                account=d["Account"],
                raw_shares=d["RawShares"],
                norm_shares=d["NormShares"],
                raw_usage=d["RawUsage"],
                norm_usage=d["NormUsage"],
                effective_usage=d["EffectvUsage"],
                fair_share=d["FairShare"],
            )
            for d in account_data
        ]

        self.update_user_priorities(user_priorities)
        self.update_account_priorities(account_priorities)

    def update_from_sprio_data(self, entries: list[tuple[str, ...]]) -> None:
        """Update job priorities from raw sprio data.

        Args:
            entries: Raw sprio output tuples from get_pending_job_priority().
        """
        job_data = parse_sprio_output(entries)

        job_priorities = [
            JobPriority(
                job_id=d["JobID"],
                user=d["User"],
                account=d["Account"],
                priority=d["Priority"],
                age=d["Age"],
                fair_share=d["FairShare"],
                job_size=d["JobSize"],
                partition=d["Partition"],
                qos=d["QOS"],
            )
            for d in job_data
        ]

        self.update_job_priorities(job_priorities)
