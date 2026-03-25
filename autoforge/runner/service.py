"""Runner service entry point — dispatches to phase-specific runners."""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

from autoforge.logging_config import setup_logging
from autoforge.runner.base import (
    BuildRunner,
    DeployRunner,
    FullRunner,
    TestRunner,
)

logger = logging.getLogger(__name__)

PHASE_RUNNERS = {
    "all": FullRunner,
    "build": BuildRunner,
    "deploy": DeployRunner,
    "test": TestRunner,
}


def load_config(path: str | None = None) -> dict:
    """Load runner configuration from a TOML file."""
    config_path = path or os.environ.get("AUTOFORGE_CONFIG", "config/runner.toml")
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def _load_campaign() -> dict:
    """Load campaign.toml from the repo root."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    campaign_path = repo_root / "config" / "campaign.toml"
    if not campaign_path.exists():
        msg = f"Campaign config not found: {campaign_path}"
        raise FileNotFoundError(msg)
    with open(campaign_path, "rb") as f:
        return tomllib.load(f)


def _load_requests_dir(campaign: dict) -> Path:
    """Derive the requests directory from campaign sprint config."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    sprint_name = campaign.get("sprint", {}).get("name")
    if not sprint_name:
        msg = "No [sprint] name in campaign.toml. Run 'autoforge sprint init' first."
        raise ValueError(msg)
    project_name = campaign.get("project", {}).get("name", "")
    if project_name:
        return repo_root / "projects" / project_name / "sprints" / sprint_name / "requests"
    return repo_root / "sprints" / sprint_name / "requests"


def main() -> None:
    """Runner service entry point."""
    config = load_config()
    runner_cfg = config.get("runner", {})

    setup_logging(
        level_name=runner_cfg.get("log_level"),
        log_file=runner_cfg.get("log_file"),
    )

    campaign = _load_campaign()
    req_dir = _load_requests_dir(campaign)

    phase = runner_cfg.get("phase", "all")
    runner_cls = PHASE_RUNNERS.get(phase)
    if runner_cls is None:
        msg = f"Unknown runner phase {phase!r}, must be one of {sorted(PHASE_RUNNERS)}"
        raise ValueError(msg)

    runner = runner_cls(config=config, campaign=campaign, requests_dir=req_dir)
    logger.info("Starting %s runner (id=%s)", phase, runner.runner_id or "unset")
    runner.poll_loop()


if __name__ == "__main__":
    main()
