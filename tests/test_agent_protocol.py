"""Tests for agent-side protocol operations."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from autoforge.agent.protocol import (
    create_request,
    find_latest_request,
    next_sequence,
    poll_for_completion,
)
from autoforge.protocol import STATUS_COMPLETED, STATUS_PENDING, STATUS_RUNNING, TestRequest

SAMPLE_CAMPAIGN = {
    "metric": {
        "name": "throughput_mpps",
        "path": "throughput_mpps",
    },
    "project": {
        "build": "local",
        "deploy": "local",
        "test": "testpmd-memif",
    },
}

CAMPAIGN_WITH_PROFILER = {
    **SAMPLE_CAMPAIGN,
    "project": {
        **SAMPLE_CAMPAIGN["project"],
        "profiler": "perf-record",
    },
}


class TestNextSequence:
    def test_empty_dir_returns_1(self, tmp_path) -> None:
        assert next_sequence(requests_dir=tmp_path) == 1

    def test_increments_from_existing(self, tmp_path) -> None:
        (tmp_path / "0001_2025-01-15_10-30-00.json").write_text("{}")
        (tmp_path / "0003_2025-01-15_11-30-00.json").write_text("{}")
        assert next_sequence(requests_dir=tmp_path) == 4

    def test_ignores_non_json_files(self, tmp_path) -> None:
        (tmp_path / ".gitkeep").touch()
        (tmp_path / "notes.txt").write_text("hello")
        assert next_sequence(requests_dir=tmp_path) == 1


class TestCreateRequest:
    def test_creates_json_file(self, tmp_path) -> None:
        path = create_request(
            seq=1,
            commit="abc123",
            campaign=SAMPLE_CAMPAIGN,
            description="Test change",
            requests_dir=tmp_path,
        )
        assert path.exists()
        assert path.suffix == ".json"

    def test_file_contains_valid_request(self, tmp_path) -> None:
        path = create_request(
            seq=1,
            commit="abc123",
            campaign=SAMPLE_CAMPAIGN,
            description="Test change",
            requests_dir=tmp_path,
        )
        data = json.loads(path.read_text())
        assert data["sequence"] == 1
        assert data["source_commit"] == "abc123"
        assert data["status"] == STATUS_PENDING
        assert data["build_plugin"] == "local"
        assert data["deploy_plugin"] == "local"
        assert data["test_plugin"] == "testpmd-memif"

    def test_request_has_metric_fields(self, tmp_path) -> None:
        path = create_request(
            seq=1,
            commit="abc123",
            campaign=SAMPLE_CAMPAIGN,
            description="Test",
            requests_dir=tmp_path,
        )
        data = json.loads(path.read_text())
        assert data["metric_name"] == "throughput_mpps"
        assert data["metric_path"] == "throughput_mpps"


class TestSkipProfiling:
    def test_profiler_included_by_default(self, tmp_path) -> None:
        path = create_request(
            seq=1,
            commit="abc123",
            campaign=CAMPAIGN_WITH_PROFILER,
            description="With profiling",
            requests_dir=tmp_path,
        )
        data = json.loads(path.read_text())
        assert data["profile_plugin"] == "perf-record"

    def test_skip_profiling_omits_profiler(self, tmp_path) -> None:
        path = create_request(
            seq=1,
            commit="abc123",
            campaign=CAMPAIGN_WITH_PROFILER,
            description="Finale: no profiling",
            requests_dir=tmp_path,
            skip_profiling=True,
        )
        data = json.loads(path.read_text())
        assert data["profile_plugin"] == ""

    def test_skip_profiling_no_effect_without_profiler(self, tmp_path) -> None:
        path = create_request(
            seq=1,
            commit="abc123",
            campaign=SAMPLE_CAMPAIGN,
            description="No profiler configured",
            requests_dir=tmp_path,
            skip_profiling=True,
        )
        data = json.loads(path.read_text())
        assert data["profile_plugin"] == ""


class TestReadRequest:
    def test_reads_created_request(self, tmp_path) -> None:
        path = create_request(
            seq=1,
            commit="abc123",
            campaign=SAMPLE_CAMPAIGN,
            description="Test",
            requests_dir=tmp_path,
        )
        req = TestRequest.read(path)
        assert req.sequence == 1
        assert req.source_commit == "abc123"


class TestFindLatestRequest:
    def test_returns_none_when_empty(self, tmp_path) -> None:
        assert find_latest_request(requests_dir=tmp_path) is None

    def test_finds_highest_sequence(self, tmp_path) -> None:
        create_request(1, "aaa", SAMPLE_CAMPAIGN, "first", requests_dir=tmp_path)
        create_request(3, "ccc", SAMPLE_CAMPAIGN, "third", requests_dir=tmp_path)
        create_request(2, "bbb", SAMPLE_CAMPAIGN, "second", requests_dir=tmp_path)
        latest = find_latest_request(requests_dir=tmp_path)
        assert latest is not None
        assert latest.sequence == 3
        assert latest.source_commit == "ccc"


class TestPollForCompletion:
    def _write_request(self, tmp_path, seq: int = 1, status: str = STATUS_PENDING):
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
        path = tmp_path / f"{seq:04d}_2026-03-26_00-00-00.json"
        req.write(path)
        return path

    @patch("autoforge.agent.protocol.time.sleep")
    @patch("autoforge.git_utils.subprocess.run")
    def test_already_completed(self, mock_run: MagicMock, mock_sleep: MagicMock, tmp_path) -> None:
        self._write_request(tmp_path, seq=1, status=STATUS_COMPLETED)
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        result = poll_for_completion(1, tmp_path, timeout=60, interval=5)

        assert result.status == STATUS_COMPLETED
        mock_sleep.assert_not_called()

    @patch("autoforge.agent.protocol.time.sleep")
    @patch("autoforge.git_utils.subprocess.run")
    def test_completes_after_one_poll(
        self, mock_run: MagicMock, mock_sleep: MagicMock, tmp_path
    ) -> None:
        path = self._write_request(tmp_path, seq=1, status=STATUS_RUNNING)
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        poll_count = 0

        def fake_sleep(seconds):
            nonlocal poll_count
            poll_count += 1
            req = TestRequest.read(path)
            req.transition_to(STATUS_COMPLETED)
            req.metric_value = 85.0
            req.write(path)

        mock_sleep.side_effect = fake_sleep

        result = poll_for_completion(1, tmp_path, timeout=300, interval=5)

        assert result.status == STATUS_COMPLETED
        assert result.metric_value == 85.0
        assert poll_count == 1
