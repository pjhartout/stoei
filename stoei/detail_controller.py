"""Detail-modal flows for the SLURM monitor.

This module owns the logic that opens the job, node, user, and account
detail modals. It collaborates with the main app through a small
:class:`_DetailHost` protocol so it can drive workers, schedule UI callbacks,
and push modal screens without importing the concrete ``SlurmMonitor`` app
(which would create an import cycle, since the app imports this module).
"""

import re
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

from textual.notifications import SeverityLevel
from textual.screen import Screen
from textual.widgets import DataTable
from textual.widgets.data_table import RowKey
from textual.worker import Worker

from stoei.logger import get_logger
from stoei.slurm.array_parser import normalize_array_job_id
from stoei.slurm.commands import (
    get_job_info_and_log_paths,
    get_node_info,
    get_user_jobs,
)
from stoei.slurm.formatters import format_account_info, format_user_info
from stoei.usage_stats import UserEnergyStats, UserPendingStats, UserStats
from stoei.widgets.screens import (
    AccountInfoScreen,
    JobInfoScreen,
    JobInputScreen,
    NodeInfoScreen,
    UserInfoScreen,
)
from stoei.widgets.user_overview import UserOverviewTab

logger = get_logger(__name__)

_JobInfoEntry = tuple[str, str | None, str | None, str | None]

# Result type a pushed screen resolves to (mirrors Textual's ScreenResultType).
_ScreenResultType = TypeVar("_ScreenResultType")


class _DetailHost(Protocol):
    """Minimal surface the :class:`DetailController` needs from the app.

    Declares only the attributes and methods the controller touches so the
    controller stays decoupled from the concrete ``SlurmMonitor`` app and no
    import cycle is introduced.
    """

    # Cached SLURM data the detail flows read from the app.
    _job_info_cache: dict[str, _JobInfoEntry]
    _all_users_jobs: list[tuple[str, ...]]
    _energy_history_jobs: list[tuple[str, ...]]
    _fair_share_entries: list[tuple[str, ...]]
    _job_priority_entries: list[tuple[str, ...]]

    def notify(
        self,
        message: str,
        *,
        title: str = ...,
        severity: SeverityLevel = ...,
        timeout: float | None = ...,
        markup: bool = ...,
    ) -> None:
        """Show a transient notification to the user."""
        ...

    def push_screen(
        self,
        screen: Screen[_ScreenResultType] | str,
        callback: Callable[[_ScreenResultType | None], None]
        | Callable[[_ScreenResultType | None], Awaitable[None]]
        | None = ...,
    ) -> object:
        """Push a modal screen onto the screen stack."""
        ...

    def run_worker(
        self,
        work: Callable[[], object],
        *,
        name: str = ...,
        group: str = ...,
        exclusive: bool = ...,
        thread: bool = ...,
    ) -> Worker[object]:
        """Run *work* in a background worker."""
        ...

    def query_one(self, selector: str, expect_type: type[DataTable]) -> DataTable:
        """Return the single widget matching *selector* with the given type."""
        ...

    def _post_ui_callback(self, callback: Callable[[], object]) -> None:
        """Schedule *callback* on the main thread without blocking the caller."""
        ...


