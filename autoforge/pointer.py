"""Pointer file (.autoforge.toml) operations."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TypedDict

REPO_ROOT = Path(__file__).resolve().parent.parent
POINTER_PATH = REPO_ROOT / ".autoforge.toml"


class PointerConfig(TypedDict):
    """Contents of .autoforge.toml pointer file."""

    project: str
    sprint: str


def load_pointer(path: Path | None = None) -> PointerConfig:
    """Load the .autoforge.toml pointer file.

    Args:
        path: Override path. Defaults to REPO_ROOT/.autoforge.toml.

    Raises:
        FileNotFoundError: If the pointer file does not exist.
        KeyError: If required fields are missing.
    """
    pointer_path = path or POINTER_PATH
    with open(pointer_path, "rb") as f:
        data = tomllib.load(f)
    project = data.get("project")
    sprint = data.get("sprint", "")
    if not project:
        msg = f"Missing 'project' in {pointer_path}"
        raise KeyError(msg)
    return PointerConfig(project=project, sprint=sprint)


def save_pointer(project: str, sprint: str, path: Path | None = None) -> None:
    """Write or update the .autoforge.toml pointer file."""
    pointer_path = path or POINTER_PATH
    pointer_path.write_text(f'project = "{project}"\nsprint = "{sprint}"\n')
