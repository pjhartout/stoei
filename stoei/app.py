"""Main Textual TUI application for stoei."""

import re
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.timer import Timer
from textual.widgets import Button, DataTable, Footer, Header, Static
from textual.widgets.data_table import RowKey
from textual.worker import Worker, WorkerState

from stoei.logger import add_tui_sink, get_logger, remove_tui_sink
from stoei.slurm.cache import JobCache, JobState
from stoei.slurm.commands import (
    cancel_job,
    get_all_users_jobs,
    get_cluster_nodes,
    get_job_info,
    get_job_log_paths,
)
from stoei.slurm.validation import check_slurm_available
from stoei.widgets.cluster_sidebar import ClusterSidebar, ClusterStats
from stoei.widgets.log_pane import LogPane
from stoei.widgets.node_overview import NodeInfo, NodeOverviewTab
from stoei.widgets.screens import CancelConfirmScreen, JobInfoScreen, JobInputScreen
from stoei.widgets.slurm_error_screen import SlurmUnavailableScreen
from stoei.widgets.tabs import TabContainer, TabSwitched
from stoei.widgets.user_overview import UserOverviewTab

logger = get_logger(__name__)

# Path to styles directory
STYLES_DIR = Path(__file__).parent / "styles"

# Refresh interval in seconds (increased for better performance)
REFRESH_INTERVAL = 5.0


