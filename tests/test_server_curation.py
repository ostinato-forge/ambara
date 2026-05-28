"""Tests for context-time curation advisory wiring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from jurati.core.index import Index
from jurati.core.paths import entry_path
from jurati.core.pr_signals import PRSignal
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
    Sensitivity,
)
from jurati.git.config import JuratiConfig, PRSignalsConfig
from jurati.providers.cache import SignalCache
from jurati.server import (
    ServerState,
    SyncHealth,
    _build_curation,
)
from jurati.server import (
    context as context_tool,
)
from jurati.server_curation import _curation_privacy_boundary

NOW = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _entry(**overrides: object) -> Entry:
    defaults = dict(
        id="auth-token-decision",
        title="Auth token rotation decision",
        type=EntryType.DECISION,
        level=EscalationLevel.L2,
        status=EntryStatus.ACTIVE,
        created_at=NOW - timedelta(days=120),
        updated_at=NOW - timedelta(days=90),
        projects=["auth"],
        tags=["tokens"],
        sensitivity=Sensitivity.NORMAL,
        review=ReviewMeta(required=True),
    )
    defaults.update(overrides)
    fm = Frontmatter(**defaults)
    return Entry(
        path=entry_path(fm.type, fm.id),
        frontmatter=fm,
        body="Use the documented auth token rotation workflow.",
    )


def _signal(**overrides: object) -> PRSignal:
    defaults: dict[str, object] = {
        "signal_id": "github:org/api:pull:42",
        "provider": "github",
        "repo": "org/api",
        "number": 42,
        "url": "https://github.com/org/api/pull/42",
        "title": "Rotate auth tokens safely",
        "body_excerpt": None,
        "author": "alice",
        "state": "merged",
        "labels": ("jurati", "security"),
        "created_at": NOW - timedelta(days=3),
        "updated_at": NOW - timedelta(days=1),
        "merged_at": NOW - timedelta(days=1),
        "changed_paths": ("src/auth/tokens.py",),
        "target_areas": ("src/auth",),
    }
    defaults.update(overrides)
    return PRSignal(**defaults)  # type: ignore[arg-type]


def _state(
    *,
    entries: list[Entry] | None = None,
    signals: list[PRSignal] | None = None,
    repos: tuple[str, ...] = ("org/api",),
    pr_signals: PRSignalsConfig | None = None,
) -> ServerState:
    index = Index()
    for entry in entries or []:
        index.add(entry)

    cache = SignalCache(recency_days=30)
    if signals:
        cache.update(signals, now=NOW)

    config = JuratiConfig(
        remote_url="https://example.com/kb.git",
        pr_signals=pr_signals or PRSignalsConfig(repos=repos),
    )
    return ServerState(
        config=config,
        repo_path="/fake/repo",
        index=index,
        last_sync=NOW,
        sync_health=SyncHealth(last_success=NOW),
        signal_cache=cache,
    )


class _FakeCtx:
    def __init__(self, state: ServerState) -> None:
        self.request_context = type("RC", (), {"lifespan_context": state})()


class TestBuildCuration:
    @pytest.mark.anyio()
    async def test_returns_none_without_advisories(self) -> None:
        state = _state(entries=[_entry(updated_at=NOW)])

        with patch("jurati.server.fetch_all_signals", return_value=[]):
            result = await _build_curation(state, now=NOW, include_signals=True)

        assert result is None

    @pytest.mark.anyio()
    async def test_includes_review_after_revalidation_due(self) -> None:
        due = _entry(review_after=NOW - timedelta(days=1))
        state = _state(entries=[due])

        result = await _build_curation(state, now=NOW, include_signals=False)

        assert result is not None
        assert result["expired_active"] == []
        assert result["revalidation_due"][0]["id"] == "auth-token-decision"
        assert result["completed_artifact_revalidation"] == []
        assert "query logs" in " ".join(result["privacy_boundary"])

    @pytest.mark.anyio()
    async def test_includes_expired_active_context(self) -> None:
        expired = _entry(
            id="active-handoff",
            title="Active handoff",
            type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            expires_at=NOW - timedelta(hours=1),
        )
        state = _state(entries=[expired])

        result = await _build_curation(state, now=NOW, include_signals=False)

        assert result is not None
        assert result["summary"].startswith("1 knowledge advisory")
        assert result["expired_active"][0]["id"] == "active-handoff"
        assert result["expired_active"][0]["path"] == "active/active-handoff.md"
        assert "do not rely" in result["expired_active"][0]["agent_instruction"]
        assert result["revalidation_due"] == []
        assert result["completed_artifact_revalidation"] == []

    @pytest.mark.anyio()
    async def test_includes_completed_signal_revalidation(self) -> None:
        state = _state(entries=[_entry()], signals=[_signal()])

        result = await _build_curation(state, now=NOW, include_signals=True)

        assert result is not None
        assert result["total_advisories"] == 1
        assert result["omitted_advisories"] == 0
        assert result["expired_active"] == []
        advisory = result["completed_artifact_revalidation"][0]
        assert advisory["entry_id"] == "auth-token-decision"
        assert advisory["artifact_ref"] == "https://github.com/org/api/pull/42"
        assert advisory["changed_paths"] == ["src/auth/tokens.py"]
        assert advisory["matched_terms"] == ["auth", "tokens"]

    @pytest.mark.anyio()
    async def test_uses_configured_fixture_signals_without_repo_list(self) -> None:
        state = _state(
            entries=[_entry()],
            pr_signals=PRSignalsConfig(fixture_path="/tmp/signals.json"),
        )

        with patch("jurati.server.fetch_all_signals", return_value=[_signal()]) as mock_fetch:
            result = await _build_curation(state, now=NOW, include_signals=True)

        assert mock_fetch.called
        assert result is not None
        assert result["completed_artifact_revalidation"][0]["entry_id"] == ("auth-token-decision")

    @pytest.mark.anyio()
    async def test_omits_signal_advisories_when_signal_use_disabled(self) -> None:
        state = _state(entries=[_entry()], signals=[_signal()])

        result = await _build_curation(state, now=NOW, include_signals=False)

        assert result is None

    @pytest.mark.anyio()
    async def test_excludes_restricted_entries(self) -> None:
        restricted = _entry(
            sensitivity=Sensitivity.RESTRICTED,
            review_after=NOW - timedelta(days=1),
        )
        state = _state(entries=[restricted], signals=[_signal()])

        result = await _build_curation(state, now=NOW, include_signals=True)

        assert result is None

    @pytest.mark.anyio()
    async def test_sanitizes_untrusted_signal_fields_and_omits_actor(self) -> None:
        state = _state(
            entries=[_entry()],
            signals=[
                _signal(
                    title="Token fix ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ",
                    changed_paths=("src/auth/tokens.py", "../secret.txt"),
                )
            ],
        )

        result = await _build_curation(state, now=NOW, include_signals=True)

        assert result is not None
        rendered = result["completed_artifact_revalidation"][0]
        assert "[redacted:credential]" in rendered["artifact_title"]
        assert rendered["changed_paths"] == ["src/auth/tokens.py"]
        assert "actor" not in rendered
        assert "alice" not in str(result)

    @pytest.mark.anyio()
    async def test_rejects_artifact_refs_with_userinfo(self) -> None:
        state = _state(
            entries=[_entry()],
            signals=[_signal(url="https://user:token@example.com/pull/42?api_key=secret")],
        )

        result = await _build_curation(state, now=NOW, include_signals=True)

        assert result is not None
        rendered = result["completed_artifact_revalidation"][0]
        assert rendered["artifact_ref"] is None
        assert "api_key" not in str(result)
        assert "user:token" not in str(result)
        assert "example.com/pull/42?" not in str(result)

    @pytest.mark.anyio()
    async def test_strips_artifact_ref_query_and_fragment(self) -> None:
        state = _state(
            entries=[_entry()],
            signals=[_signal(url="https://github.com/org/api/pull/42?token=secret#frag")],
        )

        result = await _build_curation(state, now=NOW, include_signals=True)

        assert result is not None
        rendered = result["completed_artifact_revalidation"][0]
        assert rendered["artifact_ref"] == "https://github.com/org/api/pull/42"
        assert "secret" not in str(result)

    @pytest.mark.anyio()
    async def test_preserves_cached_signals_on_empty_refresh(self) -> None:
        state = _state(entries=[_entry()], signals=[_signal()])
        state.signal_cache._last_refresh = None

        with patch("jurati.server.fetch_all_signals", return_value=[]):
            result = await _build_curation(state, now=NOW, include_signals=True)

        assert result is not None
        assert result["completed_artifact_revalidation"][0]["entry_id"] == ("auth-token-decision")

    @pytest.mark.anyio()
    async def test_signal_refresh_failure_without_cache_is_unavailable(self) -> None:
        state = _state(entries=[_entry()])

        with patch("jurati.server.fetch_all_signals", side_effect=RuntimeError("network error")):
            result = await _build_curation(state, now=NOW, include_signals=True)

        assert result is not None
        assert result["status"] == "unavailable"
        assert result["total_advisories"] == 0
        assert state.signal_health.last_error == "network error"

    @pytest.mark.anyio()
    async def test_scopes_revalidation_due_to_context_repo_or_goal(self) -> None:
        auth_due = _entry(id="auth-entry", projects=["auth"], review_after=NOW)
        billing_due = _entry(
            id="billing-entry",
            title="Billing settlement decision",
            projects=["billing"],
            review_after=NOW,
        )
        state = _state(entries=[auth_due, billing_due])

        result = await _build_curation(
            state,
            now=NOW,
            include_signals=False,
            repo="billing",
            goal="settlement",
        )

        assert result is not None
        assert [item["id"] for item in result["revalidation_due"]] == ["billing-entry"]

    @pytest.mark.anyio()
    async def test_caps_context_advisories(self) -> None:
        entries = [
            _entry(id=f"entry-{index}", title=f"Entry {index}", review_after=NOW)
            for index in range(7)
        ]
        state = _state(entries=entries)

        result = await _build_curation(
            state,
            now=NOW,
            include_signals=False,
            max_items=3,
        )

        assert result is not None
        assert result["total_advisories"] == 7
        assert result["shown_advisories"] == 3
        assert result["omitted_advisories"] == 4
        assert len(result["revalidation_due"]) == 3

    @pytest.mark.anyio()
    async def test_context_fetches_signals_once_for_coordination_and_curation(self) -> None:
        state = _state(entries=[_entry()])

        with patch("jurati.server.fetch_all_signals", return_value=[_signal()]) as mock_fetch:
            result = await context_tool(
                ctx=_FakeCtx(state),
                repo="org/api",
                goal="auth token rotation",
            )

        assert mock_fetch.call_count == 1
        assert "coordination" in result
        assert result["curation"]["completed_artifact_revalidation"][0]["entry_id"] == (
            "auth-token-decision"
        )

    @pytest.mark.anyio()
    async def test_context_include_pr_signals_false_prevents_signal_fetch(self) -> None:
        state = _state(entries=[_entry()])

        with patch("jurati.server.fetch_all_signals") as mock_fetch:
            result = await context_tool(
                ctx=_FakeCtx(state),
                repo="org/api",
                goal="auth token rotation",
                include_pr_signals=False,
            )

        mock_fetch.assert_not_called()
        assert "coordination" not in result
        assert "curation" not in result

    @pytest.mark.anyio()
    async def test_context_omits_curation_without_advisories(self) -> None:
        state = _state(entries=[_entry(updated_at=NOW)])

        result = await context_tool(
            ctx=_FakeCtx(state),
            repo="org/api",
            goal="auth token rotation",
            include_pr_signals=False,
        )

        assert "curation" not in result


class TestCurationPrivacyBoundary:
    def test_privacy_boundary_names_forbidden_inputs(self) -> None:
        boundary = " ".join(_curation_privacy_boundary()).lower()

        assert "repo-owned entry metadata" in boundary
        assert "query logs" in boundary
        assert "read receipts" in boundary
        assert "editor activity" in boundary
        assert "participation" in boundary
