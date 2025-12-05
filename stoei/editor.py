"""Editor integration for opening log files."""

import os
import shutil
import subprocess
from pathlib import Path

from stoei.logging import get_logger

logger = get_logger(__name__)

# Default editors to try if $EDITOR is not set
DEFAULT_EDITORS = ["less", "more", "vim", "nano", "vi", "cat"]


def get_editor() -> str | None:
    """Get the user's preferred editor.

    Checks $EDITOR environment variable first, then falls back to common editors.

    Returns:
        Path to editor executable, or None if no editor found.
    """
    # First check $EDITOR environment variable
    editor = os.environ.get("EDITOR")
    if editor and shutil.which(editor):
        logger.debug(f"Using $EDITOR: {editor}")
        return editor

    # Fall back to common editors
    for ed in DEFAULT_EDITORS:
        if shutil.which(ed):
            logger.debug(f"Using fallback editor: {ed}")
            return ed

    logger.warning("No suitable editor found")
    return None


def open_in_editor(filepath: str) -> tuple[bool, str]:
    """Open a file in the user's editor.

    Args:
        filepath: Path to the file to open.

    Returns:
        Tuple of (success, message).
    """
    path = Path(filepath)

    # Check if file exists
    if not path.exists():
        error_msg = f"File does not exist: {filepath}"
        logger.warning(error_msg)
        return False, error_msg

    # Check if file is readable
    if not path.is_file():
        error_msg = f"Not a regular file: {filepath}"
        logger.warning(error_msg)
        return False, error_msg

    if not os.access(filepath, os.R_OK):
        error_msg = f"File is not readable: {filepath}"
        logger.warning(error_msg)
        return False, error_msg

    # Get editor
    editor = get_editor()
    if not editor:
        error_msg = "No editor available. Set $EDITOR environment variable."
        logger.error(error_msg)
        return False, error_msg

    # Open file in editor
    try:
        logger.info(f"Opening {filepath} in {editor}")
        # Run editor and wait for it to complete
        result = subprocess.run(  # noqa: S603
            [editor, filepath],
            check=False,
        )
        if result.returncode != 0:
            error_msg = f"Editor exited with code {result.returncode}"
            logger.warning(error_msg)
            return False, error_msg

        return True, f"Opened {filepath} in {editor}"
    except FileNotFoundError as exc:
        error_msg = f"Editor not found: {exc}"
        logger.error(error_msg)
        return False, error_msg
    except subprocess.SubprocessError as exc:
        error_msg = f"Error running editor: {exc}"
        logger.error(error_msg)
        return False, error_msg
    except OSError as exc:
        error_msg = f"OS error opening editor: {exc}"
        logger.error(error_msg)
        return False, error_msg
