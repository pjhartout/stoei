"""Entry point for stoei."""

import sys
import traceback

from stoei.app import main


def run() -> None:
    """Run the app with standard Python tracebacks."""
    try:
        main()
    except Exception:
        # Print standard Python traceback instead of Rich's fancy one
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run()
