"""Architecture detection and PMU event profile loading."""

from __future__ import annotations

import json
import logging
import platform
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


class ArchProfile(TypedDict, total=False):
    """Architecture-specific PMU event profile."""

    arch: str
    events: dict[str, str]
    derived_metrics: dict[str, str]
    heuristics: list[dict[str, Any]]
    notes: list[str]


COMMON_EVENTS = [
    "cycles",
    "instructions",
    "cache-misses",
    "cache-references",
    "branch-misses",
]

ARCH_DIR = Path(__file__).resolve().parent.parent.parent / "perf" / "arch"


def detect_arch() -> str:
    """Return the current machine architecture, normalized to our profile keys."""
    return platform.machine()


def load_arch_profile(arch: str | None = None) -> ArchProfile:
    """Load the architecture-specific PMU event profile.

    Args:
        arch: Architecture key (e.g. 'x86_64'). Auto-detected if None.

    Returns:
        Parsed JSON profile dict with 'events', 'derived_metrics',
        'heuristics', and 'notes' keys. Falls back to a minimal
        common-event profile if no arch file exists.
    """
    if arch is None:
        arch = detect_arch()

    profile_path = ARCH_DIR / f"{arch}.json"
    if profile_path.is_file():
        with open(profile_path) as f:
            return json.load(f)

    logger.warning("No arch profile for %s, using common events", arch)
    return {
        "arch": arch,
        "events": {e: e for e in COMMON_EVENTS},
        "derived_metrics": {
            "ipc": "instructions / cycles",
        },
        "heuristics": [],
        "notes": [f"Fallback profile for {arch} — no arch-specific JSON found."],
    }
