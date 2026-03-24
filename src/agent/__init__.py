"""Agent-side modules for the autosearch optimization loop."""

from src.agent.autonomous import run_autonomous
from src.agent.git_ops import git_add_commit_push, git_submodule_head
from src.agent.history import append_result, best_result, load_history
from src.agent.loop import main
from src.agent.metric import compare_metric
from src.agent.protocol import (
    create_request,
    find_latest_request,
    next_sequence,
    poll_for_completion,
)
from src.agent.strategy import format_context, validate_change

__all__ = [
    "append_result",
    "best_result",
    "compare_metric",
    "create_request",
    "find_latest_request",
    "format_context",
    "git_add_commit_push",
    "git_submodule_head",
    "load_history",
    "main",
    "next_sequence",
    "poll_for_completion",
    "run_autonomous",
    "validate_change",
]
