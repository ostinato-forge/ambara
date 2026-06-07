# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for pure PR signal classification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ambara.core.pr_signals import (
    CoordinationGuidance,
    CoordinationSignal,
    PRSignal,
    PRSignalEvidence,
    classify_signals,
    classify_source_inputs,
)
from ambara.sources.adapters import source_artifact_from_coordination_signal

NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


def _signal(**overrides: object) -> PRSignal:
    defaults: dict[str, object] = {
        "signal_id": "github:org/api:pull:42",
        "provider": "github",
        "repo": "org/api",
        "number": 42,
        "url": "https://github.com/org/api/pull/42",
        "title": "Resolve token refresh races",
        "body_excerpt": None,
        "author": "tony",
        "state": "open",
        "labels": ("ambara",),
        "created_at": NOW - timedelta(days=2),
        "updated_at": NOW - timedelta(hours=6),
        "merged_at": None,
        "changed_paths": ("src/auth/token.py", "src/auth/refresh.py"),
        "target_areas": ("src/auth",),
    }
    defaults.update(overrides)
    return PRSignal(**defaults)  # type: ignore[arg-type]


class TestClassifyReuse:
    def test_merged_pr_same_path_gives_reuse(self) -> None:
        sig = _signal(state="merged", merged_at=NOW - timedelta(days=1))
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 1
        assert results[0].effect == "reuse"
        assert results[0].confidence >= 70
        assert "Merged review on" in results[0].summary

    def test_merged_pr_area_overlap_gives_reuse(self) -> None:
        sig = _signal(
            state="merged",
            merged_at=NOW - timedelta(days=1),
            changed_paths=(),
            target_areas=("src/auth",),
        )
        results = classify_signals([sig], repo="org/api", paths=["src/auth/middleware.py"], now=NOW)
        assert len(results) == 1
        assert results[0].effect == "reuse"

    def test_evidence_includes_matched_paths(self) -> None:
        sig = _signal(state="merged", merged_at=NOW - timedelta(days=1))
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        ev = results[0].evidence[0]
        assert "src/auth/token.py" in ev.matched_paths
        assert ev.reason == "merged ambara-labeled artifact touched requested path"
        assert ev.merged_at == NOW - timedelta(days=1)


class TestClassifyPause:
    def test_open_pr_same_path_gives_pause(self) -> None:
        sig = _signal(state="open")
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 1
        assert results[0].effect == "pause"
        assert results[0].urgency == "warning"

    def test_pause_outranks_reuse_for_same_signal(self) -> None:
        sig = _signal(state="open")
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert results[0].effect == "pause"


class TestClassifyRevise:
    @pytest.mark.parametrize(
        "keyword",
        ["migration", "workflow", "decision", "deprecation", "architecture", "release", "security"],
    )
    def test_revise_keywords_in_title(self, keyword: str) -> None:
        sig = _signal(
            title=f"Update {keyword} for v3",
            changed_paths=(),
            target_areas=(),
        )
        results = classify_signals([sig], repo="org/api", now=NOW)
        assert any(g.effect == "revise" for g in results)

    def test_revise_from_body_excerpt(self) -> None:
        sig = _signal(
            title="Big changes",
            body_excerpt="This migration affects the auth layer",
            changed_paths=(),
            target_areas=(),
        )
        results = classify_signals([sig], repo="org/api", now=NOW)
        assert any(g.effect == "revise" for g in results)


class TestClassifyHandoff:
    @pytest.mark.parametrize("keyword", ["handoff", "owner", "review", "blocked", "waiting"])
    def test_handoff_keywords(self, keyword: str) -> None:
        sig = _signal(
            title=f"PR {keyword} to platform team",
            changed_paths=(),
            target_areas=(),
        )
        results = classify_signals([sig], repo="org/api", now=NOW)
        effects = [g.effect for g in results]
        assert "handoff" in effects or "revise" in effects


class TestClassifyContinue:
    def test_same_repo_different_area(self) -> None:
        sig = _signal(
            changed_paths=("src/billing/charge.py",),
            target_areas=("src/billing",),
        )
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 1
        assert results[0].effect == "continue"
        assert results[0].urgency == "info"


