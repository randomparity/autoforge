"""Metric extraction and comparison for DTS results."""

from __future__ import annotations


def extract_metric(data: dict, path: str) -> float:
    """Walk a dot-notation path into nested dicts/lists and return the value.

    Numeric path components are treated as list indices.

    Args:
        data: The root dictionary (e.g. DTS results JSON).
        path: Dot-separated key path (e.g. 'test_runs.0.throughput_mpps').

    Returns:
        The numeric value at the given path.

    Raises:
        KeyError: If a dict key is missing.
        IndexError: If a list index is out of range.
        ValueError: If the path is empty or the value is not numeric.
    """
    if not path:
        msg = "Metric path must not be empty"
        raise ValueError(msg)

    current: object = data
    for key in path.split("."):
        if isinstance(current, list):
            current = current[int(key)]
        elif isinstance(current, dict):
            current = current[key]
        else:
            msg = f"Cannot index into {type(current).__name__} with key {key!r}"
            raise KeyError(msg)

    try:
        return float(current)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        msg = f"Metric value at '{path}' is not numeric: {current!r}"
        raise ValueError(msg) from exc


def compare_metric(current: float, best: float, direction: str) -> bool:
    """Return True if current is strictly better than best.

    Args:
        current: The metric value from the latest iteration.
        best: The best metric value seen so far.
        direction: Either 'maximize' or 'minimize'.

    Raises:
        ValueError: If direction is not 'maximize' or 'minimize'.
    """
    if direction == "maximize":
        return current > best
    if direction == "minimize":
        return current < best
    msg = f"Unknown direction {direction!r}, must be 'maximize' or 'minimize'"
    raise ValueError(msg)
