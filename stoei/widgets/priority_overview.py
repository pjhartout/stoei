"""Priority overview tab widget with sub-tabs for user, account, and job priority views."""

from dataclasses import dataclass
from typing import ClassVar, Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from stoei.logger import get_logger
from stoei.settings import load_settings
from stoei.slurm.parser import parse_sprio_output, parse_sshare_output
from stoei.widgets.filterable_table import ColumnConfig, FilterableDataTable

logger = get_logger(__name__)


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
PrioritySubtabName = Literal["users", "accounts", "jobs"]


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
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("u", "switch_subtab_users", "Users", show=False),
        Binding("a", "switch_subtab_accounts", "Accounts", show=False),
        Binding("j", "switch_subtab_jobs", "Jobs", show=False),
    ]

    # Column configs for each priority table
    USER_PRIORITY_COLUMNS: ClassVar[list[ColumnConfig]] = [
        ColumnConfig(name="User", key="user", sortable=True, filterable=True, width=15),
        ColumnConfig(name="Account", key="account", sortable=True, filterable=True, width=15),
        ColumnConfig(name="RawShares", key="raw_shares", sortable=True, filterable=True, width=12),
        ColumnConfig(name="NormShares", key="norm_shares", sortable=True, filterable=True, width=12),
        ColumnConfig(name="RawUsage", key="raw_usage", sortable=True, filterable=True, width=12),
        ColumnConfig(name="EffectvUsage", key="effective_usage", sortable=True, filterable=True, width=12),
        ColumnConfig(name="FairShare", key="fair_share", sortable=True, filterable=True, width=10),
    ]

    ACCOUNT_PRIORITY_COLUMNS: ClassVar[list[ColumnConfig]] = [
        ColumnConfig(name="Account", key="account", sortable=True, filterable=True, width=20),
        ColumnConfig(name="RawShares", key="raw_shares", sortable=True, filterable=True, width=12),
        ColumnConfig(name="NormShares", key="norm_shares", sortable=True, filterable=True, width=12),
        ColumnConfig(name="RawUsage", key="raw_usage", sortable=True, filterable=True, width=14),
        ColumnConfig(name="EffectvUsage", key="effective_usage", sortable=True, filterable=True, width=12),
        ColumnConfig(name="FairShare", key="fair_share", sortable=True, filterable=True, width=10),
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
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        """Initialize the PriorityOverviewTab widget.

        Args:
            name: The name of the widget.
            id: The ID of the widget in the DOM.
            classes: The CSS classes for the widget.
            disabled: Whether the widget is disabled.
        """
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.user_priorities: list[UserPriority] = []
        self.account_priorities: list[AccountPriority] = []
        self.job_priorities: list[JobPriority] = []
        self._active_subtab: PrioritySubtabName = "users"
        self._settings = load_settings()

    def compose(self) -> ComposeResult:
        """Create the priority overview layout with sub-tabs."""
        # Sub-tab header with keyboard shortcuts
        with Horizontal(id="priority-subtab-header"):
            yield Static(
                "[bold]⚖️  Priority[/bold]  "
                "[bold reverse] u [/bold reverse]Users  "
                "[dim]a[/dim] Accounts  "
                "[dim]j[/dim] Jobs",
                id="priority-subtab-header-text",
            )

        # Users priority sub-tab (default visible)
        with Container(id="priority-subtab-users", classes="priority-subtab-content"):
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
        # If we already have data, update the tables
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
            subtab: Name of the sub-tab to switch to ('users', 'accounts', or 'jobs').
        """
        if subtab == self._active_subtab:
            return

        logger.debug(f"Switching priority overview subtab from {self._active_subtab} to {subtab}")

        # Update header to show active tab
        self._update_subtab_header(subtab)

        # Hide all subtab containers
        for container_id in ["priority-subtab-users", "priority-subtab-accounts", "priority-subtab-jobs"]:
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
            filterable_ids = {
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

            # Build header with active tab highlighted
            users_style = "[bold reverse] u [/bold reverse]Users" if active == "users" else "[dim]u[/dim] Users"
            accounts_style = (
                "[bold reverse] a [/bold reverse]Accounts" if active == "accounts" else "[dim]a[/dim] Accounts"
            )
            jobs_style = "[bold reverse] j [/bold reverse]Jobs" if active == "jobs" else "[dim]j[/dim] Jobs"

            header.update(f"[bold]⚖️  Priority[/bold]  {users_style}  {accounts_style}  {jobs_style}")
        except Exception as exc:
            logger.debug(f"Failed to update subtab header: {exc}")

    def action_switch_subtab_users(self) -> None:
        """Switch to the Users sub-tab."""
        self.switch_subtab("users")

    def action_switch_subtab_accounts(self) -> None:
        """Switch to the Accounts sub-tab."""
        self.switch_subtab("accounts")

    def action_switch_subtab_jobs(self) -> None:
        """Switch to the Jobs sub-tab."""
        self.switch_subtab("jobs")

    def update_user_priorities(self, priorities: list[UserPriority]) -> None:
        """Update the user priority data table.

        Args:
            priorities: List of user priority statistics to display.
        """
        try:
            filterable = self.query_one("#user-priority-filterable-table", FilterableDataTable)
        except Exception:
            # Table might not be mounted yet, store for later
            self.user_priorities = priorities
            return

        # Sort by fair share descending (highest priority first)
        def sort_key(p: UserPriority) -> float:
            try:
                return float(p.fair_share)
            except ValueError:
                return 0.0

        sorted_priorities = sorted(priorities, key=sort_key, reverse=True)
        self.user_priorities = sorted_priorities

        # Build row data
        rows: list[tuple[str, ...]] = []
        for p in sorted_priorities:
            rows.append(
                (
                    p.username,
                    p.account,
                    p.raw_shares,
                    p.norm_shares,
                    p.raw_usage,
                    p.effective_usage,
                    p.fair_share,
                )
            )

        filterable.set_data(rows)

    def update_account_priorities(self, priorities: list[AccountPriority]) -> None:
        """Update the account priority data table.

        Args:
            priorities: List of account priority statistics to display.
        """
        try:
            filterable = self.query_one("#account-priority-filterable-table", FilterableDataTable)
        except Exception:
            # Table might not be mounted yet, store for later
            self.account_priorities = priorities
            return

        # Sort by fair share descending (highest priority first)
        def sort_key(p: AccountPriority) -> float:
            try:
                return float(p.fair_share)
            except ValueError:
                return 0.0

        sorted_priorities = sorted(priorities, key=sort_key, reverse=True)
        self.account_priorities = sorted_priorities

        # Build row data
        rows: list[tuple[str, ...]] = []
        for p in sorted_priorities:
            rows.append(
                (
                    p.account,
                    p.raw_shares,
                    p.norm_shares,
                    p.raw_usage,
                    p.effective_usage,
                    p.fair_share,
                )
            )

        filterable.set_data(rows)

    def update_job_priorities(self, priorities: list[JobPriority]) -> None:
        """Update the job priority data table.

        Args:
            priorities: List of job priority factors to display.
        """
        try:
            filterable = self.query_one("#job-priority-filterable-table", FilterableDataTable)
        except Exception:
            # Table might not be mounted yet, store for later
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

        # Build row data
        rows: list[tuple[str, ...]] = []
        for p in sorted_priorities:
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

    def update_from_sshare_data(self, entries: list[tuple[str, ...]]) -> None:
        """Update user and account priorities from raw sshare data.

        Args:
            entries: Raw sshare output tuples from get_fair_share_priority().
        """
        user_data, account_data = parse_sshare_output(entries)

        # Convert to dataclasses
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

        # Convert to dataclasses
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
