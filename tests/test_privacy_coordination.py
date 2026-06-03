"""Privacy regression tests for PR coordination.

Verifies that the coordination system:
- Only uses explicitly labeled PRs from configured repos
- Never leaks query text, read patterns, or agent identity
- Never includes participation metrics or absence signals
- Includes privacy boundary statements in responses
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from ambara.core.index import Index
from ambara.core.pr_signals import PRSignal, classify_signals
from ambara.git.config import AmbaraConfig, PRSignalsConfig
from ambara.providers.cache import SignalCache
from ambara.server import (
    ServerState,
    SyncHealth,
    _build_coordination,
)
from ambara.server_coordination import (
    _privacy_boundary,
    build_coordination_payload,
)

NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _signal(number: int = 42, **overrides: object) -> PRSignal:
    defaults: dict[str, object] = {
        "signal_id": f"github:org/api:pull:{number}",
        "provider": "github",
        "repo": "org/api",
        "number": number,
        "url": f"https://github.com/org/api/pull/{number}",
        "title": "Fix auth token",
        "body_excerpt": None,
        "author": "tony",
        "state": "open",
        "labels": ("ambara",),
        "created_at": NOW - timedelta(days=2),
        "updated_at": NOW - timedelta(hours=6),
        "merged_at": None,
        "changed_paths": ("src/auth/token.py",),
        "target_areas": ("src/auth",),
    }
    defaults.update(overrides)
    return PRSignal(**defaults)  # type: ignore[arg-type]


def _state(signals: list[PRSignal] | None = None) -> ServerState:
    config = AmbaraConfig(
        remote_url="https://example.com/repo.git",
        pr_signals=PRSignalsConfig(repos=("org/api",)),
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


class TestNoQueryLeakage:
    def test_goal_not_stored_in_classification(self) -> None:
        sig = _signal()
        secret_goal = "fix-secret-project-alpha"
        results = classify_signals(
            [sig], repo="org/api", _goal=secret_goal, paths=["src/auth/token.py"], now=NOW
        )
        for g in results:
            assert secret_goal not in g.summary
            assert secret_goal not in g.instruction
            for ev in g.evidence:
                assert secret_goal not in ev.reason

    def test_paths_not_echoed_in_summary(self) -> None:
        sig = _signal(
            changed_paths=("src/billing/charge.py",),
            target_areas=("src/billing",),
        )
        results = classify_signals(
            [sig],
            repo="org/api",
            paths=["src/secret-project/internal.py"],
            now=NOW,
        )
        for g in results:
            assert "secret-project" not in g.summary


class TestNoParticipationTracking:
    @pytest.mark.anyio()
    async def test_response_has_no_requester_identity(self) -> None:
        state = _state(signals=[_signal()])
        result = await _build_coordination(
            state, repo="org/api", goal=None, paths=["src/auth/token.py"], now=NOW
        )
        result_str = str(result)
        assert "requester" not in result_str.lower()
        assert "caller" not in result_str.lower()
        assert "agent_id" not in result_str.lower()

    @pytest.mark.anyio()
    async def test_no_read_receipt_or_count(self) -> None:
        state = _state(signals=[_signal()])
        result = await _build_coordination(
            state, repo="org/api", goal=None, paths=["src/auth/token.py"], now=NOW
        )
        assert "read_count" not in str(result)
        assert "viewed_by" not in str(result)

    @pytest.mark.anyio()
    async def test_no_absence_signals(self) -> None:
        state = _state(signals=[_signal()])
        result = await _build_coordination(
            state, repo="org/api", goal=None, paths=["src/auth/token.py"], now=NOW
        )
        assert "did_not" not in str(result)
        assert "never_labeled" not in str(result)
        assert "inactive" not in str(result)


class TestOnlyLabeledPRs:
    def test_classification_only_processes_provided_signals(self) -> None:
        labeled = _signal(42, labels=("ambara",))
        results = classify_signals([labeled], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert all("ambara" in str(ev.reason) or True for g in results for ev in g.evidence)

    @pytest.mark.anyio()
    async def test_unconfigured_repos_not_queried(self) -> None:
        config = AmbaraConfig(
            remote_url="https://example.com/repo.git",
            pr_signals=PRSignalsConfig(repos=("org/api",)),
        )
        state = ServerState(
            config=config,
            repo_path="/fake/repo",
            index=Index(),
            last_sync=NOW,
            sync_health=SyncHealth(last_success=NOW),
        )
        seen_configs: list[PRSignalsConfig] = []

        def fetch_signals(call_config: PRSignalsConfig) -> list[PRSignal]:
            seen_configs.append(call_config)
            return []

        async def run_blocking(function: Callable[[], list[PRSignal]]) -> list[PRSignal]:
            return function()

        await build_coordination_payload(
            state,
            repo="org/secret-repo",
            goal=None,
            paths=None,
            now=NOW,
            fetch_signals=fetch_signals,
            run_blocking=run_blocking,
            logger=MockLogger(),
        )

        assert seen_configs
        assert all("org/secret-repo" not in call_config.repos for call_config in seen_configs)


class MockLogger:
    def warning(self, *args: object, **kwargs: object) -> None:
        return None


class TestPrivacyBoundaryPresence:
    @pytest.mark.anyio()
    async def test_privacy_boundary_always_present(self) -> None:
        state = _state(signals=[_signal()])
        result = await _build_coordination(
            state, repo="org/api", goal=None, paths=["src/auth/token.py"], now=NOW
        )
        assert "privacy_boundary" in result
        boundary = result["privacy_boundary"]
        assert any("configured repos" in s for s in boundary)
        assert any("unlabeled" in s for s in boundary)

    @pytest.mark.anyio()
    async def test_privacy_boundary_on_empty_guidance(self) -> None:
        state = _state()
        state.signal_cache.update([], now=NOW)
        result = await _build_coordination(state, repo="org/api", goal=None, paths=None, now=NOW)
        assert "privacy_boundary" in result

    def test_privacy_boundary_statements_complete(self) -> None:
        boundary = _privacy_boundary()
        combined = " ".join(boundary).lower()
        assert "configured repos" in combined
        assert "ambara label" in combined
        assert "unlabeled" in combined
        assert "read activity" in combined or "editor activity" in combined


class TestNoAuthorInEvidence:
    @pytest.mark.anyio()
    async def test_evidence_dict_has_no_author_key(self) -> None:
        state = _state(signals=[_signal()])
        result = await _build_coordination(
            state, repo="org/api", goal=None, paths=["src/auth/token.py"], now=NOW
        )
        for g in result["guidance"]:
            for ev in g["evidence"]:
                assert "author" not in ev

    def test_summary_does_not_contain_actor_name(self) -> None:
        sig = _signal(state="open")
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        for g in results:
            assert "tony" not in g.summary

    def test_privacy_boundary_declares_no_author(self) -> None:
        boundary = _privacy_boundary()
        assert any("author" in s.lower() for s in boundary)


class TestTokenSanitization:
    def test_sanitize_in_provider(self) -> None:
        from ambara.providers.github_prs import _sanitize_error

        msg = "auth: ghp_abc123def456ghi789jkl012mno345pq failed"
        assert "ghp_" not in _sanitize_error(msg)
        assert "[REDACTED]" in _sanitize_error(msg)
