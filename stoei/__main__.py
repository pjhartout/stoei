"""Entry point for stoei."""

import argparse
import os
import sys
import traceback
from importlib.metadata import version

from stoei.app import REFRESH_INTERVAL, main
from stoei.logger import get_logger

logger = get_logger(__name__)


ENV_REFRESH_INTERVAL = "STOEI_REFRESH_INTERVAL"


def positive_float(value: str) -> float:
    """Convert a CLI string to a positive float.

    Args:
        value: The string representation of the float value.

    Returns:
        The parsed float.

    Raises:
        argparse.ArgumentTypeError: If the value cannot be parsed or is not positive.
    """
    try:
        interval = float(value)
    except ValueError as exc:
        msg = f"Invalid refresh interval '{value}'. Please provide a positive number."
        raise argparse.ArgumentTypeError(msg) from exc
    if interval <= 0:
        msg = "Refresh interval must be greater than 0."
        raise argparse.ArgumentTypeError(msg)
    return interval


def _get_env_refresh_interval() -> float | None:
    """Fetch a refresh interval override from environment variables."""
    value = os.environ.get(ENV_REFRESH_INTERVAL)
    if value is None:
        return None
    try:
        return positive_float(value)
    except argparse.ArgumentTypeError as exc:
        logger.warning(f"Ignoring invalid {ENV_REFRESH_INTERVAL} value '{value}': {exc}")
    return None


def resolve_refresh_interval(cli_value: float | None) -> float:
    """Resolve the refresh interval from CLI or environment overrides.

    Args:
        cli_value: Optional CLI-provided interval value.

    Returns:
        A valid refresh interval in seconds.
    """
    if cli_value is not None:
        return cli_value
    env_value = _get_env_refresh_interval()
    if env_value is not None:
        return env_value
    return REFRESH_INTERVAL


def get_version() -> str:
    """Get the package version.

    Returns:
        The package version string.
    """
    try:
        return version("stoei")
    except Exception:
        return "unknown"


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        prog="stoei",
        description="A TUI application for monitoring SLURM jobs.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {get_version()}",
        help="Show program version and exit.",
    )
    parser.add_argument(
        "--refresh-interval",
        type=positive_float,
        default=None,
        metavar="SECONDS",
        help=(
            "Seconds between automatic data refreshes "
            f"(default {REFRESH_INTERVAL:.1f}, "
            f"overridable via ${ENV_REFRESH_INTERVAL})."
        ),
    )
    return parser.parse_args()


def run() -> None:
    """Run the app with standard Python tracebacks."""
    # Parse arguments (handles --version automatically)
    args = parse_args()
    refresh_interval = resolve_refresh_interval(getattr(args, "refresh_interval", None))

    try:
        main(refresh_interval=refresh_interval)
    except Exception:
        logger.exception("Unhandled exception while running stoei")
        # Print standard Python traceback instead of Rich's fancy one
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run()
