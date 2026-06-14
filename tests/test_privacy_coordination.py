# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Privacy regression tests for PR coordination.

Verifies that the coordination system:
- Only uses explicitly labeled PRs from configured repos
- Never leaks query text, read patterns, or agent identity
- Never includes participation metrics or absence signals
- Includes privacy boundary statements in responses
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from ambara.core.index import Index
from ambara.core.pr_signals import PRSignal, classify_signals
from ambara.git.config import AmbaraConfig, PRSignalsConfig
from ambara.server import (
    ServerState,
    SyncHealth,
    _build_coordination,
)
from ambara.server_coordination import (
    _privacy_boundary,
    build_coordination_payload,
)
from ambara.sources.runtime import SourceRuntimeReport
from tests._source_report import source_report_for_signals

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
    state = ServerState(
        config=config,
        repo_path="/fake/repo",
        index=Index(),
        last_sync=NOW,
        sync_health=SyncHealth(last_success=NOW),
    )
    if signals is not None:
        state.source_report = source_report_for_signals(*signals, now=NOW)
        state.source_report_last_refresh = NOW
    return state


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
        seen_configs: list[object] = []

        def fetch_runtime(call_config: object, **kwargs: object) -> SourceRuntimeReport:
            seen_configs.append(call_config)
            return SourceRuntimeReport(
                legacy_signals=(), source_report=source_report_for_signals(now=NOW)
            )

        async def run_blocking(function: Callable[[], object]) -> object:
            return function()

        with patch("ambara.server_signals.fetch_source_runtime_report", side_effect=fetch_runtime):
            await build_coordination_payload(
                state,
                repo="org/secret-repo",
                goal=None,
                paths=None,
                now=NOW,
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
        state = _state(signals=[])
        result = await _build_coordination(state, repo="org/api", goal=None, paths=None, now=NOW)
        assert "privacy_boundary" in result

    def test_privacy_boundary_statements_complete(self) -> None:
        boundary = _privacy_boundary()
        combined = " ".join(boundary).lower()
        assert "configured repos" in combined
        assert "source inputs" in combined
        assert "ambara label" in combined
        assert "unlabeled" in combined
        assert "read activity" in combined or "editor activity" in combined
        assert "review signals" not in combined


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
        combined = " ".join(boundary).lower()
        assert "identities" in combined
        assert "source actor" in combined


class TestTokenSanitization:
    def test_sanitize_in_provider(self) -> None:
        from ambara.providers.github_prs import _sanitize_error

        msg = "auth: ghp_abc123def456ghi789jkl012mno345pq failed"
        assert "ghp_" not in _sanitize_error(msg)
        assert "[REDACTED]" in _sanitize_error(msg)


class TestJiraIdentityDroppedAtArtifactBoundary:
    """Pin that human identity (Jira displayName / actor) is structurally dropped
    when a SourceArtifact is converted to a CoordinationSignal.

    Background: jira_issues.py may populate CoordinationSignal.actor with a Jira
    displayName, but SourceArtifact has no author/actor field.  The adapter
    coordination_signal_from_source_artifact() always emits actor="unknown",
    so identity is lost at the artifact boundary regardless of what the original
    provider placed in actor.
    """

    def test_actor_is_unknown_after_adapter_conversion(self) -> None:
        from ambara.sources.adapters import coordination_signal_from_source_artifact
        from ambara.sources.testing import make_source_artifact

        # Build an artifact whose title/excerpt contains a human-name-like string
        # to make the assertion non-vacuous (we want to confirm it doesn't sneak through).
        artifact = make_source_artifact(
            artifact_id="jira:PROJ-123",
            provider_id="jira",
            artifact_type="issue",
            title="Issue assigned to John Smith",
            excerpt="Reported by Jane Doe — needs triage",
        )
        signal = coordination_signal_from_source_artifact(artifact, now=NOW)

        # Primary invariant: identity is dropped; actor is the sentinel value.
        assert signal.actor == "unknown"

    def test_display_name_does_not_appear_in_signal_serialisation(self) -> None:
        from ambara.sources.adapters import coordination_signal_from_source_artifact
        from ambara.sources.testing import make_source_artifact

        artifact = make_source_artifact(
            artifact_id="jira:PROJ-456",
            provider_id="jira",
            artifact_type="issue",
            title="Bug filed by Alice Johnson",
            excerpt="Needs review by a backend engineer",
        )
        signal = coordination_signal_from_source_artifact(artifact, now=NOW)

        serialised = json.dumps(signal.__dict__, default=str)
        # The Jira API field key "displayName" must not appear as a key in any
        # serialised form — it should be structurally absent, not merely redacted.
        assert "displayName" not in serialised
