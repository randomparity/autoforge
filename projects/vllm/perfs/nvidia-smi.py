"""GPU utilization profiler via nvidia-smi CSV polling."""

from __future__ import annotations

import logging
import subprocess
import time
from typing import TYPE_CHECKING, Any

from autoforge.plugins.protocols import ProfileResult, RunnerConfig

if TYPE_CHECKING:
    from autoforge.campaign import ProjectConfig

logger = logging.getLogger(__name__)


class NvidiaSmiProfiler:
    """Captures GPU utilization and memory via nvidia-smi in CSV mode."""

    name = "nvidia-smi"

    def configure(self, project_config: ProjectConfig, runner_config: RunnerConfig) -> None:
        cfg = runner_config.get("profiling", {})
        self._interval_ms = int(cfg.get("interval_ms", 500))

    def profile(self, pid: int, duration: int, config: dict[str, Any]) -> ProfileResult:
        start = time.monotonic()
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=timestamp,utilization.gpu,utilization.memory,"
                    "memory.used,memory.total,temperature.gpu,power.draw",
                    "--format=csv,nounits,noheader",
                    "-lms",
                    str(self._interval_ms),
                ],
                capture_output=True,
                text=True,
                timeout=duration + 10,
            )
            elapsed = time.monotonic() - start
            samples = _parse_csv(result.stdout)
            summary = _summarize(samples)
            return ProfileResult(
                success=True,
                summary=summary,
                error=None,
                duration_seconds=elapsed,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            return ProfileResult(
                success=True,
                summary={"note": "completed via timeout", "duration": elapsed},
                duration_seconds=elapsed,
            )
        except FileNotFoundError:
            return ProfileResult(
                success=False,
                error="nvidia-smi not found",
                duration_seconds=time.monotonic() - start,
            )


def _parse_csv(output: str) -> list[dict[str, float]]:
    samples: list[dict[str, float]] = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            samples.append(
                {
                    "gpu_util_pct": float(parts[1]),
                    "mem_util_pct": float(parts[2]),
                    "mem_used_mib": float(parts[3]),
                    "mem_total_mib": float(parts[4]),
                    "temp_c": float(parts[5]),
                    "power_w": float(parts[6]) if len(parts) > 6 else 0,
                }
            )
        except (ValueError, IndexError):
            continue
    return samples


def _summarize(samples: list[dict[str, float]]) -> dict[str, Any]:
    if not samples:
        return {"error": "no samples collected"}
    n = len(samples)

    def avg(key: str) -> float:
        return sum(s[key] for s in samples) / n

    def mx(key: str) -> float:
        return max(s[key] for s in samples)

    return {
        "num_samples": n,
        "avg_gpu_util_pct": round(avg("gpu_util_pct"), 1),
        "max_gpu_util_pct": round(mx("gpu_util_pct"), 1),
        "avg_mem_used_mib": round(avg("mem_used_mib"), 0),
        "max_mem_used_mib": round(mx("mem_used_mib"), 0),
        "avg_temp_c": round(avg("temp_c"), 1),
        "avg_power_w": round(avg("power_w"), 1),
    }
