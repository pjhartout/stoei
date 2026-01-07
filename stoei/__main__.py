"""Entry point for stoei."""

import argparse
import sys
import traceback
from importlib.metadata import version

from stoei.app import main


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

    try:
        main()
    except Exception:
        # Print standard Python traceback instead of Rich's fancy one
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run()
