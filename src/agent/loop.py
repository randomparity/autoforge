"""Main autoresearch optimization loop."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import tomllib
from pathlib import Path

from src.agent.history import (
    append_failure,
    append_result,
    best_result,
    format_failures,
    load_failures,
    load_history,
)
from src.agent.metric import compare_metric
from src.agent.protocol import create_request, next_sequence, poll_for_completion
from src.agent.strategy import format_context, validate_change
from src.logging_config import setup_logging

logger = logging.getLogger(__name__)


def _below_threshold(
    metric: float | None,
    best_val: float | None,
    campaign: dict,
) -> bool:
    """Check if improvement between metric and best_val is below threshold."""
    threshold = campaign.get("metric", {}).get("threshold")
    if threshold is None or metric is None or best_val is None:
        return False
    return abs(metric - best_val) < threshold


def load_campaign(path: Path) -> dict:
    """Load and return the campaign TOML configuration."""
    with open(path, "rb") as f:
        return tomllib.load(f)


def git_submodule_head(dpdk_path: Path) -> str:
    """Return the current HEAD commit SHA of the DPDK submodule."""
    result = subprocess.run(
        ["git", "-C", str(dpdk_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def git_add_commit_push(
    paths: list[str],
    message: str,
    dry_run: bool = False,
) -> None:
    """Stage files, commit, and optionally push."""
    for p in paths:
        subprocess.run(["git", "add", p], check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        check=True,
        capture_output=True,
        text=True,
    )
    if not dry_run:
        subprocess.run(["git", "push"], check=True, capture_output=True, text=True)


def ensure_optimization_branch(dpdk_path: Path, branch: str) -> None:
    """Create and check out the optimization branch if it doesn't exist."""
    result = subprocess.run(
        ["git", "-C", str(dpdk_path), "branch", "--list", branch],
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        logger.info("Creating optimization branch %s in %s", branch, dpdk_path)
        subprocess.run(
            ["git", "-C", str(dpdk_path), "checkout", "-b", branch],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        current = subprocess.run(
            ["git", "-C", str(dpdk_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
        if current.stdout.strip() != branch:
            subprocess.run(
                ["git", "-C", str(dpdk_path), "checkout", branch],
                check=True,
                capture_output=True,
                text=True,
            )


def get_diff_summary(dpdk_path: Path) -> str:
    """Capture a short diff stat of the last commit vs its parent."""
    result = subprocess.run(
        ["git", "-C", str(dpdk_path), "diff", "--stat", "HEAD~1", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def revert_last_change(dpdk_path: Path) -> None:
    """Reset the DPDK submodule to the previous commit."""
    subprocess.run(
        ["git", "-C", str(dpdk_path), "reset", "--hard", "HEAD~1"],
        check=True,
        capture_output=True,
        text=True,
    )
    logger.info("Reverted DPDK submodule to %s", git_submodule_head(dpdk_path)[:12])


def run_interactive_iteration(
    campaign: dict,
    dpdk_path: Path,
    dry_run: bool,
) -> bool:
    """Run one iteration of the interactive optimization loop.

    Returns True to continue, False to stop.
    """
    history = load_history()
    metric_cfg = campaign["metric"]
    direction = metric_cfg.get("direction", "maximize")
    max_iter = campaign.get("campaign", {}).get("max_iterations", 50)

    if len(history) >= max_iter:
        print(f"Reached max iterations ({max_iter}). Stopping.")
        return False

    print("\n" + "=" * 60)
    print(format_context(history, campaign))
    print("=" * 60)

    print("\nMake your DPDK changes in the submodule, commit them, then press Enter.")
    print("Type 'quit' to stop the loop.")
    user_input = input("> ").strip()
    if user_input.lower() in ("quit", "exit", "q"):
        return False

    if not validate_change(dpdk_path):
        print("No submodule change detected. Skipping iteration.")
        return True

    commit = git_submodule_head(dpdk_path)
    description = input("Describe this change: ").strip() or "No description"
    seq = next_sequence()
    poll_interval = campaign.get("agent", {}).get("poll_interval", 30)
    timeout = campaign.get("agent", {}).get("timeout_minutes", 60) * 60

    request_path = create_request(seq, commit, campaign, description)

    git_add_commit_push(
        [str(request_path), str(dpdk_path)],
        f"iteration {seq:04d}: {description}",
        dry_run=dry_run,
    )
    print(f"Request {seq:04d} submitted. Polling for results...")

    if dry_run:
        print("[dry-run] Skipping poll — no push was made.")
        append_result(seq, commit, None, "dry_run", description)
        return True

    try:
        result = poll_for_completion(seq, timeout=timeout, interval=poll_interval)
    except TimeoutError:
        print(f"Request {seq:04d} timed out.")
        append_result(seq, commit, None, "timed_out", description)
        return True

    if result.status == "failed":
        print(f"Request {seq:04d} FAILED: {result.error}")
        append_result(seq, commit, None, "failed", description)
        return True

    metric = result.metric_value
    print(f"Request {seq:04d} completed. Metric: {metric}")

    current_best = best_result(direction=direction)
    best_val = float(current_best["metric_value"]) if current_best is not None else None
    improved = best_val is None or (
        metric is not None and compare_metric(metric, best_val, direction)
    )

    append_result(seq, commit, metric, "completed", description)

    if improved:
        print(f"Improvement! {best_val} -> {metric}" if best_val else f"Baseline: {metric}")
        files_to_commit = ["results.tsv", str(dpdk_path)]
        git_add_commit_push(files_to_commit, f"results: iteration {seq:04d}", dry_run=dry_run)
    else:
        print(f"No improvement ({metric} vs best {best_val}). Reverting change.")
        diff_summary = get_diff_summary(dpdk_path)
        revert_last_change(dpdk_path)
        append_failure(commit, metric, description, diff_summary)
        files_to_commit = ["results.tsv", "failures.tsv", str(dpdk_path)]
        git_add_commit_push(files_to_commit, f"revert: iteration {seq:04d}", dry_run=dry_run)

    if _below_threshold(metric, best_val, campaign):
        threshold = campaign["metric"]["threshold"]
        print(f"Improvement below threshold ({threshold}). Stopping early.")
        return False

    return True


def main() -> None:
    """Entry point for the autosearch agent."""
    parser = argparse.ArgumentParser(description="Autosearch DPDK optimization agent")
    parser.add_argument(
        "--campaign",
        default="config/campaign.toml",
        help="Path to campaign TOML config",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip git push (local testing)",
    )
    parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Use Claude API for automated change proposals",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openrouter"],
        default="anthropic",
        help="API provider for autonomous mode (default: anthropic)",
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default=None,
        help="Log level (default: info, or LOG_LEVEL env var)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Path to log file (logs to stdout and file)",
    )
    args = parser.parse_args()

    setup_logging(args.log_level, args.log_file)

    campaign = load_campaign(Path(args.campaign))
    dpdk_path = Path(campaign.get("dpdk", {}).get("submodule_path", "dpdk"))
    opt_branch = campaign.get("dpdk", {}).get("optimization_branch", "autosearch/optimize")
    ensure_optimization_branch(dpdk_path, opt_branch)

    if args.autonomous:
        run_autonomous(campaign, dpdk_path, args.dry_run, args.provider)
    else:
        while run_interactive_iteration(campaign, dpdk_path, args.dry_run):
            pass

    print("Optimization loop finished.")


def build_client(provider: str) -> tuple:
    """Build an Anthropic-compatible API client and model ID.

    Args:
        provider: "anthropic" or "openrouter".

    Returns:
        (client, model_id) tuple.
    """
    try:
        import anthropic
    except ImportError:
        print("Error: 'anthropic' package required for autonomous mode.")
        print("Install with: uv add anthropic")
        sys.exit(1)

    if provider == "openrouter":
        import os

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            print("Error: OPENROUTER_API_KEY environment variable required.")
            sys.exit(1)
        client = anthropic.Anthropic(
            base_url="https://openrouter.ai/api",
            api_key=api_key,
        )
        model = "anthropic/claude-opus-4-6"
    else:
        client = anthropic.Anthropic()
        model = "claude-opus-4-6"

    return client, model


def run_autonomous(
    campaign: dict,
    dpdk_path: Path,
    dry_run: bool,
    provider: str = "anthropic",
) -> None:
    """Run the autonomous optimization loop using the Claude API.

    Args:
        campaign: Parsed campaign configuration.
        dpdk_path: Path to the DPDK submodule.
        dry_run: If True, skip git push operations.
        provider: API provider ("anthropic" or "openrouter").
    """
    client, model = build_client(provider)
    max_iter = campaign.get("campaign", {}).get("max_iterations", 50)

    for _ in range(max_iter):
        history = load_history()
        failures = load_failures()
        context = format_context(history, campaign)

        goal = campaign.get("goal", {}).get("description", "").strip()
        goal_block = f"\nGoal:\n{goal}\n" if goal else ""

        failures_block = format_failures(failures)
        failures_section = f"\n{failures_block}\n" if failures_block else ""

        prompt = (
            f"You are optimizing DPDK for maximum throughput.\n"
            f"{goal_block}\n"
            f"Current state:\n{context}\n"
            f"{failures_section}\n"
            f"Propose a specific code change to the DPDK source in {dpdk_path}. "
            f"Focus on the scoped areas. Describe the change and the file(s) to modify."
        )

        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        proposal = response.content[0].text
        print(f"\nClaude proposes:\n{proposal}\n")

        user_input = input("Apply this change? [y/N/quit]: ").strip().lower()
        if user_input == "quit":
            break
        if user_input != "y":
            continue

        if not validate_change(dpdk_path):
            print("No submodule change detected after proposal. Skipping.")
            continue

        commit = git_submodule_head(dpdk_path)
        seq = next_sequence()
        description = proposal[:200]
        poll_interval = campaign.get("agent", {}).get("poll_interval", 30)
        timeout = campaign.get("agent", {}).get("timeout_minutes", 60) * 60

        request_path = create_request(seq, commit, campaign, description)
        git_add_commit_push(
            [str(request_path), str(dpdk_path)],
            f"auto iteration {seq:04d}",
            dry_run=dry_run,
        )

        if dry_run:
            append_result(seq, commit, None, "dry_run", description)
            continue

        try:
            result = poll_for_completion(seq, timeout=timeout, interval=poll_interval)
        except TimeoutError:
            append_result(seq, commit, None, "timed_out", description)
            continue

        metric = result.metric_value if result.status == "completed" else None
        direction = campaign.get("metric", {}).get("direction", "maximize")
        prev_best = best_result(direction=direction)
        prev_val = float(prev_best["metric_value"]) if prev_best is not None else None
        improved = prev_val is None or (
            metric is not None and compare_metric(metric, prev_val, direction)
        )

        append_result(seq, commit, metric, result.status, description)

        if improved:
            print(f"Improvement! {prev_val} -> {metric}" if prev_val else f"Baseline: {metric}")
            files = ["results.tsv", str(dpdk_path)]
            git_add_commit_push(files, f"results: iteration {seq:04d}", dry_run=dry_run)
        else:
            print(f"No improvement ({metric} vs best {prev_val}). Reverting.")
            diff_summary = get_diff_summary(dpdk_path)
            revert_last_change(dpdk_path)
            append_failure(commit, metric, description, diff_summary)
            files = ["results.tsv", "failures.tsv", str(dpdk_path)]
            git_add_commit_push(files, f"revert: iteration {seq:04d}", dry_run=dry_run)

        if _below_threshold(metric, prev_val, campaign):
            threshold = campaign["metric"]["threshold"]
            print(f"Improvement below threshold ({threshold}). Stopping early.")
            break


if __name__ == "__main__":
    main()