class DetailController:
    """Owns the job/node/user/account detail-modal flows.

    The controller fetches detail data in background workers and pushes the
    corresponding modal screens. It delegates all UI access back to the host
    app via the :class:`_DetailHost` protocol.
    """

    def __init__(self, host: _DetailHost) -> None:
        """Initialise the controller.

        Args:
            host: The app the controller drives modals on.
        """
        self._host = host

    def show_job_info_prompt(self) -> None:
        """Prompt for a job ID, then fetch and display its info."""

        def handle_job_id(job_id: object) -> None:
            if isinstance(job_id, str) and job_id:
                logger.info(f"Looking up job info for {job_id}")
                self._host.notify("Loading job information...", timeout=2)
                # Run SLURM queries in background worker to avoid blocking UI
                self._host.run_worker(
                    lambda: self.fetch_and_display_job_info(job_id),
                    name="fetch_job_info",
                    thread=True,
                )

        self._host.push_screen(JobInputScreen(), handle_job_id)

    def fetch_and_display_job_info(self, job_id: str) -> None:
        """Fetch job info in background and display on main thread.

        Uses the job info cache for instant display on cache hit. On miss,
        fetches via a single combined SLURM query and stores the result.

        Args:
            job_id: The SLURM job ID to fetch.
        """
        query_id = normalize_array_job_id(job_id)

        # Check cache first
        cached = self._host._job_info_cache.get(query_id)
        if cached is not None:
            logger.debug(f"Job info cache hit for {query_id}")
            job_info, error, stdout_path, stderr_path = cached
        else:
            job_info, error, stdout_path, stderr_path = get_job_info_and_log_paths(query_id)
            self._host._job_info_cache[query_id] = (job_info, error, stdout_path, stderr_path)

        # Schedule UI update on main thread
        self._host._post_ui_callback(
            lambda: self._host.push_screen(JobInfoScreen(job_id, job_info, error, stdout_path, stderr_path))
        )

    def show_detail_for_row(self, table: DataTable, row_key: RowKey, noun: str, show: Callable[[str], None]) -> None:
        """Extract the first-column identifier from a row and open its detail modal.

        Args:
            table: The DataTable containing the row.
            row_key: The key of the row to show info for.
            noun: Entity name used in log and error messages (e.g. "node name").
            show: Callback that opens the detail modal for the extracted identifier.
        """
        try:
            row_data = table.get_row(row_key)
            # Remove Rich markup tags if present.
            value = re.sub(r"\[.*?\]", "", str(row_data[0])).strip()
            if not value:
                logger.warning(f"Could not extract {noun} from row {row_key}")
                self._host.notify(f"Could not get {noun} from selected row", severity="error")
                return
            logger.info(f"Showing info for selected {noun} {value}")
            show(value)
        except (IndexError, KeyError):
            logger.exception(f"Could not get {noun} from row {row_key}")
            self._host.notify(f"Could not get {noun} from selected row", severity="error")

    def show_node_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show node info for a specific row in the nodes table."""
        self.show_detail_for_row(table, row_key, "node name", self.show_node_info)

    def show_node_info(self, node_name: str) -> None:
        """Show detailed information for a node.

        Args:
            node_name: The name of the node to display.
        """
        logger.info(f"Fetching node info for {node_name}")
        self._host.notify("Loading node information...", timeout=2)

        # Get node info in a worker to avoid blocking
        def fetch_node_info() -> None:
            node_info, error = get_node_info(node_name)
            self._host._post_ui_callback(lambda: self.display_node_info(node_name, node_info, error))

        self._host.run_worker(fetch_node_info, name="fetch_node_info", thread=True)

    def display_node_info(self, node_name: str, node_info: str, error: str | None) -> None:
        """Display node information in a modal screen.

        Args:
            node_name: The node name.
            node_info: Formatted node information.
            error: Optional error message.
        """
        self._host.push_screen(NodeInfoScreen(node_name, node_info, error))
        logger.debug(f"Displayed node info screen for {node_name}")

    def show_user_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show user info for a specific row in the users table."""
        self.show_detail_for_row(table, row_key, "username", self.show_user_info)

    def show_user_info(self, username: str) -> None:
        """Show detailed information for a user.

        Args:
            username: The username to display.
        """
        logger.info(f"Fetching user info for {username}")
        self._host.notify("Loading user information...", timeout=2)

        # Capture cached data references for use in worker thread
        all_users_jobs = self._host._all_users_jobs
        energy_history_jobs = self._host._energy_history_jobs
        fair_share_entries = self._host._fair_share_entries
        job_priority_entries = self._host._job_priority_entries

        # Get user info in a worker to avoid blocking
        def fetch_user_info() -> None:  # noqa: PLR0912
            jobs, error = get_user_jobs(username)
            if error:
                self._host._post_ui_callback(lambda: self.display_user_info(username, "", error))
                return

            # Aggregate user stats from the jobs
            # Build a job list in the format expected by aggregate_user_stats
            # Jobs from get_user_jobs: (JobID, Name, Partition, State, Time, Nodes, NodeList, TRES)
            # aggregate_user_stats expects: (JobID, Name, User, Partition, State, Time, Nodes, NodeList, TRES)
            min_user_job_fields = 8  # Minimum fields from get_user_jobs
            formatted_jobs: list[tuple[str, ...]] = []
            for job in jobs:
                if len(job) >= min_user_job_fields:
                    # Insert username at position 2
                    formatted_job = (job[0], job[1], username, job[2], job[3], job[4], job[5], job[6], job[7])
                    formatted_jobs.append(formatted_job)

            user_stats_list = UserOverviewTab.aggregate_user_stats(formatted_jobs)

            # Find stats for this user
            user_stats: UserStats | None = None
            for stats in user_stats_list:
                if stats.username == username:
                    user_stats = stats
                    break

            if user_stats is None:
                # Create default stats if no jobs
                user_stats = UserStats(
                    username=username,
                    job_count=0,
                    total_cpus=0,
                    total_memory_gb=0.0,
                    total_gpus=0,
                    total_nodes=0,
                    gpu_types="",
                )

            # Gather pending stats from cached all users jobs
            pending_stats: UserPendingStats | None = None
            if all_users_jobs:
                pending_stats_list = UserOverviewTab.aggregate_pending_user_stats(all_users_jobs)
                for stats in pending_stats_list:
                    if stats.username == username:
                        pending_stats = stats
                        break

            # Gather energy stats from cached energy history
            energy_stats: UserEnergyStats | None = None
            if energy_history_jobs:
                energy_stats_list = UserOverviewTab.aggregate_energy_stats(energy_history_jobs)
                for stats in energy_stats_list:
                    if stats.username == username:
                        energy_stats = stats
                        break

            # Gather fair-share priority info from cached data
            # sshare format: (Account, User, RawShares, NormShares, RawUsage, NormUsage, EffectvUsage, FairShare)
            priority_info: dict[str, str] | None = None
            if fair_share_entries:
                min_sshare_fields = 8
                for entry in fair_share_entries:
                    if len(entry) >= min_sshare_fields and entry[1] == username:
                        priority_info = {
                            "account": entry[0],
                            "raw_shares": entry[2],
                            "norm_shares": entry[3],
                            "raw_usage": entry[4],
                            "norm_usage": entry[5],
                            "effective_usage": entry[6],
                            "fair_share": entry[7],
                        }
                        break

            # Gather pending job priorities for this user
            # sprio format: (JOBID, USER, ACCOUNT, PRIORITY, AGE, FAIRSHARE, JOBSIZE, PARTITION, QOS)
            job_priorities: list[dict[str, str]] = []
            if job_priority_entries:
                min_sprio_fields = 9
                for entry in job_priority_entries:
                    if len(entry) >= min_sprio_fields and entry[1] == username:
                        job_priorities.append(
                            {
                                "job_id": entry[0],
                                "priority": entry[3],
                                "age": entry[4],
                                "fair_share": entry[5],
                                "job_size": entry[6],
                                "partition": entry[7],
                                "qos": entry[8],
                            }
                        )

            formatted_info = format_user_info(
                username,
                user_stats,
                jobs,
                pending_stats=pending_stats,
                energy_stats=energy_stats,
                priority_info=priority_info,
                job_priorities=job_priorities if job_priorities else None,
            )
            self._host._post_ui_callback(lambda: self.display_user_info(username, formatted_info, None))

        self._host.run_worker(fetch_user_info, name="fetch_user_info", thread=True)

    def display_user_info(self, username: str, user_info: str, error: str | None) -> None:
        """Display user information in a modal screen.

        Args:
            username: The username.
            user_info: Formatted user information.
            error: Optional error message.
        """
        self._host.push_screen(UserInfoScreen(username, user_info, error))
        logger.debug(f"Displayed user info screen for {username}")

    def show_account_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show account info for a specific row in the accounts table."""
        self.show_detail_for_row(table, row_key, "account name", self.show_account_info)

    def show_account_info(self, account_name: str) -> None:
        """Show detailed information for an account/institute.

        Args:
            account_name: The account/institute name to display.
        """
        logger.info(f"Fetching account info for {account_name}")
        self._host.notify("Loading account information...", timeout=2)

        # Capture cached data references for use in worker thread
        fair_share_entries = self._host._fair_share_entries
        all_users_jobs = self._host._all_users_jobs
        job_priority_entries = self._host._job_priority_entries

        # Get account info in a worker to avoid blocking
        def fetch_account_info() -> None:  # noqa: PLR0912
            # Get account-level priority info from cached sshare data
            # sshare format: (Account, User, RawShares, NormShares, RawUsage, NormUsage, EffectvUsage, FairShare)
            account_priority: dict[str, str] = {}
            users_in_account: list[dict[str, str]] = []

            if fair_share_entries:
                min_sshare_fields = 8
                for entry in fair_share_entries:
                    if len(entry) >= min_sshare_fields and entry[0] == account_name:
                        if entry[1]:  # Has username - this is a user entry
                            users_in_account.append(
                                {
                                    "username": entry[1],
                                    "raw_shares": entry[2],
                                    "norm_shares": entry[3],
                                    "raw_usage": entry[4],
                                    "norm_usage": entry[5],
                                    "effective_usage": entry[6],
                                    "fair_share": entry[7],
                                }
                            )
                        else:  # No username - this is the account-level entry
                            account_priority = {
                                "raw_shares": entry[2],
                                "norm_shares": entry[3],
                                "raw_usage": entry[4],
                                "norm_usage": entry[5],
                                "effective_usage": entry[6],
                                "fair_share": entry[7],
                            }

            # Get usernames in this account for filtering jobs
            usernames_in_account = {u["username"] for u in users_in_account}

            # Filter running jobs for users in this account
            # Job format: (JobID, Name, User, Partition, State, Time, Nodes, NodeList, TRES)
            running_jobs: list[tuple[str, ...]] = []
            pending_jobs: list[tuple[str, ...]] = []

            if all_users_jobs:
                min_job_fields = 5
                username_index = 2
                state_index = 4
                for job in all_users_jobs:
                    if len(job) >= min_job_fields:
                        username = job[username_index].strip()
                        state = job[state_index].strip().upper()
                        if username in usernames_in_account:
                            if state in ("RUNNING", "R"):
                                running_jobs.append(job)
                            elif state in ("PENDING", "PD"):
                                pending_jobs.append(job)

            # Get pending job priorities for users in this account
            # sprio format: (JOBID, USER, ACCOUNT, PRIORITY, AGE, FAIRSHARE, JOBSIZE, PARTITION, QOS)
            job_priorities: list[dict[str, str]] = []
            if job_priority_entries:
                min_sprio_fields = 9
                for entry in job_priority_entries:
                    if len(entry) >= min_sprio_fields:
                        # Check if account matches or user is in account
                        entry_account = entry[2]
                        entry_user = entry[1]
                        if entry_account == account_name or entry_user in usernames_in_account:
                            job_priorities.append(
                                {
                                    "job_id": entry[0],
                                    "user": entry[1],
                                    "account": entry[2],
                                    "priority": entry[3],
                                    "age": entry[4],
                                    "fair_share": entry[5],
                                    "job_size": entry[6],
                                    "partition": entry[7],
                                    "qos": entry[8],
                                }
                            )

            formatted_info = format_account_info(
                account_name,
                account_priority,
                users_in_account,
                running_jobs,
                pending_jobs,
                job_priorities=job_priorities if job_priorities else None,
            )
            self._host._post_ui_callback(lambda: self.display_account_info(account_name, formatted_info, None))

        self._host.run_worker(fetch_account_info, name="fetch_account_info", thread=True)

    def display_account_info(self, account_name: str, account_info: str, error: str | None) -> None:
        """Display account information in a modal screen.

        Args:
            account_name: The account/institute name.
            account_info: Formatted account information.
            error: Optional error message.
        """
        self._host.push_screen(AccountInfoScreen(account_name, account_info, error))
        logger.debug(f"Displayed account info screen for {account_name}")

    def show_job_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show job info for a specific row in a table.

        Args:
            table: The DataTable containing the row.
            row_key: The key of the row to show info for.
        """
        try:
            row_data = table.get_row(row_key)
            job_id = str(row_data[0]).strip()
            logger.info(f"Showing info for selected job {job_id}")
            self._host.notify("Loading job information...", timeout=2)
            # Run SLURM queries in background worker to avoid blocking UI
            self._host.run_worker(
                lambda: self.fetch_and_display_job_info(job_id),
                name="fetch_job_info",
                thread=True,
            )
        except (IndexError, KeyError):
            logger.exception(f"Could not get job ID from row {row_key}")
            self._host.notify("Could not get job ID from selected row", severity="error")

    def show_selected_job_info(self) -> None:
        """Show job info for the currently selected row in the jobs table."""
        jobs_table = self._host.query_one("#jobs_table", DataTable)

        if jobs_table.row_count == 0:
            self._host.notify("No jobs to display", severity="warning")
            return

        cursor_row = jobs_table.cursor_row
        if cursor_row is None or cursor_row < 0:
            self._host.notify("No row selected", severity="warning")
            return

        try:
            row_data = jobs_table.get_row_at(cursor_row)
            job_id = str(row_data[0]).strip()
            logger.info(f"Showing info for selected job {job_id}")
            self._host.notify("Loading job information...", timeout=2)
            # Run SLURM queries in background worker to avoid blocking UI
            self._host.run_worker(
                lambda: self.fetch_and_display_job_info(job_id),
                name="fetch_job_info",
                thread=True,
            )
        except (IndexError, KeyError):
            logger.exception(f"Could not get job ID from row {cursor_row}")
            self._host.notify("Could not get job ID from selected row", severity="error")
