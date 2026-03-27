"""vLLM container builder — pull prebuilt or build from source."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autoforge.plugins.protocols import BuildResult

if TYPE_CHECKING:
    from autoforge.campaign import ProjectConfig

logger = logging.getLogger(__name__)


class VllmContainerBuilder:
    """Builds a vLLM container image via pull (prebuilt) or podman build (source)."""

    name = "container"

    def configure(self, project_config: ProjectConfig, runner_config: dict[str, Any]) -> None:
        cfg = runner_config.get("build", {})
        self._mode = cfg.get("mode", "prebuilt")
        self._base_image = cfg.get("base_image", "docker.io/vllm/vllm-openai:latest")
        self._local_tag = cfg.get("local_tag", "localhost/vllm-bench:latest")

    def build(
        self,
        source_path: Path,
        commit: str,
        build_dir: Path,
        timeout: int,
    ) -> BuildResult:
        start = time.monotonic()
        if self._mode == "prebuilt":
            return self._build_prebuilt(start, timeout)
        return self._build_from_source(source_path, commit, start, timeout)

    def _build_prebuilt(self, start: float, timeout: int) -> BuildResult:
        try:
            result = subprocess.run(
                ["podman", "pull", self._base_image],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = time.monotonic() - start
            if result.returncode != 0:
                logger.error("podman pull failed: %s", result.stderr.strip())
                return BuildResult(
                    success=False,
                    log=result.stderr[-2000:],
                    duration_seconds=elapsed,
                )
            subprocess.run(
                ["podman", "tag", self._base_image, self._local_tag],
                check=True,
                capture_output=True,
                timeout=30,
            )
            logger.info("Pulled %s in %.1fs", self._base_image, elapsed)
            return BuildResult(
                success=True,
                log=f"Pulled {self._base_image}",
                duration_seconds=elapsed,
                artifacts={"image": self._local_tag, "mode": "prebuilt"},
            )
        except subprocess.TimeoutExpired:
            return BuildResult(
                success=False,
                log="TIMEOUT pulling image",
                duration_seconds=time.monotonic() - start,
            )

    def _build_from_source(
        self,
        source_path: Path,
        commit: str,
        start: float,
        timeout: int,
    ) -> BuildResult:
        try:
            subprocess.run(
                ["git", "checkout", commit],
                cwd=source_path,
                check=True,
                capture_output=True,
                timeout=30,
            )
            result = subprocess.run(
                [
                    "podman",
                    "build",
                    "--security-opt",
                    "label=disable",
                    "--build-arg",
                    "VLLM_USE_PRECOMPILED=1",
                    "-t",
                    self._local_tag,
                    "-f",
                    str(source_path / "Dockerfile"),
                    str(source_path),
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            elapsed = time.monotonic() - start
            if result.returncode != 0:
                logger.error("podman build failed (exit %d)", result.returncode)
                return BuildResult(
                    success=False,
                    log=result.stderr[-2000:],
                    duration_seconds=elapsed,
                )
            logger.info("Built from source (%s) in %.1fs", commit[:12], elapsed)
            return BuildResult(
                success=True,
                log=result.stdout[-2000:],
                duration_seconds=elapsed,
                artifacts={
                    "image": self._local_tag,
                    "mode": "source",
                    "commit": commit,
                },
            )
        except subprocess.TimeoutExpired:
            return BuildResult(
                success=False,
                log="TIMEOUT building image",
                duration_seconds=time.monotonic() - start,
            )