class TestClassifyClarify:
    def test_ambiguous_signal(self) -> None:
        sig = _signal(
            title="Minor fixes",
            changed_paths=(),
            target_areas=(),
        )
        results = classify_signals([sig], repo="org/api", now=NOW)
        assert any(g.effect in ("continue", "clarify") for g in results)

    def test_closed_not_merged_overlap_gives_clarify(self) -> None:
        sig = _signal(state="closed", merged_at=None)
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 1
        assert results[0].effect == "clarify"
        assert "not merged" in results[0].summary

    def test_missing_paths_for_same_repo_gives_clarify(self) -> None:
        sig = _signal(
            changed_paths=(),
            target_areas=(),
            changed_paths_status="unavailable",
        )
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 1
        assert results[0].effect == "clarify"
        assert "unavailable paths" in results[0].summary
        assert results[0].evidence[0].changed_paths_status == "unavailable"


class TestFiltering:
    def test_stale_signals_excluded(self) -> None:
        sig = _signal(updated_at=NOW - timedelta(days=60))
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 0

    def test_different_repo_no_paths_returns_nothing(self) -> None:
        sig = _signal(repo="org/web", changed_paths=(), target_areas=())
        results = classify_signals([sig], repo="org/api", now=NOW)
        assert len(results) == 0


class TestSorting:
    def test_higher_urgency_first(self) -> None:
        open_sig = _signal(state="open", number=1)
        merged_sig = _signal(
            state="merged",
            merged_at=NOW - timedelta(days=1),
            number=2,
            signal_id="github:org/api:pull:2",
            changed_paths=("src/auth/refresh.py",),
        )
        results = classify_signals(
            [merged_sig, open_sig],
            repo="org/api",
            paths=["src/auth/token.py", "src/auth/refresh.py"],
            now=NOW,
        )
        assert results[0].effect == "pause"


class TestDataclasses:
    def test_pr_signal_frozen(self) -> None:
        sig = _signal()
        with pytest.raises(AttributeError):
            sig.title = "changed"  # type: ignore[misc]

    def test_evidence_frozen(self) -> None:
        ev = PRSignalEvidence(
            repo="org/api",
            number=1,
            url="https://example.com",
            title="t",
            state="open",
            updated_at=NOW,
            matched_paths=(),
            reason="test",
        )
        with pytest.raises(AttributeError):
            ev.reason = "changed"  # type: ignore[misc]

    def test_guidance_frozen(self) -> None:
        g = CoordinationGuidance(
            effect="continue",
            urgency="info",
            summary="s",
            instruction="i",
            confidence=50,
            evidence=(),
        )
        with pytest.raises(AttributeError):
            g.effect = "pause"  # type: ignore[misc]

    def test_body_excerpt_truncated_in_classification(self) -> None:
        long_body = "x" * 1000
        sig = _signal(
            body_excerpt=long_body,
            title="Normal title",
            changed_paths=(),
            target_areas=(),
        )
        results = classify_signals([sig], repo="org/api", now=NOW)
        assert all(len(g.summary) < 500 for g in results)


# --- Phase 3: CoordinationSignal, configurable keywords, provider protocol ---


def _coord_signal(**overrides: object) -> CoordinationSignal:
    defaults: dict[str, object] = {
        "signal_id": "github:org/api:pull:42",
        "provider": "github",
        "source": "org/api",
        "artifact_ref": "https://github.com/org/api/pull/42",
        "title": "Resolve token refresh races",
        "excerpt": None,
        "actor": "tony",
        "state": "open",
        "labels": ("ambara",),
        "created_at": NOW - timedelta(days=2),
        "updated_at": NOW - timedelta(hours=6),
        "resolved_at": None,
        "subject_refs": ("src/auth/token.py", "src/auth/refresh.py"),
        "subject_areas": ("src/auth",),
    }
    defaults.update(overrides)
    return CoordinationSignal(**defaults)  # type: ignore[arg-type]


class TestCoordinationSignalConstruction:
    def test_frozen(self) -> None:
        sig = _coord_signal()
        with pytest.raises(AttributeError):
            sig.title = "changed"  # type: ignore[misc]

    def test_fields_match_provider_neutral_shape(self) -> None:
        sig = _coord_signal(
            provider="jira",
            source="PROJ-123",
            artifact_ref="https://jira.example.com/PROJ-123",
            state="resolved",
            resolved_at=NOW - timedelta(days=1),
        )
        assert sig.provider == "jira"
        assert sig.source == "PROJ-123"
        assert sig.artifact_ref == "https://jira.example.com/PROJ-123"
        assert sig.state == "resolved"
        assert sig.resolved_at is not None


