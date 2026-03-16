"""DTS test execution for the runner."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DtsResult:
    """Result of a DTS test run."""

    success: bool
    results_json: dict | None
    results_summary: str | None
    metric_value: float | None
    error: str | None
    duration_seconds: float


def _extract_metric_value(data: dict, path: str) -> float | None:
    """Extract a numeric value from nested dict using dot-notation path.

    Args:
        data: The JSON results dictionary.
        path: Dot-separated key path (e.g. 'results.throughput.avg').

    Returns:
        The extracted float value, or None if the path is invalid.
    """
    current = data
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            logger.warning("Metric path %r not found in results", path)
            return None

    try:
        return float(current)
    except (TypeError, ValueError):
        logger.warning("Metric value at %r is not numeric: %r", path, current)
        return None


def run_dts(
    dts_path: Path,
    config: dict,
    suites: list[str],
    perf: bool,
    metric_path: str,
    timeout: int = 3600,
) -> DtsResult:
    """Run the DTS test suite and collect results.

    Args:
        dts_path: Path to the DTS installation directory.
        config: Runner configuration dictionary (for DTS-specific settings).
        suites: List of test suite names to run.
        perf: Whether to run in performance mode.
        metric_path: Dot-notation path to extract metric from results JSON.
        timeout: Maximum seconds before the test is killed.

    Returns:
        A DtsResult with test outcomes, metrics, and duration.
    """
    start = time.monotonic()

    cmd = ["poetry", "run", "./main.py"]
    for suite in suites:
        cmd.extend(["--test-suite", suite])
    if perf:
        cmd.append("--perf")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(dts_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.monotonic() - start

        if result.returncode != 0:
            return DtsResult(
                success=False,
                results_json=None,
                results_summary=None,
                metric_value=None,
                error=f"DTS exited with code {result.returncode}:\n{result.stderr[-2000:]}",
                duration_seconds=duration,
            )

        results_json = _read_json_file(dts_path / "output" / "results.json")
        results_summary = _read_text_file(dts_path / "output" / "results_summary.txt")

        metric_value = None
        if results_json is not None:
            metric_value = _extract_metric_value(results_json, metric_path)

        return DtsResult(
            success=True,
            results_json=results_json,
            results_summary=results_summary,
            metric_value=metric_value,
            error=None,
            duration_seconds=duration,
        )

    except subprocess.TimeoutExpired:
        duration = time.monotonic() - start
        logger.error("DTS timed out after %.0fs", duration)
        return DtsResult(
            success=False,
            results_json=None,
            results_summary=None,
            metric_value=None,
            error=f"DTS timed out after {duration:.0f}s",
            duration_seconds=duration,
        )


def _read_json_file(path: Path) -> dict | None:
    """Read and parse a JSON file, returning None on failure."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("Could not read results JSON at %s: %s", path, exc)
        return None


def _read_text_file(path: Path) -> str | None:
    """Read a text file, returning None on failure."""
    try:
        return path.read_text()
    except FileNotFoundError:
        logger.warning("Results summary not found at %s", path)
        return None
