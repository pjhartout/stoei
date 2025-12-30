"""Editor integration for opening log files."""

import os
import shutil
import subprocess
from pathlib import Path

from stoei.logger import get_logger

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


def open_in_editor(filepath: str | None) -> tuple[bool, str]:  # noqa: PLR0911
    """Open a file in the user's editor.

    Args:
        filepath: Path to the file to open.

    Returns:
        Tuple of (success, message).
    """
    if not filepath:
        error_msg = "No file path provided"
        logger.warning(error_msg)
        return False, error_msg

    # Resolve the path to handle relative paths and symlinks
    path = Path(filepath).expanduser().resolve()

    # Check if file exists
    if not path.exists():
        error_msg = f"File does not exist: {path}"
        logger.warning(error_msg)
        return False, error_msg

    # Check if file is readable
    if not path.is_file():
        error_msg = f"Not a regular file: {path}"
        logger.warning(error_msg)
        return False, error_msg

    # Check read permissions using the resolved path
    if not os.access(str(path), os.R_OK):
        error_msg = f"File is not readable: {path}"
        logger.warning(error_msg)
        return False, error_msg

    # Get editor
    editor = get_editor()
    if not editor:
        error_msg = "No editor available. Set $EDITOR environment variable."
        logger.error(error_msg)
        return False, error_msg

    # Open file in editor using the resolved absolute path
    resolved_path = str(path)
    try:
        logger.info(f"Opening {resolved_path} in {editor}")
        # Run editor and wait for it to complete
        result = subprocess.run(  # noqa: S603
            [editor, resolved_path],
            check=False,
        )
        if result.returncode != 0:
            error_msg = f"Editor exited with code {result.returncode}"
            logger.warning(error_msg)
            return False, error_msg
    except FileNotFoundError as exc:
        error_msg = f"Editor not found: {exc}"
        logger.exception(error_msg)
        return False, error_msg
    except subprocess.SubprocessError as exc:
        error_msg = f"Error running editor: {exc}"
        logger.exception(error_msg)
        return False, error_msg
    except OSError as exc:
        error_msg = f"OS error opening editor: {exc}"
        logger.exception(error_msg)
        return False, error_msg
    else:
        return True, f"Opened {resolved_path} in {editor}"
