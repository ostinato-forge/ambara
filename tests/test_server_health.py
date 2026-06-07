# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Sync health tracking tests — exercise sync() behavior via mocked git layer."""

from __future__ import annotations

import json
import logging
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import anyio

import ambara.server_signals as server_signals
from ambara.core.index import Index
from ambara.core.pr_signals import PRSignal
from ambara.git.config import AmbaraConfig, PRSignalsConfig
from ambara.providers.cache import SignalCache
from ambara.server import ServerState, SyncHealth, app_lifespan, sync
from ambara.server_snapshot import (
    _signal_baseline_unavailable,
    _source_input_baseline_unavailable,
    build_context_snapshot,
    compiler_health_for_context,
    refresh_context_snapshot,
    render_coordination_from_snapshot,
    snapshot_coverage,
    snapshot_signal_inputs,
    snapshot_source_inputs,
    snapshot_status_payload,
    startup_source_health_payload,
)
from ambara.server_source_inputs import signal_inputs_for_state, source_inputs_for_state
from ambara.server_state import SourceRefreshHealth
from ambara.server_types import LegacySignalFetcher, SignalFetcher
from ambara.sources.adapters import source_artifact_from_pr_signal
from ambara.sources.health import SourceHealth, SourceHealthStatus
from ambara.sources.inspect import SourceInspection, SourceInspectionReport
from ambara.sources.runtime import SourceRuntimeReport
from ambara.sources.types import SourceCategory, SourceInstanceConfig

NOW = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)


def _build_state() -> ServerState:
    return ServerState(
        config=AmbaraConfig(remote_url="https://example.com/repo.git"),
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


def _signal(now: datetime | None = None) -> PRSignal:
    current_now = now or datetime.now(UTC)
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
        labels=("ambara",),
        created_at=current_now - timedelta(days=1),
        updated_at=current_now - timedelta(hours=1),
        merged_at=None,
        changed_paths=("src/auth/token.py",),
        target_areas=("src/auth",),
    )


def _source_report_for_signals(*signals: PRSignal) -> SourceInspectionReport:
    config = SourceInstanceConfig(
        id="source-reviews",
        provider="github",
        category=SourceCategory.FORGE_REVIEW,
        selectors={"repos": ("org/api",)},
    )
    return SourceInspectionReport(
        sources=(
            SourceInspection(
                config=config,
                provider_display_name="GitHub",
                health=SourceHealth(
                    source_instance_id=config.id,
                    status=SourceHealthStatus.FRESH,
                    last_success=NOW,
                ),
                artifacts=tuple(
                    source_artifact_from_pr_signal(
                        signal,
                        source_instance_id=config.id,
                        fetched_at=NOW,
                    )
                    for signal in signals
                ),
            ),
        ),
        provider_ids=("github",),
    )


async def _run_inline(function: Any) -> Any:
    return function()


def _write_fixture(path: Path, *, title: str = "Coordinate auth rollout") -> None:
    path.write_text(
        json.dumps(
            {
                "signals": [
                    {
                        "repo": "org/api",
                        "number": 42,
                        "url": "https://github.com/org/api/pull/42",
                        "title": title,
                        "body_excerpt": "Review the API handoff before continuing.",
                        "author": "alice@example.com",
                        "state": "open",
                        "labels": ["ambara"],
                        "created_at": NOW.isoformat(),
                        "updated_at": NOW.isoformat(),
                        "changed_paths": ["src/auth/token.py"],
                    }
                ]
            }
        )
        + "\n"
    )


