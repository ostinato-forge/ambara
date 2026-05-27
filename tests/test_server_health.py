"""Sync health tracking tests — exercise sync() behavior via mocked git layer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import anyio

from jurati.core.index import Index
from jurati.core.pr_signals import PRSignal
from jurati.git.config import JuratiConfig, PRSignalsConfig
from jurati.server import ServerState, SyncHealth, app_lifespan, sync

NOW = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)


def _build_state() -> ServerState:
    return ServerState(
        config=JuratiConfig(remote_url="https://example.com/repo.git"),
        repo_path="/fake/repo",
        index=Index(),
        last_sync=NOW,
        sync_health=SyncHealth(last_success=NOW),
    )


class _FakeCtx:
    def __init__(self, state: ServerState) -> None:
        self.request_context = type("RC", (), {"lifespan_context": state})()


def _run(coro: Any) -> Any:
    return anyio.from_thread.run(coro)


def _signal() -> PRSignal:
    return PRSignal(
        signal_id="github:org/api:pull:42",
        provider="github",
        repo="org/api",
        number=42,
        url="https://github.com/org/api/pull/42",
        title="Coordinate auth rollout",
        body_excerpt=None,
        author="alice",
        state="open",
        labels=("jurati",),
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(hours=1),
        merged_at=None,
        changed_paths=("src/auth/token.py",),
        target_areas=("src/auth",),
    )


class TestLifespanSnapshot:
    @patch("jurati.server.fetch_all_signals")
    @patch("jurati.server.load_index_from_repo")
    @patch("jurati.server.fetch_all")
    @patch("jurati.server.ensure_repo")
    @patch("jurati.server.load_config_from_env")
    def test_startup_snapshot_refreshes_configured_signals(
        self,
        mock_config: Any,
        mock_ensure: Any,
        mock_fetch: Any,
        mock_load: Any,
        mock_signals: Any,
    ) -> None:
        mock_config.return_value = JuratiConfig(
            remote_url="https://example.com/repo.git",
            pr_signals=PRSignalsConfig(repos=("org/api",)),
        )
        mock_ensure.return_value = "/fake/repo"
        mock_load.return_value = Index()
        mock_signals.return_value = [_signal()]

        async def capture() -> ServerState:
            async with app_lifespan(None) as state:  # type: ignore[arg-type]
                return state

        state = anyio.run(capture)

        assert state.signal_cache.size == 1
        assert state.signal_cache.last_refresh is not None
        assert state.signal_health.last_success is not None
        assert state.signal_health.last_error is None
        assert state.context_snapshot is not None
        assert len(state.context_snapshot.signals) == 1
        mock_fetch.assert_called_once()
        mock_signals.assert_called_once()


class TestSyncSuccess:
    @patch("jurati.server.load_index_from_repo")
    @patch("jurati.server.fetch_all")
    def test_resets_failures_after_success(self, mock_fetch: Any, mock_load: Any) -> None:
        state = _build_state()
        state.sync_health.consecutive_failures = 3
        state.sync_health.last_error = "prior error"
        mock_load.return_value = Index()
        ctx = _FakeCtx(state)

        async def run() -> dict[str, Any]:
            return await sync(ctx=ctx)

        result = anyio.run(run)

        assert result["status"] == "ok"
        assert state.sync_health.consecutive_failures == 0
        assert state.sync_health.last_error is None
        assert state.sync_health.last_success is not None

    @patch("jurati.server.load_index_from_repo")
    @patch("jurati.server.fetch_all")
    def test_success_response_includes_full_health(self, mock_fetch: Any, mock_load: Any) -> None:
        state = _build_state()
        mock_load.return_value = Index()
        ctx = _FakeCtx(state)

        async def run() -> dict[str, Any]:
            return await sync(ctx=ctx)

        result = anyio.run(run)

        health = result["health"]
        assert "last_success" in health
        assert "last_failure" in health
        assert "last_error" in health
        assert "consecutive_failures" in health
        assert health["consecutive_failures"] == 0

    @patch("jurati.server.load_index_from_repo")
    @patch("jurati.server.fetch_all")
    def test_success_replaces_index(self, mock_fetch: Any, mock_load: Any) -> None:
        state = _build_state()
        old_index = state.index
        new_index = Index()
        mock_load.return_value = new_index
        ctx = _FakeCtx(state)

        async def run() -> dict[str, Any]:
            return await sync(ctx=ctx)

        result = anyio.run(run)

        assert state.index is new_index
        assert state.index is not old_index
        assert state.context_snapshot is not None
        assert state.context_snapshot.index_generation == state._index_generation
        assert result["context_snapshot"]["available"] is True
        assert result["context_snapshot"]["current"] is True
        assert result["context_snapshot"]["availability"] == "fresh"
        assert result["context_snapshot"]["freshness"]["status"] == "fresh"
        assert result["context_snapshot"]["snapshot_index_generation"] == state._index_generation
        assert result["context_snapshot"]["entries_considered"] == 0

    @patch("jurati.server.fetch_all_signals", side_effect=RuntimeError("provider down"))
    @patch("jurati.server.load_index_from_repo")
    @patch("jurati.server.fetch_all")
    def test_success_reports_signal_refresh_failure(
        self,
        mock_fetch: Any,
        mock_load: Any,
        mock_signals: Any,
    ) -> None:
        state = _build_state()
        state.config = JuratiConfig(
            remote_url="https://example.com/repo.git",
            pr_signals=PRSignalsConfig(repos=("org/api",)),
        )
        mock_load.return_value = Index()
        ctx = _FakeCtx(state)

        async def run() -> dict[str, Any]:
            return await sync(ctx=ctx)

        result = anyio.run(run)

        assert result["status"] == "ok"
        signal_refresh = result["context_snapshot"]["signal_refresh"]
        assert signal_refresh["configured"] is True
        assert signal_refresh["baseline_available"] is False
        assert signal_refresh["last_error"] == "provider down"
        assert state.signal_health.consecutive_failures == 1
        mock_signals.assert_called_once()


class TestSyncFailure:
    @patch("jurati.server.fetch_all", side_effect=ConnectionError("refused"))
    def test_increments_consecutive_failures(self, mock_fetch: Any) -> None:
        state = _build_state()
        ctx = _FakeCtx(state)

        async def run() -> None:
            await sync(ctx=ctx)
            assert state.sync_health.consecutive_failures == 1
            await sync(ctx=ctx)
            assert state.sync_health.consecutive_failures == 2

        anyio.run(run)

    @patch("jurati.server.fetch_all", side_effect=ConnectionError("refused"))
    def test_preserves_last_good_index(self, mock_fetch: Any) -> None:
        state = _build_state()
        original_index = state.index
        ctx = _FakeCtx(state)

        async def run() -> dict[str, Any]:
            return await sync(ctx=ctx)

        result = anyio.run(run)

        assert result["status"] == "error"
        assert state.index is original_index

    @patch("jurati.server.fetch_all", side_effect=TimeoutError("timed out"))
    def test_failure_response_includes_full_health(self, mock_fetch: Any) -> None:
        state = _build_state()
        ctx = _FakeCtx(state)

        async def run() -> dict[str, Any]:
            return await sync(ctx=ctx)

        result = anyio.run(run)

        health = result["health"]
        assert "last_success" in health
        assert "last_failure" in health
        assert health["last_error"] == "timed out"
        assert health["consecutive_failures"] == 1

    @patch("jurati.server.fetch_all", side_effect=TimeoutError("timed out"))
    def test_failure_response_tells_agent_to_stop(self, mock_fetch: Any) -> None:
        state = _build_state()
        ctx = _FakeCtx(state)

        async def run() -> dict[str, Any]:
            return await sync(ctx=ctx)

        result = anyio.run(run)

        assert result["status"] == "error"
        assert "Do not call context()" in result["agent_instruction"]
        assert "team context is unavailable" in result["agent_instruction"]
        assert "local-only context" in result["agent_instruction"]

    @patch("jurati.server.fetch_all", side_effect=RuntimeError("network"))
    def test_records_error_message(self, mock_fetch: Any) -> None:
        state = _build_state()
        ctx = _FakeCtx(state)

        async def run() -> None:
            await sync(ctx=ctx)

        anyio.run(run)

        assert state.sync_health.last_error == "network"
        assert state.sync_health.last_failure is not None
