"""Data-refresh orchestration for the SLURM monitor.

This module owns the fluidity-critical refresh core: the two-tier fast/slow
refresh loops, the step-by-step initial load, the parallel fetch helpers, and
the result-application logic that rebuilds the shared job cache and pushes
partial UI updates. It collaborates with the main app through a small
:class:`_RefreshHost` protocol so it can drive workers, schedule UI callbacks,
read and write the shared refresh state, and call SLURM commands without
importing the concrete ``SlurmMonitor`` app (which would create an import
cycle, since the app imports this module).

The SLURM command functions are reached through the host protocol rather than
imported directly here so that they resolve in the ``stoei.app`` module
namespace at call time — preserving the existing behaviour (and tests that
patch ``stoei.app.get_*``) exactly.
"""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Protocol, TypeAlias, cast

import loguru
from textual.notifications import SeverityLevel
from textual.timer import Timer
from textual.worker import Worker, WorkerState

from stoei.cluster_stats import ClusterStats
from stoei.settings import Settings
from stoei.slurm.array_parser import normalize_array_job_id
from stoei.slurm.cache import JobCache
from stoei.table_controller import TableController

# Type aliases for fetch result types used in apply_fetch_result.
_HistoryResult: TypeAlias = tuple[list[tuple[str, ...]] | None, int, int, int]
_PriorityHalfResult: TypeAlias = tuple[list[tuple[str, ...]], str | None]
_EnergyResult: TypeAlias = tuple[list[tuple[str, ...]], bool]
_FetchResult: TypeAlias = (
    _HistoryResult | list[dict[str, str]] | list[tuple[str, ...]] | _PriorityHalfResult | _EnergyResult
)

# The heavy data loop (history, nodes, all-users jobs, wait times, priority) refreshes
# at this multiple of the base refresh interval. Slow sacct/sshare/sprio calls then never
# gate the fast running-jobs loop that drives the jobs-table "Time" column.
HEAVY_REFRESH_MULTIPLIER = 4

# Number of independent priority fetch futures (fair_share + job_priority).
# The priority tab is updated once both halves have arrived in the same cycle.
_PRIORITY_FETCH_COUNT = 2


