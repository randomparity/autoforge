"""Shared git utility functions used by both agent and runner."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from autoforge.protocol import GIT_TIMEOUT

logger = logging.getLogger(__name__)


def git_pull_with_stash(repo_root: Path, *, timeout: int = GIT_TIMEOUT) -> bool:
    """Pull latest changes with rebase, stashing local modifications first.

    Stashes uncommitted changes before pulling so that a co-located agent
    (or any other process modifying the working tree) does not block the rebase.
    Restores the stash after the pull completes.

    Args:
        repo_root: Root of the git repository to pull in.
        timeout: Seconds to allow for each git subprocess call.

    Returns:
        True if ``git pull --rebase`` succeeded, False otherwise.
    """
    stash_result = subprocess.run(
        ["git", "-C", str(repo_root), "stash", "--include-untracked"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    stashed = stash_result.returncode == 0 and "No local changes" not in stash_result.stdout

    pull_result = subprocess.run(
        ["git", "-C", str(repo_root), "pull", "--rebase"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if pull_result.returncode != 0:
        logger.warning("git pull --rebase failed: %s", pull_result.stderr.strip())

    if stashed:
        pop_result = subprocess.run(
            ["git", "-C", str(repo_root), "stash", "pop"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if pop_result.returncode != 0:
            logger.warning("git stash pop failed: %s", pop_result.stderr.strip())

    return pull_result.returncode == 0


def git_push_with_retry(
    repo_root: Path | None = None,
    *,
    max_retries: int = 3,
    timeout: int = GIT_TIMEOUT,
) -> bool:
    """Push to remote, retrying with pull --rebase on conflict.

    Args:
        repo_root: Repository root to pass via ``git -C``. If None, uses the
            current working directory (no ``-C`` flag).
        max_retries: Maximum number of push attempts.
        timeout: Seconds to allow for each git subprocess call.

    Returns:
        True if the push succeeded, False if all retries were exhausted or a
        rebase failed mid-retry.
    """
    base_cmd = ["git", "-C", str(repo_root)] if repo_root is not None else ["git"]

    for attempt in range(max_retries):
        result = subprocess.run(
            [*base_cmd, "push"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True

        logger.warning(
            "Push failed (attempt %d/%d): %s",
            attempt + 1,
            max_retries,
            result.stderr.strip(),
        )
        if attempt < max_retries - 1:
            rebase = subprocess.run(
                [*base_cmd, "pull", "--rebase"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if rebase.returncode != 0:
                logger.error("Pull --rebase failed: %s", rebase.stderr.strip())
                return False

    return False
