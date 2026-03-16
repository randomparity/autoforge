"""TSV-based iteration history management."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_RESULTS_PATH = Path("results.tsv")

COLUMNS = ["sequence", "timestamp", "dpdk_commit", "metric_value", "status", "description"]


def append_result(
    seq: int,
    commit: str,
    metric: float | None,
    status: str,
    description: str,
    path: Path | None = None,
) -> None:
    """Append an iteration result to the TSV history file.

    Args:
        seq: Iteration sequence number.
        commit: DPDK submodule commit SHA.
        metric: Metric value (None if the run failed before measurement).
        status: Final status (completed, failed, etc.).
        description: Human-readable description of the change.
        path: Path to the results.tsv file.
    """
    results_path = path or DEFAULT_RESULTS_PATH
    timestamp = datetime.now(UTC).isoformat()
    metric_str = str(metric) if metric is not None else ""

    with open(results_path, "a", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow([seq, timestamp, commit, metric_str, status, description])


def load_history(path: Path | None = None) -> list[dict]:
    """Read the TSV history file into a list of dicts.

    The file must have a header row matching COLUMNS. DictReader uses
    the first row as field names, so data rows start from the second line.

    Args:
        path: Path to the results.tsv file.

    Returns:
        List of row dicts keyed by column name.
    """
    results_path = path or DEFAULT_RESULTS_PATH
    if not results_path.exists():
        return []

    with open(results_path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def best_result(
    path: Path | None = None,
    direction: str = "maximize",
) -> dict | None:
    """Return the history row with the best metric value.

    Rows where metric_value is empty are skipped.

    Args:
        path: Path to the results.tsv file.
        direction: 'maximize' or 'minimize'.

    Returns:
        The best row dict, or None if no valid metrics exist.
    """
    rows = load_history(path)
    scored = []
    for row in rows:
        val = row.get("metric_value", "")
        if val:
            try:
                scored.append((float(val), row))
            except ValueError:
                continue

    if not scored:
        return None

    if direction == "minimize":
        return min(scored, key=lambda x: x[0])[1]
    return max(scored, key=lambda x: x[0])[1]
