"""Tests for autonomous module API client creation."""

from __future__ import annotations

import pytest

from src.agent.autonomous import create_api_client


class TestCreateApiClient:
    def test_missing_anthropic_raises_import_error(self) -> None:
        # This test only works if anthropic is not installed,
        # which it may or may not be. Skip if installed.
        try:
            import anthropic  # noqa: F401

            pytest.skip("anthropic is installed")
        except ImportError:
            with pytest.raises(ImportError, match="anthropic"):
                create_api_client("anthropic")

    def test_openrouter_missing_key_raises(self, monkeypatch) -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            pytest.skip("anthropic not installed")

        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            create_api_client("openrouter")