class TestFromPRSignal:
    def test_maps_all_fields(self) -> None:
        pr = _signal(state="merged", merged_at=NOW - timedelta(days=1))
        coord = CoordinationSignal.from_pr_signal(pr)
        assert coord.signal_id == pr.signal_id
        assert coord.provider == pr.provider
        assert coord.source == pr.repo
        assert coord.artifact_ref == pr.url
        assert coord.title == pr.title
        assert coord.excerpt == pr.body_excerpt
        assert coord.actor == pr.author
        assert coord.state == pr.state
        assert coord.labels == pr.labels
        assert coord.created_at == pr.created_at
        assert coord.updated_at == pr.updated_at
        assert coord.resolved_at == pr.merged_at
        assert coord.subject_refs == pr.changed_paths
        assert coord.subject_areas == pr.target_areas
        assert coord.subject_refs_status == pr.changed_paths_status

    def test_none_merged_at_maps_to_none_resolved_at(self) -> None:
        pr = _signal(state="open", merged_at=None)
        coord = CoordinationSignal.from_pr_signal(pr)
        assert coord.resolved_at is None


class TestClassifyWithCoordinationSignals:
    """classify_signals() works identically with CoordinationSignal inputs."""

    def test_pause_from_coordination_signal(self) -> None:
        sig = _coord_signal(state="open")
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 1
        assert results[0].effect == "pause"
        assert results[0].urgency == "warning"

    def test_gitlab_review_signal_is_classified_like_github(self) -> None:
        sig = _signal(
            provider="gitlab",
            signal_id="gitlab:group/api:merge_request:42",
            url="https://gitlab.com/group/api/-/merge_requests/42",
            state="merged",
            merged_at=NOW - timedelta(days=1),
        )
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 1
        assert results[0].effect == "reuse"

    def test_reuse_from_coordination_signal(self) -> None:
        sig = _coord_signal(state="merged", resolved_at=NOW - timedelta(days=1))
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 1
        assert results[0].effect == "reuse"

    def test_revise_from_coordination_signal(self) -> None:
        sig = _coord_signal(
            title="Update migration for v3",
            subject_refs=(),
            subject_areas=(),
        )
        results = classify_signals([sig], repo="org/api", now=NOW)
        assert any(g.effect == "revise" for g in results)

    def test_continue_from_coordination_signal(self) -> None:
        sig = _coord_signal(
            subject_refs=("src/billing/charge.py",),
            subject_areas=("src/billing",),
        )
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 1
        assert results[0].effect == "continue"

    def test_clarify_from_coordination_signal_with_unavailable_paths(self) -> None:
        sig = _coord_signal(
            subject_refs=(),
            subject_areas=(),
            subject_refs_status="unavailable",
        )
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 1
        assert results[0].effect == "clarify"

    def test_evidence_extracts_pr_number_from_artifact_ref(self) -> None:
        sig = _coord_signal(
            state="merged",
            resolved_at=NOW - timedelta(days=1),
            artifact_ref="https://github.com/org/api/pull/99",
        )
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        ev = results[0].evidence[0]
        assert ev.number == 99

    def test_evidence_extracts_gitlab_mr_number_from_artifact_ref(self) -> None:
        sig = _coord_signal(
            provider="gitlab",
            state="merged",
            resolved_at=NOW - timedelta(days=1),
            artifact_ref="https://gitlab.com/group/api/-/merge_requests/77",
        )
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        ev = results[0].evidence[0]
        assert ev.number == 77

    def test_evidence_handles_non_pr_artifact_ref(self) -> None:
        sig = _coord_signal(
            state="merged",
            resolved_at=NOW - timedelta(days=1),
            artifact_ref="https://jira.example.com/PROJ-123",
        )
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        ev = results[0].evidence[0]
        assert ev.number == 0
        assert ev.url == "https://jira.example.com/PROJ-123"

    def test_stale_coordination_signals_excluded(self) -> None:
        sig = _coord_signal(updated_at=NOW - timedelta(days=60))
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 0


