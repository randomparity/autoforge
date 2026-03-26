"""Tests for runner-side protocol operations."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from autoforge.agent.protocol import create_request
from autoforge.protocol import (
    STATUS_BUILDING,
    STATUS_BUILT,
    STATUS_CLAIMED,
    STATUS_COMPLETED,
    STATUS_DEPLOYED,
    STATUS_DEPLOYING,
    STATUS_FAILED,
    STATUS_PENDING,
    TestRequest,
)
from autoforge.runner.protocol import (
    _git_commit_push,
    claim,
    fail,
    find_by_status,
    update_status,
)

SAMPLE_CAMPAIGN = {
    "metric": {
        "name": "throughput_mpps",
        "path": "results.throughput_mpps",
    },
    "project": {
        "build": "local",
        "deploy": "local",
        "test": "testpmd-memif",
    },
}


class TestFindByStatus:
    def test_returns_none_for_empty_dir(self, tmp_path) -> None:
        assert find_by_status(tmp_path, STATUS_PENDING) is None

    def test_returns_none_for_nonexistent_dir(self, tmp_path) -> None:
        assert find_by_status(tmp_path / "nonexistent", STATUS_PENDING) is None

    def test_finds_pending_request(self, tmp_path) -> None:
        create_request(1, "abc123", SAMPLE_CAMPAIGN, "test", tmp_path)
        result = find_by_status(tmp_path, STATUS_PENDING)
        assert result is not None
        request, path = result
        assert request.sequence == 1
        assert request.status == STATUS_PENDING

    def test_skips_claimed_request(self, tmp_path) -> None:
        path = create_request(1, "abc123", SAMPLE_CAMPAIGN, "test", tmp_path)
        from autoforge.protocol import TestRequest

        req = TestRequest.read(path)
        req.status = STATUS_CLAIMED
        req.write(path)

        assert find_by_status(tmp_path, STATUS_PENDING) is None

    def test_returns_oldest_pending(self, tmp_path) -> None:
        create_request(2, "bbb", SAMPLE_CAMPAIGN, "second", tmp_path)
        create_request(1, "aaa", SAMPLE_CAMPAIGN, "first", tmp_path)
        result = find_by_status(tmp_path, STATUS_PENDING)
        assert result is not None
        request, _ = result
        assert request.sequence == 1


def _make_request(seq: int = 1, status: str = STATUS_PENDING) -> TestRequest:
    """Create a minimal TestRequest for testing."""
    req = TestRequest(
        sequence=seq,
        created_at="2026-03-26T00:00:00+00:00",
        source_commit="abc123",
        description="test",
        build_plugin="local",
        deploy_plugin="local",
        test_plugin="testpmd-memif",
    )
    if status != STATUS_PENDING:
        req.status = status
    return req


def _ok() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _fail_result() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="rejected")


class TestGitCommitPush:
    @patch("autoforge.runner.protocol.subprocess.run")
    def test_happy_path(self, mock_run: MagicMock, tmp_path) -> None:
        mock_run.return_value = _ok()
        path = tmp_path / "req.json"
        path.write_text("{}")

        assert _git_commit_push(path, "test commit") is True

        calls = mock_run.call_args_list
        assert calls[0].args[0] == ["git", "add", str(path)]
        assert calls[1].args[0] == ["git", "commit", "-m", "test commit"]
        assert calls[2].args[0] == ["git", "push"]
        assert len(calls) == 3

    @patch("autoforge.runner.protocol.subprocess.run")
    def test_retry_on_conflict(self, mock_run: MagicMock, tmp_path) -> None:
        path = tmp_path / "req.json"
        path.write_text("{}")

        mock_run.side_effect = [
            _ok(),  # git add
            _ok(),  # git commit
            _fail_result(),  # git push (first attempt)
            _ok(),  # git pull --rebase
            _ok(),  # git push (second attempt)
        ]

        assert _git_commit_push(path, "test", retries=3) is True

        calls = mock_run.call_args_list
        assert calls[3].args[0] == ["git", "pull", "--rebase"]
        assert calls[4].args[0] == ["git", "push"]

    @patch("autoforge.runner.protocol.subprocess.run")
    def test_add_failure_returns_false(self, mock_run: MagicMock, tmp_path) -> None:
        path = tmp_path / "req.json"
        path.write_text("{}")

        mock_run.side_effect = subprocess.CalledProcessError(1, "git add", stderr="fatal")

        assert _git_commit_push(path, "test") is False

    @patch("autoforge.runner.protocol.subprocess.run")
    def test_all_retries_exhausted(self, mock_run: MagicMock, tmp_path) -> None:
        path = tmp_path / "req.json"
        path.write_text("{}")

        mock_run.side_effect = [
            _ok(),  # git add
            _ok(),  # git commit
            _fail_result(),  # push 1
            _ok(),  # pull --rebase
            _fail_result(),  # push 2
            _ok(),  # pull --rebase
            _fail_result(),  # push 3 (last, no pull after)
        ]

        assert _git_commit_push(path, "test", retries=3) is False

    @patch("autoforge.runner.protocol.subprocess.run")
    def test_pull_rebase_failure_returns_false(self, mock_run: MagicMock, tmp_path) -> None:
        path = tmp_path / "req.json"
        path.write_text("{}")

        mock_run.side_effect = [
            _ok(),  # git add
            _ok(),  # git commit
            _fail_result(),  # push fails
            subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="rebase conflict"
            ),  # pull --rebase fails
        ]

        assert _git_commit_push(path, "test", retries=3) is False


class TestClaim:
    @patch("autoforge.runner.protocol._git_commit_push", return_value=True)
    def test_claim_success(self, mock_push: MagicMock, tmp_path) -> None:
        req = _make_request()
        path = tmp_path / "0001_test.json"
        req.write(path)

        assert claim(req, path) is True
        assert req.status == STATUS_CLAIMED
        assert req.claimed_at is not None

        reloaded = TestRequest.read(path)
        assert reloaded.status == STATUS_CLAIMED
        mock_push.assert_called_once_with(path, "runner: claim request 0001")

    @patch("autoforge.runner.protocol._git_commit_push", return_value=False)
    def test_claim_push_failure(self, mock_push: MagicMock, tmp_path) -> None:
        req = _make_request()
        path = tmp_path / "0001_test.json"
        req.write(path)

        assert claim(req, path) is False
        assert req.status == STATUS_CLAIMED


class TestUpdateStatus:
    @patch("autoforge.runner.protocol._git_commit_push", return_value=True)
    def test_completion_with_results(self, mock_push: MagicMock, tmp_path) -> None:
        req = _make_request(status=STATUS_CLAIMED)
        req.transition_to(STATUS_BUILDING)
        req.transition_to(STATUS_BUILT)
        req.transition_to(STATUS_DEPLOYING)
        req.transition_to(STATUS_DEPLOYED)
        req.transition_to("running")
        path = tmp_path / "0001_test.json"
        req.write(path)

        update_status(
            req,
            STATUS_COMPLETED,
            path,
            results_json={"throughput_mpps": 90.5},
            results_summary="90.5 Mpps",
            metric_value=90.5,
            completed_at="2026-03-26T12:00:00+00:00",
        )

        assert req.status == STATUS_COMPLETED
        assert req.metric_value == 90.5
        assert req.results_json == {"throughput_mpps": 90.5}
        assert req.results_summary == "90.5 Mpps"
        assert req.completed_at == "2026-03-26T12:00:00+00:00"

        reloaded = TestRequest.read(path)
        assert reloaded.status == STATUS_COMPLETED
        assert reloaded.metric_value == 90.5

    @patch("autoforge.runner.protocol._git_commit_push", return_value=True)
    def test_only_sets_non_none_fields(self, mock_push: MagicMock, tmp_path) -> None:
        req = _make_request(status=STATUS_CLAIMED)
        req.transition_to(STATUS_BUILDING)
        path = tmp_path / "0001_test.json"
        req.write(path)

        update_status(req, STATUS_BUILT, path)

        assert req.status == STATUS_BUILT
        assert req.metric_value is None
        assert req.error is None


class TestFail:
    @patch("autoforge.runner.protocol._git_commit_push", return_value=True)
    def test_fail_sets_error_and_status(self, mock_push: MagicMock, tmp_path) -> None:
        req = _make_request(status=STATUS_CLAIMED)
        req.transition_to(STATUS_BUILDING)
        path = tmp_path / "0001_test.json"
        req.write(path)

        fail(req, path, "build failed: missing header", log_snippet="error: foo.h")

        assert req.status == STATUS_FAILED
        assert req.error == "build failed: missing header"
        assert req.build_log_snippet == "error: foo.h"
        assert req.completed_at is not None

        reloaded = TestRequest.read(path)
        assert reloaded.status == STATUS_FAILED
        assert reloaded.error == "build failed: missing header"

    @patch("autoforge.runner.protocol._git_commit_push", return_value=True)
    def test_fail_without_log_snippet(self, mock_push: MagicMock, tmp_path) -> None:
        req = _make_request(status=STATUS_CLAIMED)
        req.transition_to(STATUS_BUILDING)
        path = tmp_path / "0001_test.json"
        req.write(path)

        fail(req, path, "timeout exceeded")

        assert req.status == STATUS_FAILED
        assert req.error == "timeout exceeded"
        assert req.build_log_snippet is None