class _RefreshHost(Protocol):
    """Minimal surface the :class:`RefreshController` needs from the app.

    Declares only the attributes and methods the controller touches so the
    controller stays decoupled from the concrete ``SlurmMonitor`` app and no
    import cycle is introduced. The surface is large because the refresh state
    is shared with the app and the other controllers; every member is read or
    written through this protocol.
    """

    # --- Settings and identity ---
    _settings: Settings
    # The app's module-level logger; the controller logs through it so refresh
    # log records keep the ``stoei.app`` identity they had before this move.
    logger: "loguru.Logger"

    # --- Refresh timers / workers / cadence state ---
    refresh_interval: float
    auto_refresh_timer: Timer | None
    heavy_refresh_timer: Timer | None
    _refresh_worker: Worker[None] | None
    _running_refresh_worker: Worker[None] | None
    _refresh_state_lock: Lock
    _job_cache: JobCache
    _last_running_jobs: list[tuple[str, ...]]
    _last_history_jobs: list[tuple[str, ...]]
    _last_history_stats: tuple[int, int, int]

    # --- Initial-load state ---
    _precomputed_job_rows: list[tuple[str, ...]]
    _initial_background_complete: bool

    # --- Shared caches the refresh flow writes ---
    _cluster_nodes: list[dict[str, str]]
    _all_users_jobs: list[tuple[str, ...]]
    _wait_time_jobs: list[tuple[str, ...]]
    _energy_history_jobs: list[tuple[str, ...]]
    _energy_data_loaded: bool
    _fair_share_entries: list[tuple[str, ...]]
    _job_priority_entries: list[tuple[str, ...]]
    _cached_node_infos: list  # list[NodeInfo]; widget type kept opaque here
    _cached_cluster_stats: ClusterStats | None
    _cached_energy_user_stats: list  # list[UserEnergyStats]
    _job_info_cache: dict[str, tuple[str, str | None, str | None, str | None]]

    # --- Priority half-cycle bookkeeping and error de-dup ---
    _priority_halves_received: int
    _error_notified: dict[str, bool]

    @property
    def heavy_refresh_interval(self) -> float:
        """Interval (seconds) for the heavy data loop."""
        ...

    # --- Textual App surface used by the controller ---
    def run_worker(
        self,
        work: Callable[[], object],
        *,
        name: str = ...,
        group: str = ...,
        exclusive: bool = ...,
        thread: bool = ...,
    ) -> Worker[None]:
        """Run *work* in a background worker."""
        ...

    def set_interval(self, interval: float, callback: Callable[[], object]) -> Timer:
        """Schedule *callback* to run every *interval* seconds."""
        ...

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

    def _post_ui_callback(self, callback: Callable[[], object]) -> None:
        """Schedule *callback* on the main thread without blocking the caller."""
        ...

    def _current_worker(self) -> Worker[object]:
        """Return the worker running the current task/thread."""
        ...

    # --- Loading-screen step bridges (stay on the app) ---
    def _loading_update_step(self, idx: int) -> None:
        """Mark a loading step as started."""
        ...

    def _loading_complete_step(self, idx: int, msg: str | None = ...) -> None:
        """Mark a loading step as completed."""
        ...

    def _loading_fail_step(self, idx: int, error: str) -> None:
        """Mark a loading step as failed."""
        ...

    def _show_slurm_error(self) -> None:
        """Show the SLURM-unavailable error screen."""
        ...

    def _finish_initial_load(self) -> None:
        """Populate the jobs table and start background loading (main thread)."""
        ...

    # --- UI-update / cache-compute helpers that stay on the app ---
    def _set_loading_indicator(self, active: bool) -> None:
        """Toggle the global loading indicator."""
        ...

    def _update_nodes_tab_only(self) -> None:
        """Update the node overview tab only."""
        ...

    def _update_all_jobs_widgets(self) -> None:
        """Update user overview and My Usage banner."""
        ...

    def _update_priority_tab(self) -> None:
        """Update the priority overview tab."""
        ...

    def _update_energy_tab(self) -> None:
        """Update the energy subtab in user overview."""
        ...

    def _parse_node_infos(self) -> list:
        """Parse cached cluster node data into NodeInfo objects."""
        ...

    def _calculate_cluster_stats(self) -> ClusterStats:
        """Compute cluster stats from cached node/job data."""
        ...

    def _compute_user_overview_cache(self) -> None:
        """Pre-compute user overview data from cached SLURM results."""
        ...

    def _compute_priority_overview_cache(self) -> None:
        """Pre-compute priority overview data from cached SLURM results."""
        ...

    def aggregate_energy_stats(self, energy_jobs: list[tuple[str, ...]]) -> list:
        """Aggregate energy history rows into per-user stats."""
        ...

    # --- SLURM command bridges (resolve in stoei.app namespace at call time) ---
    def _slurm_check_available(self) -> tuple[bool, str | None]:
        """Check SLURM controller availability."""
        ...

    def _slurm_running_jobs(self, *, max_retries: int) -> tuple[list[tuple[str, ...]], str | None]:
        """Fetch the current user's running/pending jobs (squeue)."""
        ...

    def _slurm_job_history(
        self, *, days: int, max_retries: int = ...
    ) -> tuple[list[tuple[str, ...]], int, int, int, str | None]:
        """Fetch the current user's job history (sacct)."""
        ...

    def _slurm_cluster_nodes(self) -> tuple[list[dict[str, str]], str | None]:
        """Fetch cluster node data (scontrol)."""
        ...

    def _slurm_all_running_jobs(self) -> tuple[list[tuple[str, ...]], str | None]:
        """Fetch all users' running jobs (squeue)."""
        ...

    def _slurm_wait_time_history(self, *, hours: int) -> tuple[list[tuple[str, ...]], str | None]:
        """Fetch wait-time history (sacct)."""
        ...

    def _slurm_energy_history(self, months: int) -> tuple[list[tuple[str, ...]], str | None]:
        """Fetch energy history (sacct)."""
        ...

    def _slurm_fair_share_priority(self, *, max_retries: int) -> tuple[list[tuple[str, ...]], str | None]:
        """Fetch fair-share priority data (sshare)."""
        ...

    def _slurm_pending_job_priority(self, *, max_retries: int) -> tuple[list[tuple[str, ...]], str | None]:
        """Fetch pending-job priority data (sprio)."""
        ...