class TestClassifyWithSourceArtifacts:
    """classify_source_inputs() accepts source artifacts without legacy cache conversion."""

    def test_pause_from_source_artifact(self) -> None:
        artifact = source_artifact_from_coordination_signal(
            _coord_signal(state="open"), fetched_at=NOW
        )

        results = classify_source_inputs(
            [artifact],
            repo="org/api",
            paths=["src/auth/token.py"],
            now=NOW,
        )

        assert len(results) == 1
        assert results[0].effect == "pause"
        assert results[0].evidence[0].repo == "org/api"

    def test_legacy_signal_classifier_preserves_compatibility(self) -> None:
        artifact = source_artifact_from_coordination_signal(
            _coord_signal(state="open"), fetched_at=NOW
        )

        assert classify_signals(
            [artifact],
            repo="org/api",
            paths=["src/auth/token.py"],
            now=NOW,
        ) == classify_source_inputs(
            [artifact],
            repo="org/api",
            paths=["src/auth/token.py"],
            now=NOW,
        )

    def test_revise_from_jira_source_artifact(self) -> None:
        artifact = source_artifact_from_coordination_signal(
            _coord_signal(
                signal_id="jira:PROJ:issue:PROJ-123",
                provider="jira",
                source="PROJ",
                artifact_ref="https://jira.example.com/browse/PROJ-123",
                title="Update release workflow",
                subject_refs=(),
                subject_areas=(),
            ),
            fetched_at=NOW,
        )

        results = classify_source_inputs([artifact], repo="org/api", now=NOW)

        assert len(results) == 1
        assert results[0].effect == "revise"
        assert results[0].evidence[0].repo == "PROJ"


class TestConfigurableKeywords:
    def test_custom_revise_keywords(self) -> None:
        sig = _coord_signal(
            title="Update curriculum for training module",
            subject_refs=(),
            subject_areas=(),
        )
        results_default = classify_signals([sig], repo="org/api", now=NOW)
        assert not any(g.effect == "revise" for g in results_default)

        results_custom = classify_signals(
            [sig],
            repo="org/api",
            now=NOW,
            revise_keywords=("curriculum", "module", "lab"),
        )
        assert any(g.effect == "revise" for g in results_custom)

    def test_custom_handoff_keywords(self) -> None:
        sig = _coord_signal(
            title="Escalation to compliance team",
            subject_refs=(),
            subject_areas=(),
        )
        results_default = classify_signals([sig], repo="org/api", now=NOW)
        assert not any(g.effect == "handoff" for g in results_default)

        results_custom = classify_signals(
            [sig],
            repo="org/api",
            now=NOW,
            handoff_keywords=("escalation", "compliance"),
        )
        assert any(g.effect == "handoff" for g in results_custom)

    def test_keyword_prefix_matching(self) -> None:
        """Custom keyword 'deprecat' should match 'deprecation', 'deprecated'."""
        sig = _coord_signal(
            title="Handle deprecation of old API",
            subject_refs=(),
            subject_areas=(),
        )
        results = classify_signals(
            [sig],
            repo="org/api",
            now=NOW,
            revise_keywords=("deprecat",),
        )
        assert any(g.effect == "revise" for g in results)

    def test_none_keywords_use_defaults(self) -> None:
        sig = _coord_signal(
            title="Security update for auth layer",
            subject_refs=(),
            subject_areas=(),
        )
        results = classify_signals(
            [sig],
            repo="org/api",
            now=NOW,
            revise_keywords=None,
            handoff_keywords=None,
        )
        assert any(g.effect == "revise" for g in results)


class TestSignalProviderProtocol:
    def test_protocol_is_runtime_checkable(self) -> None:
        from ambara.providers.protocol import SignalProvider

        class FakeProvider:
            provider_id = "fake"

            def fetch_signals(self, config):
                return []

            def needs_refresh(self, last_fetch, now):
                return False

        assert isinstance(FakeProvider(), SignalProvider)

    def test_non_conforming_class_fails_check(self) -> None:
        from ambara.providers.protocol import SignalProvider

        class NotAProvider:
            pass

        assert not isinstance(NotAProvider(), SignalProvider)

    def test_protocol_returns_coordination_signals(self) -> None:
        from ambara.providers.protocol import SignalProvider

        class StubProvider:
            provider_id = "stub"

            def fetch_signals(self, config):
                return [_coord_signal(provider="stub", source="stub-project")]

            def needs_refresh(self, last_fetch, now):
                return True

        provider: SignalProvider = StubProvider()
        signals = provider.fetch_signals({})
        assert len(signals) == 1
        assert signals[0].provider == "stub"
        results = classify_signals(
            signals, repo="stub-project", paths=["src/auth/token.py"], now=NOW
        )
        assert len(results) >= 1
