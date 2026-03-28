"""Linux perf profiler for containerized vLLM — captures CPU stacks and HW counters."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autoforge.plugins.protocols import ProfileResult, RunnerConfig

if TYPE_CHECKING:
    from autoforge.campaign import ProjectConfig

logger = logging.getLogger(__name__)


class PerfContainerProfiler:
    """Profiles a containerized process via its host-side PID using Linux perf."""

    name = "perf-container"

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    def configure(self, project_config: ProjectConfig, runner_config: RunnerConfig) -> None:
        self._config = runner_config.get("profiling", {})

    def profile(self, pid: int, duration: int, config: dict[str, Any]) -> ProfileResult:
        from autoforge.perf.analyze import summarize
        from autoforge.perf.arch import load_arch_profile
        from autoforge.perf.profile import profile_pid

        start = time.monotonic()
        merged = {**self._config, **config}

        target_pid = pid
        if target_pid <= 0:
            target_pid = _discover_container_pid(
                merged.get("container_name", "vllm-bench"),
                merged.get("runtime", "auto"),
            )
            if target_pid <= 0:
                return ProfileResult(
                    success=False,
                    error="Could not discover container PID",
                    duration_seconds=time.monotonic() - start,
                )

        output_dir = _output_dir()
        result = profile_pid(
            pid=target_pid,
            duration=duration,
            output_dir=output_dir,
            frequency=merged.get("frequency", 99),
            sudo=merged.get("sudo", False),
            cpus=merged.get("cpus"),
            symfs=f"/proc/{target_pid}/root",
        )
        elapsed = time.monotonic() - start

        if not result.success:
            logger.warning("Profiling failed: %s", result.error)
            return ProfileResult(
                success=False,
                error=result.error,
                duration_seconds=elapsed,
            )

        profile = load_arch_profile()
        summary = summarize(result.counters, result.folded_stacks, profile)

        return ProfileResult(
            success=True,
            summary=summary or {},
            duration_seconds=elapsed,
        )


def _discover_container_pid(container_name: str, runtime: str) -> int:
    """Get the host-side PID of a running container."""
    from projects.vllm._utils import resolve_runtime

    rt = resolve_runtime(runtime)
    try:
        result = subprocess.run(
            [rt, "inspect", "--format={{.State.Pid}}", container_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Container PID discovery failed: %s", exc)
        return 0

    if result.returncode != 0:
        logger.warning(
            "%s inspect failed (rc=%d): %s",
            rt,
            result.returncode,
            result.stderr.strip(),
        )
        return 0

    pid_str = result.stdout.strip()
    try:
        return int(pid_str)
    except ValueError:
        logger.warning("Invalid PID from container inspect: %r", pid_str)
        return 0


def _output_dir() -> Path:
    """Create a timestamped directory under perf/results/ for profile output."""
    from autoforge.pointer import REPO_ROOT

    return REPO_ROOT / "perf" / "results" / str(int(time.time()))