class SlurmMonitor(App[None]):
    """Textual TUI app for monitoring SLURM jobs."""

    ENABLE_COMMAND_PALETTE = False
    CSS_PATH: ClassVar[list[Path]] = [
        STYLES_DIR / "app.tcss",
        STYLES_DIR / "modals.tcss",
    ]
    BINDINGS: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh Now"),
        ("i", "show_job_info", "Job Info"),
        ("enter", "show_selected_job_info", "View Selected Job"),
        ("c", "cancel_job", "Cancel Job"),
        ("1", "switch_tab_jobs", "Jobs Tab"),
        ("2", "switch_tab_nodes", "Nodes Tab"),
        ("3", "switch_tab_users", "Users Tab"),
        ("left", "previous_tab", "Previous Tab"),
        ("right", "next_tab", "Next Tab"),
        ("shift+tab", "previous_tab", "Previous Tab"),
    )

    def __init__(self) -> None:
        """Initialize the SLURM monitor app."""
        super().__init__()
        self.refresh_interval: float = REFRESH_INTERVAL
        self.auto_refresh_timer: Timer | None = None
        self._job_cache: JobCache = JobCache()
        self._refresh_worker: Worker[None] | None = None
        self._initial_load_complete: bool = False
        self._log_sink_id: int | None = None
        self._cluster_nodes: list[dict[str, str]] = []
        self._all_users_jobs: list[tuple[str, ...]] = []
        logger.info("Initializing SlurmMonitor app")

    def compose(self) -> ComposeResult:
        """Create the UI layout.

        Yields:
            The widgets that make up the application UI.
        """
        yield Header(show_clock=True)

        with Horizontal(id="main-container"):
            # Main content area with tabs
            with Container(id="content-area"):
                yield TabContainer(id="tab-container")

                # Jobs tab (default)
                with Container(id="tab-jobs-content", classes="tab-content"):
                    with Horizontal(id="jobs-header"):
                        yield Static("[bold]📋 My Jobs[/bold]", id="jobs-title")
                        yield Button("🗑️ Cancel Job", variant="error", id="cancel-job-btn")
                    yield DataTable(id="jobs_table")

                # Nodes tab
                with Container(id="tab-nodes-content", classes="tab-content"):
                    yield NodeOverviewTab(id="node-overview")

                # Users tab
                with Container(id="tab-users-content", classes="tab-content"):
                    yield UserOverviewTab(id="user-overview")

            # Sidebar with cluster load (on the right)
            yield ClusterSidebar(id="cluster-sidebar")

        with Container(id="log-panel"):
            yield Static("[bold]📝 Logs[/bold]", id="log-title")
            yield LogPane(id="log_pane")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize table and start data loading."""
        # Check SLURM availability first
        is_available, error_msg = check_slurm_available()
        if not is_available:
            logger.error(f"SLURM not available: {error_msg}")
            self.push_screen(SlurmUnavailableScreen())
            return

        # Set up log pane as a loguru sink
        log_pane = self.query_one("#log_pane", LogPane)
        self._log_sink_id = add_tui_sink(log_pane.sink, level="DEBUG")

        logger.info("Mounting application")

        # Hide non-default tabs initially and ensure jobs tab is visible
        try:
            jobs_tab = self.query_one("#tab-jobs-content", Container)
            jobs_tab.display = True
            nodes_tab = self.query_one("#tab-nodes-content", Container)
            nodes_tab.display = False
            users_tab = self.query_one("#tab-users-content", Container)
            users_tab.display = False
        except Exception as exc:
            logger.warning(f"Failed to set tab visibility: {exc}")

        jobs_table = self.query_one("#jobs_table", DataTable)
        jobs_table.cursor_type = "row"
        jobs_table.add_columns("JobID", "Name", "State", "Time", "Nodes", "NodeList")
        logger.debug("Jobs table columns added, ready for data")

        # Show loading message
        self.notify("Loading job data...", timeout=2)

        # Initial data load in background worker
        self._start_refresh_worker()

    def _start_refresh_worker(self) -> None:
        """Start background worker for data refresh."""
        if self._refresh_worker is not None and self._refresh_worker.state == WorkerState.RUNNING:
            logger.debug("Refresh worker already running, skipping")
            return

        self._refresh_worker = self.run_worker(
            self._refresh_data_async,
            name="refresh_data",
            exclusive=True,
            thread=True,
        )

    def _refresh_data_async(self) -> None:
        """Refresh data from SLURM (runs in background worker thread)."""
        logger.debug("Background refresh starting")

        # Workers run in a separate thread, so blocking calls are safe
        self._job_cache.refresh()

        # Also refresh cluster nodes and all users jobs
        nodes, error = get_cluster_nodes()
        if error:
            logger.warning(f"Failed to get cluster nodes: {error}")
        else:
            logger.debug(f"Fetched {len(nodes)} cluster nodes")
        self._cluster_nodes = nodes if not error else []

        all_jobs = get_all_users_jobs()
        logger.debug(f"Fetched {len(all_jobs)} jobs from all users")
        self._all_users_jobs = all_jobs

        # Schedule UI update on main thread
        self.call_from_thread(self._update_ui_from_cache)

    def _update_ui_from_cache(self) -> None:
        """Update UI components from cached data (must run on main thread)."""
        # Check which tab is active
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            active_tab = tab_container.active_tab
        except Exception:
            active_tab = "jobs"  # Default to jobs tab if we can't determine

        # Only update jobs table if jobs tab is active
        if active_tab == "jobs":
            try:
                jobs_table = self.query_one("#jobs_table", DataTable)
            except Exception as exc:
                logger.error(f"Failed to find jobs table: {exc}")
            else:
                # Save cursor position before clearing
                cursor_row = jobs_table.cursor_row

                # Clear existing rows but keep columns
                jobs_table.clear(columns=False)

                # Add jobs from cache with state-based styling
                jobs = self._job_cache.jobs
                logger.debug(f"Updating UI with {len(jobs)} jobs from cache")
                rows_added = 0
                for job in jobs:
                    try:
                        # Apply state-based row styling using Rich markup
                        state_display = self._format_state(job.state, job.state_category)
                        jobs_table.add_row(
                            job.job_id,
                            job.name,
                            state_display,
                            job.time,
                            job.nodes,
                            job.node_list,
                        )
                        rows_added += 1
                    except Exception as exc:
                        logger.error(f"Failed to add job {job.job_id} to table: {exc}")
                logger.debug(f"Added {rows_added} rows to jobs table (table now has {jobs_table.row_count} rows)")

                # Ensure table is properly displayed and visible
                if rows_added > 0:
                    logger.debug(f"Table has {jobs_table.row_count} rows, columns: {list(jobs_table.columns.keys())}")

                # Restore cursor position if possible
                cursor_restored = False
                if cursor_row is not None and jobs_table.row_count > 0:
                    new_row = min(cursor_row, jobs_table.row_count - 1)
                    jobs_table.move_cursor(row=new_row)
                    cursor_restored = True

                # Force a refresh and ensure table is visible
                if jobs_table.row_count > 0:
                    jobs_table.display = True
                    # Ensure table is mounted and has proper size
                    if jobs_table.is_attached:
                        # Ensure parent containers are properly sized
                        try:
                            jobs_tab = self.query_one("#tab-jobs-content", Container)
                            if jobs_tab.is_attached:
                                jobs_tab.refresh(layout=True)
                        except Exception:
                            pass
                        # Force layout recalculation for the table
                        jobs_table.refresh(layout=True)
                        # Move cursor to first row only if we didn't restore a position
                        if jobs_table.row_count > 0 and not cursor_restored:
                            jobs_table.move_cursor(row=0)
                        logger.debug(
                            f"Table refreshed: {jobs_table.row_count} rows, "
                            f"size={jobs_table.size}, visible={jobs_table.visible}, "
                            f"display={jobs_table.display}"
                        )
                    else:
                        logger.warning("Table is not attached to DOM")

        # Update cluster sidebar
        self._update_cluster_sidebar()

        # Update node and user overview if those tabs are active
        try:
            tab_container = self.query_one("#tab-container", TabContainer)
            if tab_container.active_tab == "nodes":
                self._update_node_overview()
            elif tab_container.active_tab == "users":
                self._update_user_overview()
        except Exception:
            pass

        # Start auto-refresh timer after initial load
        if not self._initial_load_complete:
            self._initial_load_complete = True
            self.auto_refresh_timer = self.set_interval(self.refresh_interval, self._start_refresh_worker)
            logger.info(f"Auto-refresh started with interval {self.refresh_interval}s")

            # Focus the table to ensure it's rendered
            try:
                jobs_table.focus()
                logger.debug("Focused jobs table")
            except Exception as exc:
                logger.warning(f"Failed to focus jobs table: {exc}")

    def _format_state(self, state: str, category: JobState) -> str:
        """Format job state with color coding.

        Args:
            state: Raw state string.
            category: Categorized state.

        Returns:
            Rich-formatted state string.
        """
        state_formats = {
            JobState.RUNNING: f"[bold green]{state}[/bold green]",
            JobState.PENDING: f"[bold yellow]{state}[/bold yellow]",
            JobState.COMPLETED: f"[green]{state}[/green]",
            JobState.FAILED: f"[bold red]{state}[/bold red]",
            JobState.CANCELLED: f"[dim]{state}[/dim]",
            JobState.TIMEOUT: f"[red]{state}[/red]",
        }
        return state_formats.get(category, state)

    def _update_cluster_sidebar(self) -> None:
        """Update the cluster sidebar with current statistics."""
        try:
            sidebar = self.query_one("#cluster-sidebar", ClusterSidebar)
            stats = self._calculate_cluster_stats()
            sidebar.update_stats(stats)
            logger.debug(f"Updated cluster sidebar: {stats.total_nodes} nodes, {stats.total_cpus} CPUs")
        except Exception as exc:
            logger.error(f"Failed to update cluster sidebar: {exc}", exc_info=True)

    def _calculate_cluster_stats(self) -> ClusterStats:
        """Calculate cluster statistics from node data.

        Returns:
            ClusterStats object with aggregated statistics.
        """
        stats = ClusterStats()

        if not self._cluster_nodes:
            logger.debug("No cluster nodes available for stats calculation")
            return stats

        for node_data in self._cluster_nodes:
            # Parse node information
            node_name = node_data.get("NodeName", "")
            state = node_data.get("State", "").upper()

            # Count nodes
            stats.total_nodes += 1
            if "IDLE" in state or "ALLOCATED" in state or "MIXED" in state:
                if "IDLE" in state:
                    stats.free_nodes += 1
                else:
                    stats.allocated_nodes += 1

            # Parse CPUs
            cpus_total_str = node_data.get("CPUTot", "0")
            cpus_alloc_str = node_data.get("CPUAlloc", "0")
            try:
                cpus_total = int(cpus_total_str)
                cpus_alloc = int(cpus_alloc_str)
                stats.total_cpus += cpus_total
                stats.allocated_cpus += cpus_alloc
            except ValueError:
                pass

            # Parse memory (in MB, convert to GB)
            mem_total_str = node_data.get("RealMemory", "0")
            mem_alloc_str = node_data.get("AllocMem", "0")
            try:
                mem_total_mb = int(mem_total_str)
                mem_alloc_mb = int(mem_alloc_str)
                stats.total_memory_gb += mem_total_mb / 1024.0
                stats.allocated_memory_gb += mem_alloc_mb / 1024.0
            except ValueError:
                pass

            # Parse GPUs by type from CfgTRES and AllocTRES
            cfg_tres = node_data.get("CfgTRES", "")
            alloc_tres = node_data.get("AllocTRES", "")

            # Parse CfgTRES for total GPUs by type
            # Format: "gres/gpu=8,gres/gpu:h200=8" or "gres/gpu:a100:4"
            # Note: If both generic (gres/gpu=8) and specific (gres/gpu:h200=8) exist,
            # they represent the same GPUs, so we only count specific types to avoid double-counting
            gpu_total_pattern = re.compile(r"gres/gpu(?::([^=,]+))?=(\d+)", re.IGNORECASE)
            gpu_entries: list[tuple[str, int]] = []
            for match in gpu_total_pattern.finditer(cfg_tres):
                gpu_type = match.group(1) if match.group(1) else "gpu"
                try:
                    gpu_count = int(match.group(2))
                    gpu_entries.append((gpu_type, gpu_count))
                except ValueError:
                    pass

            # Check if we have specific types (non-generic)
            has_specific_types = any(gpu_type != "gpu" for gpu_type, _ in gpu_entries)

            # Process entries: only count specific types if they exist, otherwise count generic
            for gpu_type, gpu_count in gpu_entries:
                if has_specific_types and gpu_type == "gpu":
                    # Skip generic if we have specific types
                    continue
                current_total, current_alloc = stats.gpus_by_type.get(gpu_type, (0, 0))
                stats.gpus_by_type[gpu_type] = (current_total + gpu_count, current_alloc)
                stats.total_gpus += gpu_count

            # Parse AllocTRES for allocated GPUs by type
            alloc_entries: list[tuple[str, int]] = []
            for match in gpu_total_pattern.finditer(alloc_tres):
                gpu_type = match.group(1) if match.group(1) else "gpu"
                try:
                    gpu_count = int(match.group(2))
                    alloc_entries.append((gpu_type, gpu_count))
                except ValueError:
                    pass

            # Process allocated entries with same logic
            for gpu_type, gpu_count in alloc_entries:
                if has_specific_types and gpu_type == "gpu":
                    # Skip generic if we have specific types
                    continue
                current_total, current_alloc = stats.gpus_by_type.get(gpu_type, (0, 0))
                stats.gpus_by_type[gpu_type] = (current_total, current_alloc + gpu_count)
                stats.allocated_gpus += gpu_count

            # Fallback: if no TRES data, try parsing Gres field
            if not cfg_tres and not alloc_tres:
                gres = node_data.get("Gres", "")
                if "gpu:" in gres.lower():
                    # Try to extract GPU count and type from Gres field
                    # Format is usually like "gpu:4" or "gpu:a100:4"
                    gpu_match = re.search(r"gpu(?::([^:,]+))?:(\d+)", gres, re.IGNORECASE)
                    if gpu_match:
                        try:
                            gpu_type = gpu_match.group(1) if gpu_match.group(1) else "gpu"
                            gpu_count = int(gpu_match.group(2))
                            current_total, current_alloc = stats.gpus_by_type.get(gpu_type, (0, 0))
                            stats.gpus_by_type[gpu_type] = (current_total + gpu_count, current_alloc)
                            stats.total_gpus += gpu_count
                            # Estimate allocated GPUs (rough)
                            if "ALLOCATED" in state or "MIXED" in state:
                                current_total, current_alloc = stats.gpus_by_type.get(gpu_type, (0, 0))
                                stats.gpus_by_type[gpu_type] = (current_total, current_alloc + gpu_count)
                                stats.allocated_gpus += gpu_count
                        except ValueError:
                            pass

        return stats

    def _update_node_overview(self) -> None:
        """Update the node overview tab."""
        try:
            node_tab = self.query_one("#node-overview", NodeOverviewTab)
            node_infos = self._parse_node_infos()
            logger.debug(f"Updating node overview with {len(node_infos)} nodes")
            node_tab.update_nodes(node_infos)
        except Exception as exc:
            logger.error(f"Failed to update node overview: {exc}", exc_info=True)

    def _parse_node_infos(self) -> list[NodeInfo]:
        """Parse cluster node data into NodeInfo objects.

        Returns:
            List of NodeInfo objects.
        """
        node_infos: list[NodeInfo] = []

        for node_data in self._cluster_nodes:
            node_name = node_data.get("NodeName", "")
            state = node_data.get("State", "")
            partitions = node_data.get("Partitions", "")
            reason = node_data.get("Reason", "")

            # Parse CPUs
            cpus_total = int(node_data.get("CPUTot", "0") or "0")
            cpus_alloc = int(node_data.get("CPUAlloc", "0") or "0")

            # Parse memory (MB to GB)
            mem_total_mb = int(node_data.get("RealMemory", "0") or "0")
            mem_alloc_mb = int(node_data.get("AllocMem", "0") or "0")
            mem_total_gb = mem_total_mb / 1024.0
            mem_alloc_gb = mem_alloc_mb / 1024.0

            # Parse GPUs
            gpus_total = 0
            gpus_alloc = 0
            gres = node_data.get("Gres", "")
            if "gpu:" in gres.lower():
                gpu_match = re.search(r"gpu(?::[^:,]+)*:(\d+)", gres, re.IGNORECASE)
                if gpu_match:
                    try:
                        gpus_total = int(gpu_match.group(1))
                        if "ALLOCATED" in state.upper() or "MIXED" in state.upper():
                            gpus_alloc = gpus_total
                    except ValueError:
                        pass

            node_infos.append(
                NodeInfo(
                    name=node_name,
                    state=state,
                    cpus_alloc=cpus_alloc,
                    cpus_total=cpus_total,
                    memory_alloc_gb=mem_alloc_gb,
                    memory_total_gb=mem_total_gb,
                    gpus_alloc=gpus_alloc,
                    gpus_total=gpus_total,
                    partitions=partitions,
                    reason=reason,
                )
            )

        return node_infos

    def _update_user_overview(self) -> None:
        """Update the user overview tab."""
        try:
            user_tab = self.query_one("#user-overview", UserOverviewTab)
            user_stats = UserOverviewTab.aggregate_user_stats(self._all_users_jobs)
            logger.debug(f"Updating user overview with {len(user_stats)} users from {len(self._all_users_jobs)} jobs")
            user_tab.update_users(user_stats)
        except Exception as exc:
            logger.error(f"Failed to update user overview: {exc}", exc_info=True)

    def on_tab_switched(self, event: TabSwitched) -> None:
        """Handle tab switching events.

        Args:
            event: The TabSwitched event.
        """
        # Hide all tab contents
        for tab_id in ["tab-jobs-content", "tab-nodes-content", "tab-users-content"]:
            try:
                tab_content = self.query_one(f"#{tab_id}", Container)
                tab_content.display = False
            except Exception:
                pass

        # Show the active tab content
        active_tab_id = f"tab-{event.tab_name}-content"
        try:
            active_tab = self.query_one(f"#{active_tab_id}", Container)
            active_tab.display = True

            # Update the tab content if needed (always update when switching to ensure data is shown)
            if event.tab_name == "jobs":
                # Focus the jobs table to enable arrow key navigation
                try:
                    jobs_table = self.query_one("#jobs_table", DataTable)
                    jobs_table.focus()
                    logger.debug("Focused jobs table for arrow key navigation")
                except Exception as exc:
                    logger.debug(f"Failed to focus jobs table: {exc}")
            elif event.tab_name == "nodes":
                # Always update when switching to nodes tab
                self._update_node_overview()
            elif event.tab_name == "users":
                # Always update when switching to users tab
                self._update_user_overview()
        except Exception as exc:
            logger.warning(f"Failed to switch to tab {event.tab_name}: {exc}")

    def action_refresh(self) -> None:
        """Manual refresh action."""
        logger.info("Manual refresh triggered")
        self.notify("Refreshing...")
        self._start_refresh_worker()

    def action_switch_tab_jobs(self) -> None:
        """Switch to the Jobs tab."""
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            tab_container.switch_tab("jobs")
        except Exception as exc:
            logger.debug(f"Failed to switch to jobs tab: {exc}")

    def action_switch_tab_nodes(self) -> None:
        """Switch to the Nodes tab."""
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            tab_container.switch_tab("nodes")
        except Exception as exc:
            logger.debug(f"Failed to switch to nodes tab: {exc}")

    def action_switch_tab_users(self) -> None:
        """Switch to the Users tab."""
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            tab_container.switch_tab("users")
        except Exception as exc:
            logger.debug(f"Failed to switch to users tab: {exc}")

    def action_next_tab(self) -> None:
        """Switch to the next tab (cycling)."""
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            current_tab = tab_container.active_tab
            tab_order = ["jobs", "nodes", "users"]
            current_index = tab_order.index(current_tab)
            next_index = (current_index + 1) % len(tab_order)
            tab_container.switch_tab(tab_order[next_index])
        except Exception as exc:
            logger.debug(f"Failed to switch to next tab: {exc}")

    def action_previous_tab(self) -> None:
        """Switch to the previous tab (cycling)."""
        try:
            tab_container = self.query_one("TabContainer", TabContainer)
            current_tab = tab_container.active_tab
            tab_order = ["jobs", "nodes", "users"]
            current_index = tab_order.index(current_tab)
            previous_index = (current_index - 1) % len(tab_order)
            tab_container.switch_tab(tab_order[previous_index])
        except Exception as exc:
            logger.debug(f"Failed to switch to previous tab: {exc}")

    def on_key(self, event: Key) -> None:
        """Handle key events, intercepting Tab for tab navigation.

        Args:
            event: The key event.
        """
        # Intercept Tab for tab navigation (Shift+Tab is handled by binding)
        # Check if it's a plain tab (not shift+tab which comes through as binding)
        if event.key == "tab" and event.name == "tab":
            event.prevent_default()
            self.action_next_tab()

    def action_show_job_info(self) -> None:
        """Show job info dialog."""

        def handle_job_id(job_id: str | None) -> None:
            if job_id:
                logger.info(f"Looking up job info for {job_id}")
                job_info, error = get_job_info(job_id)
                stdout_path, stderr_path, _ = get_job_log_paths(job_id)
                self.push_screen(JobInfoScreen(job_id, job_info, error, stdout_path, stderr_path))

        self.push_screen(JobInputScreen(), handle_job_id)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection (Enter key) in DataTable.

        Args:
            event: The row selection event from the DataTable.
        """
        self._show_job_info_for_row(event.data_table, event.row_key)

    def _show_job_info_for_row(self, table: DataTable, row_key: RowKey) -> None:
        """Show job info for a specific row in a table.

        Args:
            table: The DataTable containing the row.
            row_key: The key of the row to show info for.
        """
        try:
            row_data = table.get_row(row_key)
            job_id = str(row_data[0]).strip()
            logger.info(f"Showing info for selected job {job_id}")
            job_info, error = get_job_info(job_id)
            stdout_path, stderr_path, _ = get_job_log_paths(job_id)
            self.push_screen(JobInfoScreen(job_id, job_info, error, stdout_path, stderr_path))
        except (IndexError, KeyError) as exc:
            logger.error(f"Could not get job ID from row {row_key}: {exc}")
            self.notify("Could not get job ID from selected row", severity="error")

    def action_show_selected_job_info(self) -> None:
        """Show job info for the currently selected row."""
        jobs_table = self.query_one("#jobs_table", DataTable)

        if jobs_table.row_count == 0:
            self.notify("No jobs to display", severity="warning")
            return

        cursor_row = jobs_table.cursor_row
        if cursor_row is None or cursor_row < 0:
            self.notify("No row selected", severity="warning")
            return

        try:
            row_data = jobs_table.get_row_at(cursor_row)
            job_id = str(row_data[0]).strip()
            logger.info(f"Showing info for selected job {job_id}")
            job_info, error = get_job_info(job_id)
            stdout_path, stderr_path, _ = get_job_log_paths(job_id)
            self.push_screen(JobInfoScreen(job_id, job_info, error, stdout_path, stderr_path))
        except (IndexError, KeyError):
            logger.error(f"Could not get job ID from row {cursor_row}")
            self.notify("Could not get job ID from selected row", severity="error")

    def action_cancel_job(self) -> None:
        """Cancel the selected job after confirmation."""
        jobs_table = self.query_one("#jobs_table", DataTable)

        if jobs_table.row_count == 0:
            self.notify("No jobs to cancel", severity="warning")
            return

        cursor_row = jobs_table.cursor_row
        if cursor_row is None or cursor_row < 0:
            self.notify("No job selected", severity="warning")
            return

        try:
            row_data = jobs_table.get_row_at(cursor_row)
            job_id = str(row_data[0]).strip()
            job_name = str(row_data[1]).strip() if len(row_data) > 1 else None

            # Check if job is active (can be cancelled)
            cached_job = self._job_cache.get_job_by_id(job_id)
            if cached_job and not cached_job.is_active:
                self.notify("Cannot cancel completed job", severity="warning")
                return

            def handle_confirmation(confirmed: bool | None) -> None:
                if confirmed is True:
                    success, error = cancel_job(job_id)
                    if success:
                        logger.info(f"Successfully cancelled job {job_id}")
                        self.notify(f"Job {job_id} cancelled", severity="information")
                        self._start_refresh_worker()  # Refresh to update state
                    else:
                        logger.error(f"Failed to cancel job {job_id}: {error}")
                        self.notify(f"Failed to cancel: {error}", severity="error")

            self.push_screen(CancelConfirmScreen(job_id, job_name), handle_confirmation)

        except (IndexError, KeyError) as exc:
            logger.error(f"Could not get job ID from row {cursor_row}: {exc}")
            self.notify("Could not get job ID from selected row", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: The button press event.
        """
        if event.button.id == "cancel-job-btn":
            self.action_cancel_job()

    async def action_quit(self) -> None:
        """Quit the application."""
        logger.info("Quitting application")
        if self.auto_refresh_timer:
            self.auto_refresh_timer.stop()
        # Clean up log sink
        if self._log_sink_id is not None:
            remove_tui_sink(self._log_sink_id)
            self._log_sink_id = None
        self.exit()


def main() -> None:
    """Run the SLURM monitor TUI app."""
    logger.info("Starting stoei")
    app = SlurmMonitor()
    app.run()
    logger.info("Stoei exited")
