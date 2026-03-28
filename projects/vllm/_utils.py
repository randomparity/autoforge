"""Shared utilities for vLLM plugins."""

from __future__ import annotations

import shutil


def resolve_runtime(configured: str = "auto") -> str:
    """Return the container runtime to use.

    Args:
        configured: Explicit runtime name, or "auto" to detect from PATH.

    Returns:
        "docker" or "podman".

    Raises:
        RuntimeError: If no supported runtime is found on PATH.
    """
    if configured and configured != "auto":
        return configured
    if shutil.which("docker"):
        return "docker"
    if shutil.which("podman"):
        return "podman"
    msg = "No container runtime found. Install docker or podman."
    raise RuntimeError(msg)
