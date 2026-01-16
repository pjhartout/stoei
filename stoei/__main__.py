"""Entry point for stoei."""

import argparse
import os
import sys
import traceback
from importlib.metadata import version

from stoei.app import main
from stoei.logger import get_logger

logger = get_logger(__name__)


def _ensure_truecolor() -> None:
    """Ensure true color mode is enabled for consistent theme rendering.

    Many terminals support true color (24-bit) but have COLORTERM set to
    non-standard values like '1' instead of 'truecolor'. This causes Rich/Textual
    to fall back to 256-color mode, which approximates hex colors poorly
    (e.g., Nord's #2e3440 becomes a teal color instead of dark blue-gray).

    This function sets COLORTERM=truecolor if not already set to a known
    true color value. Most modern terminals (including tmux with proper config)
    support true color.
    """
    colorterm = os.environ.get("COLORTERM", "")
    if colorterm.lower() not in ("truecolor", "24bit"):
        os.environ["COLORTERM"] = "truecolor"
        logger.debug(f"Set COLORTERM=truecolor (was: {colorterm!r})")


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
    return parser.parse_args()


def run() -> None:
    """Run the app with standard Python tracebacks."""
    # Parse arguments (handles --version automatically)
    parse_args()

    # Ensure true color mode for consistent theme colors
    _ensure_truecolor()

    try:
        main()
    except Exception:
        logger.exception("Unhandled exception while running stoei")
        # Print standard Python traceback instead of Rich's fancy one
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run()
