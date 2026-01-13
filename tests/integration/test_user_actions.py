"""Integration tests covering user flows and crash logging."""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from stoei.app import SlurmMonitor
from stoei.slurm.cache import JobCache
from stoei.widgets.tabs import TabContainer

RUNNING_JOBS: list[tuple[str, ...]] = [
    ("101", "train", "RUNNING", "00:10:00", "1", "node001"),
]

HISTORY_JOBS: list[tuple[str, ...]] = [
    ("201", "completed", "COMPLETED", "0", "00:30:00", "0:0", "node002"),
]

ALL_RUNNING_JOBS: list[tuple[str, ...]] = [
    ("101", "train", "user1", "gpu", "RUNNING", "00:10:00", "1", "node001", "cpu=4,mem=32G,gres/gpu:h100=1"),
]

NODE_DATA: list[dict[str, str]] = [
    {
        "NodeName": "node001",
        "State": "IDLE",
        "Partitions": "gpu",
        "CPUTot": "64",
        "CPUAlloc": "8",
        "RealMemory": "256000",
        "AllocMem": "64000",
        "CfgTRES": "cpu=64,mem=256000,gres/gpu:h100=4",
        "AllocTRES": "cpu=8,mem=64000,gres/gpu:h100=1",
        "Gres": "gpu:h100:4",
    },
]


@pytest.fixture
def slurm_monitor_factory(monkeypatch: pytest.MonkeyPatch) -> Callable[[], SlurmMonitor]:
    """Return a factory that creates a SlurmMonitor with fast fake data."""

    def fake_check() -> tuple[bool, str | None]:
        return True, None

    def fake_nodes() -> tuple[list[dict[str, str]], str | None]:
        return ([dict(node) for node in NODE_DATA], None)

    def fake_running() -> tuple[list[tuple[str, ...]], str | None]:
        return ([tuple(job) for job in RUNNING_JOBS], None)

    def fake_history(*_args, **_kwargs) -> tuple[list[tuple[str, ...]], int, int, int, str | None]:
        history_copy = [tuple(job) for job in HISTORY_JOBS]
        return history_copy, len(history_copy), 0, 0, None

    def fake_all_running() -> tuple[list[tuple[str, ...]], str | None]:
        return ([tuple(job) for job in ALL_RUNNING_JOBS], None)

    monkeypatch.setattr("stoei.app.check_slurm_available", fake_check)
    monkeypatch.setattr("stoei.app.get_cluster_nodes", fake_nodes)
    monkeypatch.setattr("stoei.app.get_running_jobs", fake_running)
    monkeypatch.setattr("stoei.app.get_job_history", fake_history)
    monkeypatch.setattr("stoei.app.get_all_running_jobs", fake_all_running)

    def factory() -> SlurmMonitor:
        JobCache.reset()
        app = SlurmMonitor()

        def _noop_interval(*_args, **_kwargs) -> None:
            return None

        app.set_interval = _noop_interval  # type: ignore[assignment]
        return app

    return factory


@pytest.mark.asyncio
async def test_tab_shortcuts_cycle_views(slurm_monitor_factory: Callable[[], SlurmMonitor]) -> None:
    """Ensure number keys switch tab focus like a user would expect."""
    app = slurm_monitor_factory()

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        tab_container = app.query_one("#tab-container", TabContainer)
        assert tab_container.active_tab == "jobs"

        await pilot.press("2")
        assert tab_container.active_tab == "nodes"

        await pilot.press("3")
        assert tab_container.active_tab == "users"

        await pilot.press("4")
        assert tab_container.active_tab == "logs"

        await pilot.press("1")
        assert tab_container.active_tab == "jobs"


@pytest.mark.asyncio
async def test_manual_refresh_triggers_worker(slurm_monitor_factory: Callable[[], SlurmMonitor]) -> None:
    """Pressing 'r' should invoke refresh logic through the binding."""
    app = slurm_monitor_factory()
    refresh_calls: list[str] = []

    def fake_refresh() -> None:
        refresh_calls.append("called")

    app._start_refresh_worker = fake_refresh  # type: ignore[assignment]

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("r")

    assert refresh_calls == ["called"]


def test_cli_logs_uncaught_exceptions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the CLI writes failures to the logs directory."""
    import stoei.__main__ as cli_module
    import stoei.logger as logger_module

    original_log_dir = os.environ.get("STOEI_LOG_DIR")
    os.environ["STOEI_LOG_DIR"] = str(tmp_path)
    logger_module = importlib.reload(logger_module)
    cli_module = importlib.reload(cli_module)

    def blow_up() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_module, "main", blow_up)
    monkeypatch.setattr(cli_module.sys, "argv", ["stoei"])

    try:
        with pytest.raises(SystemExit):
            cli_module.run()

        log_files = sorted(tmp_path.glob("stoei_*.log"))
        assert log_files, "expected log file to be written"
        contents = log_files[0].read_text()
        assert "Unhandled exception while running stoei" in contents
        assert "RuntimeError: boom" in contents
    finally:
        if original_log_dir is None:
            os.environ.pop("STOEI_LOG_DIR", None)
        else:
            os.environ["STOEI_LOG_DIR"] = original_log_dir
        importlib.reload(logger_module)
        importlib.reload(cli_module)