class RefreshController:
    """Owns the data-refresh orchestration for the SLURM monitor.

    The controller drives the fast running-jobs loop and the slow heavy loop,
    performs the step-by-step initial load, fetches all data sources in
    parallel, and applies each result back into the shared state on the host
    app via the :class:`_RefreshHost` protocol.
    """

    def __init__(self, host: _RefreshHost, tables: TableController) -> None:
        """Initialise the controller.

        Args:
            host: The app whose refresh state the controller orchestrates.
            tables: The table controller that renders the jobs table, sidebar,
                and overview widgets the refresh flow pushes results into.
        """
        self._host = host
        self._tables = tables

    # --- Worker starters ---

    def start_initial_load_worker(self) -> None:
        """Start background worker for initial step-by-step data load."""
        self._host._refresh_worker = self._host.run_worker(
            self.initial_load_async,
            name="initial_load",
            group="data_load",
            exclusive=True,
            thread=True,
        )

    def start_refresh_worker(self) -> None:
        """Start the heavy background worker (history, nodes, all-users jobs, priority)."""
        if self._host._refresh_worker is not None and self._host._refresh_worker.state == WorkerState.RUNNING:
            self._host.logger.debug("Heavy refresh worker already running, skipping")
            return

        self._host._refresh_worker = self._host.run_worker(
            self.refresh_data_async,
            name="refresh_data",
            group="data_load",
            exclusive=True,
            thread=True,
        )

    def start_running_refresh_worker(self) -> None:
        """Start the fast worker that refreshes running jobs (drives the jobs-table Time column).

        This loop fetches ``squeue`` only, so it is never gated by the slow
        ``sacct``/``sshare``/``sprio`` calls in the heavy loop.
        """
        if (
            self._host._running_refresh_worker is not None
            and self._host._running_refresh_worker.state == WorkerState.RUNNING
        ):
            self._host.logger.debug("Running-jobs refresh worker already running, skipping")
            return

        self._host._running_refresh_worker = self._host.run_worker(
            self.refresh_running_jobs_async,
            name="refresh_running_jobs",
            group="running_refresh",
            exclusive=True,
            thread=True,
        )

    # --- Initial load ---

    def initial_load_async(self) -> None:
        """Perform initial data load with step-by-step progress (runs in worker thread)."""
        self._host.logger.info("Starting initial data load")

        # Execute loading steps and collect results
        load_result = self._execute_loading_steps()
        if load_result is None:
            return  # SLURM error, already handled

        running_jobs, history_jobs, total_jobs, total_requeues, max_requeues = load_result

        # Save initial snapshots so each refresh loop can rebuild the table from
        # the other loop's last-known data without re-fetching it.
        self._host._last_running_jobs = running_jobs
        self._host._last_history_jobs = history_jobs
        self._host._last_history_stats = (total_jobs, total_requeues, max_requeues)

        # Build job cache from fetched data
        self._host._loading_update_step(2)
        self._host._job_cache._build_from_data(running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)

        # Pre-compute row tuples in the worker thread so the main thread
        # only needs to push them into the DataTable (the unavoidable DOM work).
        jobs = self._tables.sorted_jobs_for_display(self._host._job_cache.jobs)
        self._host._precomputed_job_rows = [tuple(self._tables.job_row_values(job)) for job in jobs]

        self._host._loading_complete_step(2, "Ready")

        # Transition to main UI — the loading screen stays up until the
        # first background refresh (cluster data) completes.
        self._host._post_ui_callback(self._host._finish_initial_load)

    def _execute_loading_steps(
        self,
    ) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]], int, int, int] | None:
        """Execute critical loading steps and return collected data.

        Only loads the minimum data needed for the jobs table (SLURM check,
        running jobs, job history). All other data sources (cluster nodes,
        all-users jobs, energy, wait times, priority) are loaded in the
        background after the UI is shown.

        Returns:
            Tuple of (running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)
            or None if SLURM is not available.
        """
        # Step 0: Check SLURM availability
        if not self._load_step_check_slurm():
            return None

        # Step 1: Fetch running jobs + job history in parallel (no retries)
        running_jobs, history_jobs, total_jobs, total_requeues, max_requeues = self._load_step_user_jobs()

        return running_jobs, history_jobs, total_jobs, total_requeues, max_requeues

    def _load_step_check_slurm(self) -> bool:
        """Execute step 0: Check SLURM availability."""
        self._host._loading_update_step(0)
        is_available, error_msg = self._host._slurm_check_available()
        if not is_available:
            self._host._loading_fail_step(0, error_msg or "SLURM not available")
            self._host.logger.error(f"SLURM not available: {error_msg}")
            self._host._post_ui_callback(self._host._show_slurm_error)
            return False
        self._host._loading_complete_step(0, "SLURM available")
        return True

    def _load_step_user_jobs(
        self,
    ) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]], int, int, int]:
        """Execute step 1: Fetch running jobs and job history in parallel (no retries)."""
        self._host._loading_update_step(1)
        job_history_days = self._host._settings.job_history_days

        running_jobs: list[tuple[str, ...]] = []
        history_jobs: list[tuple[str, ...]] = []
        total_jobs = 0
        total_requeues = 0
        max_requeues = 0
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_running = executor.submit(self._host._slurm_running_jobs, max_retries=0)
            future_history = executor.submit(self._host._slurm_job_history, days=job_history_days, max_retries=0)

            rj, rj_error = future_running.result()
            if rj_error:
                self._host.logger.warning(f"Failed to get running jobs: {rj_error}")
                errors.append(rj_error)
            else:
                running_jobs = rj

            hj, tj, tr, mr, hj_error = future_history.result()
            if hj_error:
                self._host.logger.warning(f"Failed to get job history: {hj_error}")
                errors.append(hj_error)
            else:
                history_jobs = hj
                total_jobs = tj
                total_requeues = tr
                max_requeues = mr

        if errors:
            self._host._loading_fail_step(1, "; ".join(errors))
        else:
            self._host._loading_complete_step(
                1, f"{len(running_jobs)} running/pending, {total_jobs} in {job_history_days}d"
            )

        return running_jobs, history_jobs, total_jobs, total_requeues, max_requeues

    # --- Fast running-jobs loop ---

    def refresh_running_jobs_async(self) -> None:
        """Fetch running jobs (squeue only) and refresh the jobs table (worker thread)."""
        worker = self._host._current_worker()
        running_jobs, error = self._host._slurm_running_jobs(max_retries=1)
        if worker.is_cancelled:
            return
        if error:
            self._host.logger.warning(f"Failed to refresh running jobs: {error}")
            self.apply_running_jobs_result(None)
        else:
            self.apply_running_jobs_result(running_jobs)

    def apply_running_jobs_result(self, running_jobs: list[tuple[str, ...]] | None) -> None:
        """Rebuild the jobs table from fresh running jobs + cached history (worker thread).

        On a fetch failure (``running_jobs is None``) the previous table is kept
        and the user is notified once. On success the running-jobs snapshot is
        updated and the table is rebuilt against the last-known history snapshot,
        so the "Time" column advances without waiting on the heavy history loop.

        Args:
            running_jobs: Fresh squeue job tuples, or None if the fetch failed.
        """
        if running_jobs is None:
            if not self._host._error_notified.get("running_jobs"):
                self._host._error_notified["running_jobs"] = True
                self._host._post_ui_callback(
                    lambda: self._host.notify("Running jobs refresh failed - keeping old data", severity="warning")
                )
            return

        self._host._error_notified["running_jobs"] = False
        with self._host._refresh_state_lock:
            self._host._last_running_jobs = running_jobs
            old_states = self._job_states()
            total_jobs, total_requeues, max_requeues = self._host._last_history_stats
            self._host._job_cache._build_from_data(
                running_jobs, self._host._last_history_jobs, total_jobs, total_requeues, max_requeues
            )
            self._notify_new_jobs(set(old_states))
            self._invalidate_changed_job_info(old_states)
            job_rows = self._current_job_rows()
        self._host._post_ui_callback(lambda: self._tables.update_jobs_table(job_rows))

    def _current_job_rows(self) -> list[tuple[str, ...]]:
        """Snapshot the cached jobs as display-ready table rows."""
        return [
            tuple(self._tables.job_row_values(job))
            for job in self._tables.sorted_jobs_for_display(self._host._job_cache.jobs)
        ]

    # --- Parallel fetch helpers (run inside ThreadPoolExecutor threads) ---

    def _fetch_history(self) -> _HistoryResult:
        """Fetch the user's job history (sacct) for the heavy refresh loop.

        Returns:
            Tuple of (history_jobs, total_jobs, total_requeues, max_requeues).
            ``history_jobs`` is None if the fetch failed.
        """
        history_raw, total_jobs, total_requeues, max_requeues, h_error = self._host._slurm_job_history(
            days=self._host._settings.job_history_days
        )
        if h_error:
            self._host.logger.warning(f"Failed to refresh job history: {h_error}")
            return None, 0, 0, 0
        return history_raw, total_jobs, total_requeues, max_requeues

    def _fetch_nodes(self) -> list[dict[str, str]]:
        """Fetch cluster node data.

        Returns:
            List of node data dicts, empty on error.
        """
        nodes, error = self._host._slurm_cluster_nodes()
        if error:
            self._host.logger.warning(f"Failed to get cluster nodes: {error}")
            return []
        self._host.logger.debug(f"Fetched {len(nodes)} cluster nodes")
        return nodes

    def _fetch_all_jobs(self) -> list[tuple[str, ...]]:
        """Fetch all-users running job data.

        Returns:
            List of job tuples, empty on error.
        """
        all_jobs, error = self._host._slurm_all_running_jobs()
        if error:
            self._host.logger.warning(f"Failed to get all running jobs: {error}")
            return []
        self._host.logger.debug(f"Fetched {len(all_jobs)} running jobs from all users")
        return all_jobs

    def _fetch_wait_time(self) -> list[tuple[str, ...]]:
        """Fetch wait-time history.

        Returns:
            List of wait-time job tuples, empty on error.
        """
        wait_time_jobs, error = self._host._slurm_wait_time_history(hours=1)
        if error:
            self._host.logger.warning(f"Failed to get wait time history: {error}")
            return []
        self._host.logger.debug(f"Fetched {len(wait_time_jobs)} jobs for wait time calculation")
        return wait_time_jobs

    def _fetch_energy(self) -> tuple[list[tuple[str, ...]], bool]:
        """Fetch energy history data (only used during first background cycle).

        Returns:
            Tuple of (energy_jobs, energy_loaded).
        """
        if not self._host._settings.energy_loading_enabled:
            self._host.logger.debug("Energy loading disabled, skipping")
            return [], False

        months = self._host._settings.energy_history_months
        energy_jobs, error = self._host._slurm_energy_history(months)
        if error:
            self._host.logger.warning(f"Failed to get {months}-month energy history: {error}")
            return [], False
        self._host.logger.debug(f"Fetched {len(energy_jobs)} energy history jobs")
        return energy_jobs, True

    # --- Main refresh worker ---

    def refresh_data_async(self) -> None:
        """Parallel refresh of SLURM data (runs in background worker thread).

        Fetches all data sources concurrently. Each fetch result is processed
        and pushed to the UI as soon as it arrives (progressive rendering),
        so widgets update incrementally rather than waiting for all fetches.
        """
        is_first_cycle = not self._host._initial_background_complete
        self._host.logger.debug(f"Background refresh starting (parallel, first_cycle={is_first_cycle})")
        self._host._post_ui_callback(lambda: self._host._set_loading_indicator(True))
        worker = self._host._current_worker()

        try:
            max_workers = 7 if is_first_cycle else 6
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures: dict[Future[object], str] = {
                    pool.submit(self._fetch_history): "history",
                    pool.submit(self._fetch_nodes): "nodes",
                    pool.submit(self._fetch_all_jobs): "all_jobs",
                    pool.submit(self._fetch_wait_time): "wait_time",
                    pool.submit(self._host._slurm_fair_share_priority, max_retries=1): "fair_share",
                    pool.submit(self._host._slurm_pending_job_priority, max_retries=1): "job_priority",
                }
                if is_first_cycle:
                    futures[pool.submit(self._fetch_energy)] = "energy"

                for future in as_completed(futures):
                    if worker.is_cancelled:
                        self._host.logger.debug("Refresh worker cancelled, aborting")
                        return
                    label = futures[future]
                    try:
                        result = cast(_FetchResult, future.result())
                        self.apply_fetch_result(label, result)
                    except Exception:
                        self._host.logger.exception(f"Failed to fetch {label}")

            if worker.is_cancelled:
                return
            self._host._post_ui_callback(lambda: self.on_refresh_complete(is_first_cycle))

        except Exception:
            self._host.logger.exception("Error during parallel refresh")
        finally:
            self._host._post_ui_callback(lambda: self._host._set_loading_indicator(False))

    def apply_fetch_result(self, label: str, result: _FetchResult) -> None:  # noqa: PLR0912, PLR0915
        """Process one completed fetch and push a partial UI update (worker thread).

        Called in the background worker thread as each data source completes.
        Updates shared state and schedules targeted main-thread UI updates.

        Args:
            label: Fetch label identifying the data source.
            result: The data returned by the fetch function.
        """
        if label == "history":
            history_jobs, total_jobs, total_requeues, max_requeues = cast(_HistoryResult, result)
            with self._host._refresh_state_lock:
                old_states = self._job_states()
                self.handle_refresh_fallback(
                    self._host._last_running_jobs, history_jobs, total_jobs, total_requeues, max_requeues
                )
                self._invalidate_changed_job_info(old_states)
                job_rows = self._current_job_rows()
            self._host._post_ui_callback(lambda: self._tables.update_jobs_table(job_rows))

        elif label == "nodes":
            self._host._cluster_nodes = cast(list[dict[str, str]], result)
            self._host._cached_node_infos = self._host._parse_node_infos()
            self._host._post_ui_callback(self._host._update_nodes_tab_only)

        elif label == "all_jobs":
            self._host._all_users_jobs = cast(list[tuple[str, ...]], result)
            self._host._compute_user_overview_cache()
            self._host._post_ui_callback(self._host._update_all_jobs_widgets)

        elif label == "wait_time":
            self._host._wait_time_jobs = cast(list[tuple[str, ...]], result)
            stats = self._host._calculate_cluster_stats()
            self._host._cached_cluster_stats = stats
            self._host._post_ui_callback(lambda s=stats: self._tables.update_cluster_sidebar_with_stats(s))

        elif label == "fair_share":
            entries, error = cast(_PriorityHalfResult, result)
            if error:
                self._host.logger.warning(f"sshare failed: {error}")
            else:
                self._host._fair_share_entries = entries
            # Only trigger priority tab update once both halves have arrived
            self._host._priority_halves_received += 1
            if self._host._priority_halves_received >= _PRIORITY_FETCH_COUNT:
                self._host._priority_halves_received = 0
                self._host._compute_priority_overview_cache()
                self._host._post_ui_callback(self._host._update_priority_tab)

        elif label == "job_priority":
            entries, error = cast(_PriorityHalfResult, result)
            if error:
                self._host.logger.warning(f"sprio failed: {error}")
            else:
                self._host._job_priority_entries = entries
            self._host._priority_halves_received += 1
            if self._host._priority_halves_received >= _PRIORITY_FETCH_COUNT:
                self._host._priority_halves_received = 0
                self._host._compute_priority_overview_cache()
                self._host._post_ui_callback(self._host._update_priority_tab)

        elif label == "energy":
            energy_jobs, energy_loaded = cast(_EnergyResult, result)
            self._host._energy_history_jobs = energy_jobs
            self._host._energy_data_loaded = energy_loaded
            if energy_loaded:
                self._host._cached_energy_user_stats = self._host.aggregate_energy_stats(energy_jobs)
                self._host._post_ui_callback(self._host._update_energy_tab)

        else:
            self._host.logger.warning(f"_apply_fetch_result: unknown label {label!r}")

    def on_refresh_complete(self, is_first_cycle: bool) -> None:
        """Handle post-refresh bookkeeping (main thread only).

        On the first cycle this starts the recurring heavy-refresh timer and
        notifies the user that all cluster data has been loaded. The fast
        running-jobs timer is already started in :meth:`_finish_initial_load`.

        Args:
            is_first_cycle: Whether this was the first background refresh cycle.
        """
        if is_first_cycle:
            self._host._initial_background_complete = True
            self._host.heavy_refresh_timer = self._host.set_interval(
                self._host.heavy_refresh_interval, self.start_refresh_worker
            )
            self._host.notify("Cluster data ready", timeout=3, severity="information")
            self._host.logger.info(
                f"Background initial load complete. Running-jobs refresh every {self._host.refresh_interval}s, "
                f"heavy refresh every {self._host.heavy_refresh_interval}s"
            )
        else:
            self._host.logger.debug("Heavy refresh cycle complete - all data sources updated")

    def handle_refresh_fallback(
        self,
        running_jobs: list[tuple[str, ...]],
        history_jobs: list[tuple[str, ...]] | None,
        total_jobs: int,
        total_requeues: int,
        max_requeues: int,
    ) -> None:
        """Handle refresh logic with fallback for failed history.

        Args:
            running_jobs: List of running jobs tuples.
            history_jobs: List of history jobs tuples (or None if failed).
            total_jobs: Total job count from history.
            total_requeues: Total requeues from history.
            max_requeues: Max requeues from history.
        """
        if history_jobs is None:
            # Reuse last successful history
            history_jobs = list(self._host._last_history_jobs)
            total_jobs, total_requeues, max_requeues = self._host._last_history_stats
            if not self._host._error_notified.get("history_jobs"):
                self._host._error_notified["history_jobs"] = True
                self._host._post_ui_callback(
                    lambda: self._host.notify("History refresh failed - using cached history", severity="warning")
                )
        else:
            # Update cache of raw history data on success
            self._host._error_notified["history_jobs"] = False
            self._host._last_history_jobs = history_jobs
            self._host._last_history_stats = (total_jobs, total_requeues, max_requeues)

        self._host._job_cache._build_from_data(running_jobs, history_jobs, total_jobs, total_requeues, max_requeues)

    def _notify_new_jobs(self, old_job_ids: set[str]) -> None:
        """Post a notification if new jobs appeared in the cache after a refresh.

        Compares the current cache contents against *old_job_ids* (captured
        before the cache was rebuilt) and notifies the user about any newly
        detected active (running/pending) jobs.

        Args:
            old_job_ids: Set of job IDs that were in the cache before the refresh.
        """
        if not old_job_ids:
            return  # First load — don't notify for initial data
        new_active_jobs = [j for j in self._host._job_cache.jobs if j.job_id not in old_job_ids and j.is_active]
        if not new_active_jobs:
            return
        if len(new_active_jobs) == 1:
            job = new_active_jobs[0]
            msg = f"New job detected: {job.job_id} ({job.name})"
        else:
            msg = f"{len(new_active_jobs)} new jobs detected"
        self._host._post_ui_callback(lambda m=msg: self._host.notify(m, timeout=5, severity="information"))

    def _job_states(self) -> dict[str, str]:
        """Return a snapshot mapping each cached job's ID to its current state."""
        return {job.job_id: job.state for job in self._host._job_cache.jobs}

    def _invalidate_changed_job_info(self, old_states: dict[str, str]) -> None:
        """Evict cached modal job-info for jobs whose state changed (worker thread).

        Compares each job's state before and after the cache rebuild. Any job
        whose state changed - or that disappeared from the cache - has its cached
        ``scontrol``/``sacct`` detail evicted so the next modal open re-fetches
        it; unchanged jobs keep their cached entry for instant display. Eviction
        is conservative: array tasks that share a normalized cache key are
        evicted together when any one of them changes.

        Called from ``apply_fetch_result`` right after the cache rebuild, so the
        modal cache stays consistent with the table cache it was derived from
        instead of being gated behind full-cycle completion.

        Args:
            old_states: Job-ID-to-state snapshot captured before the rebuild.
        """
        new_states = self._job_states()
        for job_id, old_state in old_states.items():
            if new_states.get(job_id) != old_state:
                self._host._job_info_cache.pop(normalize_array_job_id(job_id), None)
