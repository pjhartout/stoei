"""Slurm NodeList expression parser for expanding bracket notation to hostnames."""

from stoei.logger import get_logger

logger = get_logger(__name__)


def _split_nodelist(s: str) -> list[str]:
    """Split a NodeList string on commas that are not inside brackets.

    Args:
        s: A NodeList string like "node01,node[03-05],gpu[01-02]".

    Returns:
        List of individual NodeList tokens.
    """
    tokens: list[str] = []
    depth = 0
    current: list[str] = []

    for ch in s:
        if ch == "[":
            depth += 1
            current.append(ch)
        elif ch == "]":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            tokens.append("".join(current))
            current = []
        else:
            current.append(ch)

    if current:
        tokens.append("".join(current))

    return tokens


def _expand_bracket_expr(expr: str) -> set[str]:
    """Expand a single bracket expression like "node[01-04]" or "node[01,03]".

    Args:
        expr: A bracket expression token, e.g. "node[01-04,07]".

    Returns:
        Set of expanded hostnames. Returns empty set if expression is malformed.
    """
    try:
        bracket_open = expr.index("[")
        bracket_close = expr.index("]")
    except ValueError:
        logger.warning(f"Malformed NodeList expression (missing bracket): {expr!r}")
        return set()

    prefix = expr[:bracket_open]
    spec = expr[bracket_open + 1 : bracket_close]

    result: set[str] = set()
    for part in spec.split(","):
        if "-" in part:
            range_parts = part.split("-", 1)
            try:
                start_str, end_str = range_parts[0], range_parts[1]
                start = int(start_str)
                end = int(end_str)
                # Preserve zero-padding width from the start token
                width = len(start_str)
                for i in range(start, end + 1):
                    result.add(f"{prefix}{str(i).zfill(width)}")
            except ValueError:
                logger.warning(f"Malformed range in NodeList expression: {part!r}")
        else:
            result.add(f"{prefix}{part}")

    return result


def expand_nodelist(nodelist: str) -> set[str]:
    """Expand a Slurm NodeList expression to a set of individual hostnames.

    Handles the full Slurm bracket notation including ranges, comma-separated
    lists within brackets, multiple prefix groups, and zero-padded indices.
    Returns an empty set for pending-state placeholders like "(None)" and
    for empty strings.

    Args:
        nodelist: A Slurm NodeList string, e.g. "node[01-04]",
            "node01,node[03-05]", "gpu[01-02],cpu[01-02]", or "(None)".

    Returns:
        Set of individual hostname strings. Empty set for pending placeholders,
        empty input, or malformed expressions (a warning is logged for the latter).

    Examples:
        >>> expand_nodelist("node01")
        {'node01'}
        >>> expand_nodelist("node[01-04]")
        {'node01', 'node02', 'node03', 'node04'}
        >>> expand_nodelist("(None)")
        set()
        >>> expand_nodelist("")
        set()
    """
    nodelist = nodelist.strip()

    if not nodelist or nodelist.startswith("("):
        return set()

    try:
        tokens = _split_nodelist(nodelist)
    except Exception as exc:
        logger.warning(f"Failed to parse NodeList {nodelist!r}: {exc}")
        return set()

    result: set[str] = set()
    for token in tokens:
        if not token:
            continue
        if "[" in token:
            result.update(_expand_bracket_expr(token))
        else:
            result.add(token)

    return result
