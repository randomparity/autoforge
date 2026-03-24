"""Metric comparison for optimization results."""

from __future__ import annotations

from typing import Literal

Direction = Literal["maximize", "minimize"]


def compare_metric(current: float, best: float, direction: Direction) -> bool:
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
