"""Array job parsing utilities for SLURM job IDs."""

import re


def parse_array_size(job_id: str) -> int:
    """Parse job ID and return array size (1 for non-array jobs).

    Handles formats:
    - "12345" -> 1 (regular job)
    - "12345_5" -> 1 (single array task)
    - "12345_[0-99]" -> 100 (pending array, 0 to 99 inclusive)
    - "12345_[1-100]" -> 100 (pending array, 1 to 100 inclusive)
    - "12345_[0-99%5]" -> 100 (array with step throttle, still 100 tasks)
    - "12345_[1,3,5,7-10]" -> 7 (mixed list and range)

    Args:
        job_id: SLURM job ID string.

    Returns:
        Number of array tasks (1 for non-array jobs).
    """
    if not job_id or not isinstance(job_id, str):
        return 1

    job_id = job_id.strip()

    # Check for array notation with brackets
    bracket_match = re.search(r"_\[([^\]]+)\]", job_id)
    if not bracket_match:
        # No brackets - either regular job (12345) or single array task (12345_5)
        return 1

    array_spec = bracket_match.group(1)
    return _parse_array_spec(array_spec)


def _parse_array_spec(array_spec: str) -> int:
    """Parse the array specification inside brackets.

    Args:
        array_spec: The content inside brackets, e.g., "0-99", "0-99%5", "1,3,5,7-10".

    Returns:
        Number of array tasks.
    """
    # Remove throttle suffix (e.g., %5 in 0-99%5)
    throttle_match = re.search(r"(.+)%\d+$", array_spec)
    if throttle_match:
        array_spec = throttle_match.group(1)

    # Handle comma-separated list (e.g., "1,3,5,7-10")
    if "," in array_spec:
        return _parse_comma_list(array_spec)

    # Handle simple range (e.g., "0-99")
    return _parse_range(array_spec)


def _parse_comma_list(array_spec: str) -> int:
    """Parse comma-separated array specification.

    Args:
        array_spec: Comma-separated list like "1,3,5,7-10".

    Returns:
        Total number of tasks.
    """
    total = 0
    parts = array_spec.split(",")

    for part in parts:
        stripped_part = part.strip()
        if not stripped_part:
            continue

        if "-" in stripped_part:
            total += _parse_range(stripped_part)
        else:
            # Single number
            try:
                int(stripped_part)  # Validate it's a number
                total += 1
            except ValueError:
                continue

    return max(1, total)


def _parse_range(range_spec: str) -> int:
    """Parse a range specification like "0-99" or "1-100".

    Args:
        range_spec: Range string like "0-99".

    Returns:
        Number of tasks in the range.
    """
    range_match = re.match(r"^(\d+)-(\d+)$", range_spec.strip())
    if range_match:
        try:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if end >= start:
                return end - start + 1
        except ValueError:
            pass

    # Single number or invalid format
    try:
        int(range_spec.strip())
    except ValueError:
        return 1
    else:
        return 1
