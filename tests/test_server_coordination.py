"""Tests for PR signal coordination wiring in context()."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from jurati.core.index import Index
from jurati.core.pr_signals import PRSignal
from jurati.git.config import JuratiConfig, PRSignalsConfig
from jurati.providers.cache import SignalCache
from jurati.server import (
    ServerState,
    SyncHealth,
    _build_coordination,
    _format_guidance,
    _privacy_boundary,
)

NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


def _signal(number: int = 42, **overrides: object) -> PRSignal:
    defaults: dict[str, object] = {
        "signal_id": f"github:org/api:pull:{number}",
        "provider": "github",
        "repo": "org/api",
        "number": number,
        "url": f"https://github.com/org/api/pull/{number}",
        "title": "Resolve token refresh races",
        "body_excerpt": None,
        "author": "tony",
        "state": "open",
        "labels": ("jurati",),
        "created_at": NOW - timedelta(days=2),
        "updated_at": NOW - timedelta(hours=6),
        "merged_at": None,
        "changed_paths": ("src/auth/token.py",),
        "target_areas": ("src/auth",),
    }
    defaults.update(overrides)
    return PRSignal(**defaults)  # type: ignore[arg-type]


def _state(
    *, repos: tuple[str, ...] = ("org/api",), signals: list[PRSignal] | None = None
) -> ServerState:
    config = JuratiConfig(
        remote_url="https://example.com/repo.git",
        pr_signals=PRSignalsConfig(repos=repos),
    )
    cache = SignalCache(recency_days=30)
    if signals:
        cache.update(signals, now=NOW)
    return ServerState(
        config=config,
        repo_path="/fake/repo",
        index=Index(),
        last_sync=NOW,
        sync_health=SyncHealth(last_success=NOW),
        signal_cache=cache,
    )


class TestFormatGuidance:
    def test_formats_all_fields(self) -> None:
        from jurati.core.pr_signals import CoordinationGuidance, PRSignalEvidence

        ev = PRSignalEvidence(
            repo="org/api",
            number=42,
            url="https://github.com/org/api/pull/42",
            title="Fix auth",
            author="tony",
            state="open",
            updated_at=NOW,
            matched_paths=("src/auth/token.py",),
            reason="test reason",
        )
        g = CoordinationGuidance(
            effect="pause",
            urgency="warning",
            summary="tony has open PR #42",
            instruction="Pause edits.",
            confidence=85,
            evidence=(ev,),
        )
        result = _format_guidance(g)
        assert result["effect"] == "pause"
        assert result["urgency"] == "warning"
        assert result["confidence"] == 85
        assert len(result["evidence"]) == 1
        assert result["evidence"][0]["matched_paths"] == ["src/auth/token.py"]


class TestPrivacyBoundary:
    def test_returns_privacy_statements(self) -> None:
        boundary = _privacy_boundary()
        assert len(boundary) == 3
        assert any("configured repos" in s for s in boundary)
        assert any("unlabeled" in s for s in boundary)


class TestBuildCoordination:
    @pytest.mark.anyio()
    async def test_empty_cache_returns_empty_guidance(self) -> None:
        state = _state()
        result = await _build_coordination(state, repo="org/api", goal=None, paths=None, now=NOW)
        assert result["status"] == "ok"
        assert result["guidance"] == []
        assert "privacy_boundary" in result

    @pytest.mark.anyio()
    async def test_with_cached_signals(self) -> None:
        state = _state(signals=[_signal(42)])
        result = await _build_coordination(
            state, repo="org/api", goal=None, paths=["src/auth/token.py"], now=NOW
        )
        assert result["status"] == "ok"
        assert len(result["guidance"]) >= 1
        assert result["guidance"][0]["effect"] == "pause"

    @pytest.mark.anyio()
    async def test_refresh_on_stale_cache(self) -> None:
        state = _state()
        with patch("jurati.server.fetch_all_signals", return_value=[_signal(99)]) as mock_fetch:
            result = await _build_coordination(
                state, repo="org/api", goal=None, paths=["src/auth/token.py"], now=NOW
            )
            assert mock_fetch.called
            assert len(result["guidance"]) >= 1

    @pytest.mark.anyio()
    async def test_refresh_failure_uses_cached_data(self) -> None:
        state = _state(signals=[_signal(42)])
        state.signal_cache._last_refresh = None  # force refresh
        with patch("jurati.server.fetch_all_signals", side_effect=RuntimeError("network error")):
            result = await _build_coordination(
                state, repo="org/api", goal=None, paths=["src/auth/token.py"], now=NOW
            )
            assert result["status"] == "ok"
            assert len(result["guidance"]) >= 1

    @pytest.mark.anyio()
    async def test_summary_distinguishes_active_vs_parallel(self) -> None:
        sig = _signal(
            42,
            changed_paths=("src/billing/charge.py",),
            target_areas=("src/billing",),
        )
        state = _state(signals=[sig])
        result = await _build_coordination(
            state, repo="org/api", goal=None, paths=["src/auth/token.py"], now=NOW
        )
        assert "none affect" in result["summary"]


class TestServerStateDefault:
    def test_signal_cache_default(self) -> None:
        state = ServerState(
            config=JuratiConfig(remote_url="https://example.com/repo.git"),
            repo_path="/fake/repo",
            index=Index(),
            last_sync=NOW,
            sync_health=SyncHealth(last_success=NOW),
        )
        assert state.signal_cache.size == 0
        assert state.signal_cache.needs_refresh(now=NOW)