class TestLifespanSnapshot:
    @patch("ambara.server_signals.fetch_source_runtime_report")
    @patch("ambara.server.load_index_from_repo")
    @patch("ambara.server.get_main_tree_hash", return_value="fake-tree-hash")
    @patch("ambara.server.fetch_all")
    @patch("ambara.server.ensure_repo")
    @patch("ambara.server.load_config_from_env")
    def test_startup_snapshot_refreshes_configured_signals(
        self,
        mock_config: Any,
        mock_ensure: Any,
        mock_fetch: Any,
        _mock_tree_hash: Any,
        mock_load: Any,
        mock_source_report: Any,
    ) -> None:
        mock_config.return_value = AmbaraConfig(
            remote_url="https://example.com/repo.git",
            pr_signals=PRSignalsConfig(repos=("org/api",)),
        )
        mock_ensure.return_value = "/fake/repo"
        mock_load.return_value = Index()
        signal = _signal()
        mock_source_report.return_value = SourceRuntimeReport(
            legacy_signals=(signal,),
            source_report=_source_report_for_signals(signal),
        )

        async def capture() -> ServerState:
            async with app_lifespan(None) as state:  # type: ignore[arg-type]
                return state

        state = anyio.run(capture)

        assert state.legacy_signal_cache.size == 0
        assert state.legacy_signal_cache.last_refresh is None
        assert state.source_report_last_refresh is not None
        assert state.source_health.last_success is not None
        assert state.source_health.last_error is None
        assert state.cache.snapshot is not None
        assert len(state.cache.snapshot.legacy_signals) == 0
        assert state.cache.snapshot.legacy_signals == ()
        assert len(state.cache.snapshot.source_artifacts) == 1
        mock_fetch.assert_called_once()
        mock_source_report.assert_called_once()


class TestSourceHealthAlias:
    def test_server_state_stores_source_health_natively(self) -> None:
        state_fields = {field.name for field in fields(ServerState)}

        assert "source_health" in state_fields
        assert "signal_health" not in state_fields

    def test_source_health_preserves_signal_health_compatibility_alias(self) -> None:
        state = _build_state()

        state.source_health.last_error = "source unavailable"

        assert state.source_health is state.source_health
        assert state.source_health.last_error == "source unavailable"

        state.source_health = SourceRefreshHealth(last_error="legacy alias updated")

        assert state.source_health is state.source_health
        assert state.source_health.last_error == "legacy alias updated"


class TestLegacySignalCacheAlias:
    def test_server_state_stores_legacy_signal_cache_natively(self) -> None:
        state_fields = {field.name for field in fields(ServerState)}

        assert "legacy_signal_cache" in state_fields
        assert "signal_cache" not in state_fields

    def test_legacy_signal_cache_preserves_signal_cache_compatibility_alias(self) -> None:
        state = _build_state()

        state.legacy_signal_cache.update([_signal()], now=NOW)

        assert state.legacy_signal_cache is state.legacy_signal_cache
        assert state.legacy_signal_cache.size == 1

        replacement = SignalCache(recency_days=90)
        state.legacy_signal_cache = replacement

        assert state.legacy_signal_cache is replacement
        assert state.legacy_signal_cache.size == 0

    def test_legacy_signal_cache_accepts_signal_cache_constructor_alias(self) -> None:
        cache = SignalCache(recency_days=90)
        cache.update([_signal()], now=NOW)

        state = ServerState(
            config=AmbaraConfig(remote_url="https://example.com/repo.git"),
            repo_path="/fake/repo",
            index=Index(),
            last_sync=NOW,
            sync_health=SyncHealth(last_success=NOW),
            legacy_signal_cache=cache,
        )

        assert state.legacy_signal_cache is cache
        assert state.legacy_signal_cache.size == 1


class TestSourceRefreshCompatibility:
    def test_source_input_baseline_preserves_signal_compatibility_alias(self) -> None:
        state = _build_state()
        state.config = AmbaraConfig(
            remote_url="https://example.com/repo.git",
            pr_signals=PRSignalsConfig(repos=("org/api",)),
        )

        assert _source_input_baseline_unavailable(state)
        assert _signal_baseline_unavailable(state) == _source_input_baseline_unavailable(state)

    def test_legacy_signal_fetcher_preserves_signal_fetcher_compatibility_alias(
        self,
    ) -> None:
        assert SignalFetcher is LegacySignalFetcher

    def test_source_inputs_configured_preserves_signal_compatibility_alias(self) -> None:
        config = PRSignalsConfig(repos=("org/api",))

        assert server_signals.source_inputs_configured(config)
        assert server_signals.signals_configured(config) == (
            server_signals.source_inputs_configured(config)
        )

    def test_legacy_refresh_signal_cache_name_delegates_to_source_inputs(self) -> None:
        state = _build_state()

        async def run() -> None:
            with patch(
                "ambara.server_signals.refresh_source_inputs",
                new_callable=AsyncMock,
            ) as refresh:
                await server_signals.refresh_signal_cache(
                    state,
                    config=state.config.pr_signals,
                    now=NOW,
                    fetch_signals=None,
                    run_blocking=_run_inline,
                    logger=logging.getLogger("test"),
                    failure_log_message="refresh failed",
                )

            refresh.assert_awaited_once()

        anyio.run(run)


