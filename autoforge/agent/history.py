"""TSV-based iteration history management."""

from __future__ import annotations

import csv
import logging
from datetime import UTC, datetime
from pathlib import Path

from autoforge.protocol import Direction

logger = logging.getLogger(__name__)

COLUMNS = [
    "sequence",
    "timestamp",
    "source_commit",
    "metric_value",
    "status",
    "description",
    "tags",
]
FAILURE_COLUMNS = ["timestamp", "source_commit", "metric_value", "description", "diff_summary"]


def append_result(
    seq: int,
    commit: str,
    metric: float | None,
    status: str,
    description: str,
    *,
    path: Path,
    tags: list[str] | None = None,
) -> None:
    """Append an iteration result to the TSV history file.

    Args:
        seq: Iteration sequence number.
        commit: DPDK submodule commit SHA.
        metric: Metric value (None if the run failed before measurement).
        status: Final status (completed, failed, etc.).
        description: Human-readable description of the change.
        path: Path to the results.tsv file.
        tags: Optional experiment category tags.
    """
    existing = load_history(path)
    if any(row.get("sequence") == str(seq) for row in existing):
        logger.info("Sequence %d already recorded in %s, skipping", seq, path)
        return

    timestamp = datetime.now(UTC).isoformat()
    metric_str = str(metric) if metric is not None else ""

    try:
        with open(path, "a", newline="") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            row = [seq, timestamp, commit, metric_str, status, description]
            if tags:
                row.append(",".join(tags))
            writer.writerow(row)
    except OSError as exc:
        msg = f"Failed to append result to {path}: {exc}"
        raise OSError(msg) from exc


def load_history(path: Path) -> list[dict[str, str]]:
    """Read the TSV history file into a list of row dicts keyed by column name."""
    if not path.exists():
        return []

    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            return list(reader)
    except OSError as exc:
        logger.warning("Failed to read history from %s: %s", path, exc)
        return []


def score_rows(rows: list[dict[str, str]]) -> list[tuple[float, dict[str, str]]]:
    """Return rows that have a parseable numeric metric value.

    Args:
        rows: History rows as returned by load_history().

    Returns:
        List of (metric_float, row_dict) pairs in file order.
    """
    result = []
    for row in rows:
        val = row.get("metric_value", "")
        if val:
            try:
                result.append((float(val), row))
            except ValueError:
                continue
    return result


def scored_history(path: Path) -> list[tuple[float, dict[str, str]]]:
    """Return history rows from a file that have a parseable numeric metric value.

    Args:
        path: Path to the results.tsv file.

    Returns:
        List of (metric_float, row_dict) pairs in file order.
    """
    return score_rows(load_history(path))


def best_result(
    path: Path,
    direction: Direction = "maximize",
) -> dict[str, str] | None:
    """Return the history row with the best metric value.

    Args:
        path: Path to the results.tsv file.
        direction: 'maximize' or 'minimize'.

    Returns:
        The best row dict, or None if no valid metrics exist.
    """
    scored = scored_history(path)
    if not scored:
        return None
    if direction == "minimize":
        return min(scored, key=lambda x: x[0])[1]
    return max(scored, key=lambda x: x[0])[1]


def rolling_average_result(
    path: Path,
    window: int = 5,
) -> float | None:
    """Return the rolling average of the last N metric values.

    Uses all completed results with valid metrics (both kept and reverted),
    since a reverted metric is still a valid measurement of the code's
    baseline behavior.

    Args:
        path: Path to the results.tsv file.
        window: Number of recent results to average.

    Returns:
        The average metric value, or None if no valid metrics exist.
    """
    scored = scored_history(path)
    if not scored:
        return None
    recent = scored[-window:]
    return sum(v for v, _ in recent) / len(recent)


def append_failure(
    commit: str,
    metric: float | None,
    description: str,
    diff_summary: str,
    *,
    path: Path,
) -> None:
    """Record a failed optimization attempt.

    Args:
        commit: DPDK commit SHA that was reverted.
        metric: Metric value that was worse than best.
        description: What the change attempted.
        diff_summary: Short git diff --stat of the reverted change.
        path: Path to the failures.tsv file.
    """
    timestamp = datetime.now(UTC).isoformat()
    metric_str = str(metric) if metric is not None else ""

    try:
        write_header = not path.exists()
        with open(path, "a", newline="") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            if write_header:
                writer.writerow(FAILURE_COLUMNS)
            row = [timestamp, commit, metric_str, description]
            if diff_summary:
                row.append(diff_summary)
            writer.writerow(row)
    except OSError as exc:
        msg = f"Failed to append failure to {path}: {exc}"
        raise OSError(msg) from exc


def load_failures(path: Path) -> list[dict[str, str]]:
    """Read the failures TSV file into a list of row dicts keyed by column name."""
    if not path.exists():
        return []

    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            return list(reader)
    except OSError as exc:
        logger.warning("Failed to read failures from %s: %s", path, exc)
        return []


def format_failures(failures: list[dict[str, str]], limit: int = 10) -> str:
    """Format recent failures for inclusion in prompts.

    Args:
        failures: List of failure row dicts.
        limit: Maximum number of recent failures to include.

    Returns:
        Multi-line string summarizing recent failures.
    """
    if not failures:
        return ""

    recent = failures[-limit:]
    lines = ["Previously failed attempts (do NOT repeat these):"]
    for row in recent:
        desc = row.get("description", "?")
        metric = row.get("metric_value", "N/A") or "N/A"
        diff = row.get("diff_summary", "")
        lines.append(f"  - {desc} (metric={metric})")
        if diff:
            for diff_line in diff.split("\\n"):
                if diff_line.strip():
                    lines.append(f"    {diff_line.strip()}")

    return "\n".join(lines)
