"""Tests for pure PR signal classification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jurati.core.pr_signals import (
    CoordinationGuidance,
    PRSignal,
    PRSignalEvidence,
    classify_signals,
)

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
        "labels": ("jurati",),
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
        assert "tony" in results[0].summary

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
        assert ev.reason == "merged jurati-labeled PR touched requested path"


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


class TestFiltering:
    def test_stale_signals_excluded(self) -> None:
        sig = _signal(updated_at=NOW - timedelta(days=60))
        results = classify_signals([sig], repo="org/api", paths=["src/auth/token.py"], now=NOW)
        assert len(results) == 0

    def test_closed_not_merged_excluded(self) -> None:
        sig = _signal(state="closed", merged_at=None)
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
            author="a",
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