class TestSourceRefreshSnapshot:
    def test_source_inputs_for_state_preserves_signal_compatibility_alias(self) -> None:
        state = _build_state()
        legacy_signal = _signal()
        state.legacy_signal_cache.update([legacy_signal], now=NOW)

        assert source_inputs_for_state(state) == (legacy_signal,)
        assert signal_inputs_for_state(state) == source_inputs_for_state(state)

        state.source_report = _source_report_for_signals(_signal())
        state.source_report_last_refresh = NOW

        assert len(source_inputs_for_state(state)) == 1
        assert source_inputs_for_state(state)[0].source_instance_id == "source-reviews"
        assert signal_inputs_for_state(state) == source_inputs_for_state(state)

    def test_authoritative_source_report_suppresses_legacy_snapshot_signals(self) -> None:
        state = _build_state()
        state.config = AmbaraConfig(
            remote_url="https://example.com/repo.git",
            pr_signals=PRSignalsConfig(repos=("org/api",)),
        )
        state.legacy_signal_cache.update([_signal()], now=NOW)
        state.source_report = _source_report_for_signals(_signal())
        state.source_report_last_refresh = NOW

        snapshot = build_context_snapshot(state, now=NOW)

        assert snapshot.source_artifacts_authoritative is True
        assert len(snapshot.source_artifacts) == 1
        assert snapshot.legacy_signals == ()
        assert snapshot.legacy_signals == ()
        assert snapshot_source_inputs(snapshot) == snapshot.source_artifacts
        assert snapshot_signal_inputs(snapshot) == snapshot_source_inputs(snapshot)
        coverage = snapshot_coverage(snapshot)
        assert coverage["signals_considered"] == 1
        assert coverage["source_artifacts_considered"] == 1
        assert coverage["legacy_signals_considered"] == 0

    def test_refresh_context_snapshot_reports_fresh_fixture_source(
        self,
        tmp_path: Path,
    ) -> None:
        fixture = tmp_path / "signals.json"
        _write_fixture(fixture)
        state = _build_state()
        state.config = AmbaraConfig(
            remote_url="https://example.com/repo.git",
            pr_signals=PRSignalsConfig(
                repos=("org/api",),
                fixture_path=str(fixture),
                recency_days=90,
            ),
        )

        async def run() -> tuple[Any, dict[str, Any]]:
            snapshot = await refresh_context_snapshot(
                state,
                now=NOW,
                run_blocking=_run_inline,
                logger=logging.getLogger("test"),
            )
            return snapshot, snapshot_status_payload(state, now=NOW)

        snapshot, payload = anyio.run(run)
        assert payload["source_refresh"] == payload["signal_refresh"]
        source_refresh = payload["source_refresh"]["sources"][0]
        source_only_snapshot = replace(snapshot, legacy_signals=())
        coordination = render_coordination_from_snapshot(
            source_only_snapshot,
            state,
            repo="org/api",
            goal=None,
            paths=["src/auth/token.py"],
            now=NOW,
        )

        assert payload["availability"] == "fresh"
        assert state.legacy_signal_cache.size == 0
        assert state.source_report_last_refresh == NOW
        assert len(snapshot.source_artifacts) == 1
        assert len(source_only_snapshot.legacy_signals) == 0
        assert coordination["guidance"][0]["effect"] == "pause"
        assert payload["source_cache_size"] == 1
        assert payload["source_cache_source_count"] == 1
        assert payload["source_cache_last_success"] == NOW.isoformat()
        assert payload["source_cache_last_refresh"] == NOW.isoformat()
        assert payload["source_cache_needs_refresh"] is False
        assert payload["legacy_signal_cache_size"] == 0
        assert payload["legacy_signal_cache_last_refresh"] is None
        assert payload["legacy_signal_cache_needs_refresh"] is True
        assert payload["signal_cache_size"] == payload["source_cache_size"]
        assert payload["signal_cache_last_refresh"] == payload["source_cache_last_refresh"]
        assert payload["signal_cache_needs_refresh"] == payload["source_cache_needs_refresh"]
        assert payload["source_refresh"]["last_refresh"] == NOW.isoformat()
        assert payload["source_refresh"]["needs_refresh"] is False
        assert source_refresh["id"] == "legacy-fixture-signals"
        assert source_refresh["provider"] == "fixture"
        assert source_refresh["status"] == "fresh"
        assert source_refresh["artifact_count"] == 1
        assert source_refresh["baseline_available"] is True
        assert startup_source_health_payload(state) is None

    def test_source_ttl_expiry_marks_status_and_startup_health_stale(self) -> None:
        state = _build_state()
        config = SourceInstanceConfig(
            id="repo-reviews",
            provider="github",
            category=SourceCategory.FORGE_REVIEW,
            selectors={"repos": ("org/api",)},
        )
        state.source_report = SourceInspectionReport(
            sources=(
                SourceInspection(
                    config=config,
                    provider_display_name="GitHub",
                    health=SourceHealth(
                        source_instance_id=config.id,
                        status=SourceHealthStatus.FRESH,
                        last_success=NOW,
                        stale_after=NOW + timedelta(seconds=60),
                    ),
                    artifacts=(
                        source_artifact_from_pr_signal(
                            _signal(),
                            source_instance_id=config.id,
                            fetched_at=NOW,
                        ),
                    ),
                ),
            ),
            provider_ids=("github",),
        )
        state.source_report_last_refresh = NOW

        fresh_health = startup_source_health_payload(
            state,
            now=NOW + timedelta(seconds=30),
        )
        payload = snapshot_status_payload(state, now=NOW + timedelta(seconds=120))
        source_health = startup_source_health_payload(
            state,
            now=NOW + timedelta(seconds=120),
        )

        assert server_signals.source_report_needs_refresh(
            state,
            now=NOW + timedelta(seconds=120),
        )
        assert fresh_health is None
        assert payload["source_cache_needs_refresh"] is True
        assert payload["source_refresh"]["needs_refresh"] is True
        assert payload["source_refresh"]["sources"][0]["status"] == "stale"
        assert source_health is not None
        assert source_health["stale"] == 1
        assert source_health["sources"] == [
            {
                "id": "repo-reviews",
                "provider": "github",
                "status": "stale",
                "baseline_available": True,
                "rate_limited": False,
            }
        ]

    def test_partial_source_error_status_omits_raw_provider_detail(self) -> None:
        state = _build_state()
        raw_error = "page 2 timed out while reading /private/team/notes"
        config = SourceInstanceConfig(
            id="repo-reviews",
            provider="github",
            category=SourceCategory.FORGE_REVIEW,
            selectors={"repos": ("org/api",)},
        )
        state.source_report = SourceInspectionReport(
            sources=(
                SourceInspection(
                    config=config,
                    provider_display_name="GitHub",
                    health=SourceHealth(
                        source_instance_id=config.id,
                        status=SourceHealthStatus.STALE,
                        last_success=NOW,
                        last_failure=NOW,
                        consecutive_failures=1,
                        message="partial source refresh failed",
                    ),
                    artifacts=(
                        source_artifact_from_pr_signal(
                            _signal(),
                            source_instance_id=config.id,
                            fetched_at=NOW,
                        ),
                    ),
                    partial_errors=(raw_error,),
                ),
            ),
            provider_ids=("github",),
        )
        state.source_report_last_refresh = NOW

        payload = snapshot_status_payload(state, now=NOW)
        source_health = startup_source_health_payload(state, now=NOW)
        rendered = json.dumps({"payload": payload, "source_health": source_health})

        assert payload["source_refresh"]["sources"][0]["status"] == "stale"
        assert payload["source_refresh"]["sources"][0]["last_error"] == (
            "partial source refresh failed"
        )
        assert source_health is not None
        assert source_health["sources"][0]["status"] == "stale"
        assert "partial source refresh failed" in rendered
        assert raw_error not in rendered
        assert "/private/team/notes" not in rendered

    def test_rate_limited_source_status_uses_generic_boolean(self) -> None:
        state = _build_state()
        raw_hint = "Retry-After: 60 for /private/team/source"
        config = SourceInstanceConfig(
            id="repo-reviews",
            provider="github",
            category=SourceCategory.FORGE_REVIEW,
            selectors={"repos": ("org/api",)},
        )
        state.source_report = SourceInspectionReport(
            sources=(
                SourceInspection(
                    config=config,
                    provider_display_name="GitHub",
                    health=SourceHealth(
                        source_instance_id=config.id,
                        status=SourceHealthStatus.STALE,
                        last_success=NOW,
                        last_failure=NOW,
                        consecutive_failures=1,
                        message="source refresh rate limited",
                    ),
                    rate_limited=True,
                ),
            ),
            provider_ids=("github",),
        )
        state.source_report_last_refresh = NOW

        payload = snapshot_status_payload(state, now=NOW)
        source_health = startup_source_health_payload(state, now=NOW)
        rendered = json.dumps({"payload": payload, "source_health": source_health})

        assert payload["source_refresh"]["sources"][0]["status"] == "stale"
        assert payload["source_refresh"]["sources"][0]["rate_limited"] is True
        assert source_health is not None
        assert source_health["sources"][0]["rate_limited"] is True
        assert "source refresh rate limited" in rendered
        assert raw_hint not in rendered
        assert "/private/team/source" not in rendered

    def test_refresh_context_snapshot_reports_unavailable_fixture_without_baseline(
        self,
        tmp_path: Path,
    ) -> None:
        missing = tmp_path / "missing.json"
        state = _build_state()
        state.config = AmbaraConfig(
            remote_url="https://example.com/repo.git",
            pr_signals=PRSignalsConfig(
                repos=("org/api",),
                fixture_path=str(missing),
                recency_days=90,
            ),
        )

        async def run() -> dict[str, Any]:
            await refresh_context_snapshot(
                state,
                now=NOW,
                run_blocking=_run_inline,
                logger=logging.getLogger("test"),
            )
            return snapshot_status_payload(state, now=NOW)

        payload = anyio.run(run)
        signal_refresh = payload["signal_refresh"]
        source_refresh_status = payload["source_refresh"]
        source_refresh = source_refresh_status["sources"][0]

        assert payload["availability"] == "unavailable"
        assert payload["source_cache_size"] == 0
        assert payload["source_cache_last_refresh"] == NOW.isoformat()
        assert payload["source_cache_needs_refresh"] is False
        assert payload["legacy_signal_cache_size"] == 0
        assert payload["signal_cache_size"] == payload["source_cache_size"]
        assert payload["signal_cache_last_refresh"] == payload["source_cache_last_refresh"]
        assert payload["signal_cache_needs_refresh"] == payload["source_cache_needs_refresh"]
        assert source_refresh_status == signal_refresh
        assert signal_refresh["baseline_available"] is False
        assert signal_refresh["last_error"] == "Fixture: source refresh failed"
        assert source_refresh["status"] == "unavailable"
        assert source_refresh["baseline_available"] is False
        assert str(missing) not in json.dumps(payload)

        startup_health = compiler_health_for_context(state, include_source_inputs=True)
        legacy_startup_health = compiler_health_for_context(state, include_signals=True)
        assert legacy_startup_health == startup_health
        assert startup_health.last_error == (
            "configured source unavailable; run ambara sources doctor for details"
        )
        assert str(missing) not in startup_health.last_error

        source_health = startup_source_health_payload(state)
        assert source_health is not None
        assert source_health["configured"] == 1
        assert source_health["unavailable"] == 1
        assert source_health["sources"] == [
            {
                "id": "legacy-fixture-signals",
                "provider": "fixture",
                "status": "unavailable",
                "baseline_available": False,
                "rate_limited": False,
            }
        ]
        source_health_raw = json.dumps(source_health)
        assert "source refresh failed" not in source_health_raw
        assert str(missing) not in source_health_raw


