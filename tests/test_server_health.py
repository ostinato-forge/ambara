"""Sync health tracking tests — exercise sync() behavior via mocked git layer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import anyio

from jurati.core.index import Index
from jurati.git.config import JuratiConfig
from jurati.server import ServerState, SyncHealth, sync

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


class TestSyncSuccess:
    @patch("jurati.server.load_index_from_repo")
    @patch("jurati.server.fetch_all")
    def test_resets_failures_after_success(
        self, mock_fetch: Any, mock_load: Any
    ) -> None:
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
    def test_success_response_includes_full_health(
        self, mock_fetch: Any, mock_load: Any
    ) -> None:
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
    def test_success_replaces_index(
        self, mock_fetch: Any, mock_load: Any
    ) -> None:
        state = _build_state()
        old_index = state.index
        new_index = Index()
        mock_load.return_value = new_index
        ctx = _FakeCtx(state)

        async def run() -> None:
            await sync(ctx=ctx)

        anyio.run(run)

        assert state.index is new_index
        assert state.index is not old_index


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

    @patch("jurati.server.fetch_all", side_effect=RuntimeError("network"))
    def test_records_error_message(self, mock_fetch: Any) -> None:
        state = _build_state()
        ctx = _FakeCtx(state)

        async def run() -> None:
            await sync(ctx=ctx)

        anyio.run(run)

        assert state.sync_health.last_error == "network"
        assert state.sync_health.last_failure is not None
