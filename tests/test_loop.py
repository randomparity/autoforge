"""Tests for loop module utility functions."""

from __future__ import annotations

from src.agent.autonomous import _below_threshold


class TestBelowThreshold:
    def test_below_returns_true(self) -> None:
        campaign = {"metric": {"threshold": 0.5}}
        assert _below_threshold(10.1, 10.0, campaign) is True

    def test_above_returns_false(self) -> None:
        campaign = {"metric": {"threshold": 0.01}}
        assert _below_threshold(11.0, 10.0, campaign) is False

    def test_no_threshold_returns_false(self) -> None:
        campaign = {"metric": {}}
        assert _below_threshold(10.0, 10.0, campaign) is False

    def test_none_metric_returns_false(self) -> None:
        campaign = {"metric": {"threshold": 0.5}}
        assert _below_threshold(None, 10.0, campaign) is False

    def test_none_best_returns_false(self) -> None:
        campaign = {"metric": {"threshold": 0.5}}
        assert _below_threshold(10.0, None, campaign) is False

    def test_exact_threshold_returns_false(self) -> None:
        campaign = {"metric": {"threshold": 1.0}}
        assert _below_threshold(11.0, 10.0, campaign) is False