class TestSyncSuccess:
    @patch("ambara.server.load_index_from_repo")
    @patch("ambara.server.get_main_tree_hash", return_value="fake-tree-hash")
    @patch("ambara.server.fetch_all")
    def test_resets_failures_after_success(
        self, mock_fetch: Any, _mock_tree_hash: Any, mock_load: Any
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

    @patch("ambara.server.load_index_from_repo")
    @patch("ambara.server.get_main_tree_hash", return_value="fake-tree-hash")
    @patch("ambara.server.fetch_all")
    def test_success_response_includes_full_health(
        self, mock_fetch: Any, _mock_tree_hash: Any, mock_load: Any
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

    @patch("ambara.server.load_index_from_repo")
    @patch("ambara.server.get_main_tree_hash", return_value="fake-tree-hash")
    @patch("ambara.server.fetch_all")
    def test_success_replaces_index(
        self, mock_fetch: Any, _mock_tree_hash: Any, mock_load: Any
    ) -> None:
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
        assert state.cache.snapshot is not None
        assert state.cache.snapshot.index_generation == state.cache.generation
        assert result["context_snapshot"]["available"] is True
        assert result["context_snapshot"]["current"] is True
        assert result["context_snapshot"]["availability"] == "fresh"
        assert result["context_snapshot"]["freshness"]["status"] == "fresh"
        assert result["context_snapshot"]["snapshot_index_generation"] == state.cache.generation
        assert result["context_snapshot"]["entries_considered"] == 0

    @patch(
        "ambara.server_signals.fetch_source_runtime_report",
        side_effect=RuntimeError("provider down"),
    )
    @patch("ambara.server.load_index_from_repo")
    @patch("ambara.server.get_main_tree_hash", return_value="fake-tree-hash")
    @patch("ambara.server.fetch_all")
    def test_success_reports_signal_refresh_failure(
        self,
        mock_fetch: Any,
        _mock_tree_hash: Any,
        mock_load: Any,
        mock_source_report: Any,
    ) -> None:
        state = _build_state()
        state.config = AmbaraConfig(
            remote_url="https://example.com/repo.git",
            pr_signals=PRSignalsConfig(repos=("org/api",)),
        )
        mock_load.return_value = Index()
        ctx = _FakeCtx(state)

        async def run() -> dict[str, Any]:
            return await sync(ctx=ctx)

        result = anyio.run(run)

        assert result["status"] == "ok"
        context_snapshot = result["context_snapshot"]
        assert context_snapshot["source_refresh"] == context_snapshot["signal_refresh"]
        source_refresh = context_snapshot["source_refresh"]
        assert source_refresh["configured"] is True
        assert source_refresh["baseline_available"] is False
        assert source_refresh["last_error"] == "provider down"
        assert state.source_health.consecutive_failures == 1
        mock_source_report.assert_called_once()


class TestSyncFailure:
    @patch("ambara.server.fetch_all", side_effect=ConnectionError("refused"))
    def test_increments_consecutive_failures(self, mock_fetch: Any) -> None:
        state = _build_state()
        ctx = _FakeCtx(state)

        async def run() -> None:
            await sync(ctx=ctx)
            assert state.sync_health.consecutive_failures == 1
            await sync(ctx=ctx)
            assert state.sync_health.consecutive_failures == 2

        anyio.run(run)

    @patch("ambara.server.fetch_all", side_effect=ConnectionError("refused"))
    def test_preserves_last_good_index(self, mock_fetch: Any) -> None:
        state = _build_state()
        original_index = state.index
        ctx = _FakeCtx(state)

        async def run() -> dict[str, Any]:
            return await sync(ctx=ctx)

        result = anyio.run(run)

        assert result["status"] == "error"
        assert state.index is original_index

    @patch("ambara.server.fetch_all", side_effect=TimeoutError("timed out"))
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

    @patch("ambara.server.fetch_all", side_effect=TimeoutError("timed out"))
    def test_failure_response_tells_agent_to_stop(self, mock_fetch: Any) -> None:
        state = _build_state()
        ctx = _FakeCtx(state)

        async def run() -> dict[str, Any]:
            return await sync(ctx=ctx)

        result = anyio.run(run)

        assert result["status"] == "error"
        assert "unavailable" in result["agent_instruction"]

    @patch("ambara.server.fetch_all", side_effect=RuntimeError("network"))
    def test_records_error_message(self, mock_fetch: Any) -> None:
        state = _build_state()
        ctx = _FakeCtx(state)

        async def run() -> None:
            await sync(ctx=ctx)

        anyio.run(run)

        assert state.sync_health.last_error == "network"
        assert state.sync_health.last_failure is not None
