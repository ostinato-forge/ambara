"""Tests for jurati.curation.hygiene_pr — weekly hygiene PR generation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jurati.core.curation import CurationAdvisory
from jurati.core.hygiene import summarize_lifecycle
from jurati.core.index import Index
from jurati.core.schema import EntryStatus, EntryType, EscalationLevel
from jurati.curation.hygiene_pr import build_hygiene_pr_body
from tests.core.conftest import BASE_NOW, make_entry


class TestBuildHygienePrBody:
    def test_includes_stale_entries(self) -> None:
        stale = [
            make_entry(
                entry_id="old-decision",
                title="Old decision",
                created_at=datetime(2025, 12, 1, tzinfo=UTC),
                updated_at=datetime(2025, 12, 1, tzinfo=UTC),
            ),
        ]
        body = build_hygiene_pr_body(
            stale_entries=stale,
            revalidation_entries=[],
            contradictions=[],
            now=BASE_NOW,
        )
        assert "old-decision" in body
        assert "Stale" in body

    def test_includes_revalidation_entries(self) -> None:
        index = Index()
        entry = make_entry(
            entry_id="cache-choice",
            title="Cache choice",
            status=EntryStatus.ACTIVE,
            review_pr="https://github.com/org/repo/pull/1",
            review_after=datetime(2026, 5, 1, tzinfo=UTC),
        )
        index.add(entry)
        report = summarize_lifecycle(index, now=BASE_NOW)

        body = build_hygiene_pr_body(
            stale_entries=[],
            revalidation_entries=report.revalidation,
            contradictions=[],
            now=BASE_NOW,
        )

        assert "Revalidation Due" in body
        assert "cache-choice" in body
        assert "review_after: 2026-05-01" in body

    def test_includes_expired_active_entries(self) -> None:
        index = Index()
        entry = make_entry(
            entry_id="current-task",
            title="Current task",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            expires_at=BASE_NOW - timedelta(hours=1),
        )
        index.add(entry)
        report = summarize_lifecycle(index, now=BASE_NOW)

        body = build_hygiene_pr_body(
            stale_entries=[],
            expired_active_entries=report.expired_active,
            revalidation_entries=[],
            contradictions=[],
            now=BASE_NOW,
        )

        assert "Expired Active Context" in body
        assert "current-task" in body
        assert "expires_at: 2026-05-02" in body

    def test_includes_contradictions(self) -> None:
        body = build_hygiene_pr_body(
            stale_entries=[],
            revalidation_entries=[],
            contradictions=[("new-entry", ["existing-1", "existing-2"])],
            now=BASE_NOW,
        )
        assert "Contradiction" in body or "contradiction" in body
        assert "new-entry" in body

    def test_includes_merged_artifact_revalidation_advisories(self) -> None:
        advisory = CurationAdvisory(
            entry_id="auth-token-decision",
            entry_title="Auth token decision",
            entry_type=EntryType.DECISION,
            suggested_action="revalidate",
            reason="merged artifact changed matching metadata",
            signal_id="github:org/api:pull:12",
            signal_source="org/api",
            artifact_ref="https://github.com/org/api/pull/12",
            artifact_title="Refactor auth token rotation",
            actor="alice",
            changed_paths=("src/auth/tokens.py",),
            matched_terms=("auth", "tokens"),
            merged_at=BASE_NOW,
        )

        body = build_hygiene_pr_body(
            stale_entries=[],
            revalidation_entries=[],
            contradictions=[],
            curation_advisories=[advisory],
            now=BASE_NOW,
        )

        assert "Completed Artifact Revalidation" in body
        assert "auth-token-decision" in body
        assert "Refactor auth token rotation" in body
        assert "matched: auth, tokens" in body

    def test_sanitizes_untrusted_advisory_fields(self) -> None:
        advisory = CurationAdvisory(
            entry_id="auth-token-decision",
            entry_title="Auth token decision",
            entry_type=EntryType.DECISION,
            suggested_action="revalidate",
            reason="completed artifact changed matching metadata",
            signal_id="github:org/api:pull:12",
            signal_source="org/api",
            artifact_ref="javascript:alert(1)",
            artifact_title="Rotate [auth](https://evil.example) token=ABCDEFGHIJKLMNOPQRSTUV",
            actor="alice",
            changed_paths=("src/auth/tokens.py", "../secret.txt", "bad path.py"),
            matched_terms=("auth",),
            merged_at=BASE_NOW,
        )

        body = build_hygiene_pr_body(
            stale_entries=[],
            revalidation_entries=[],
            contradictions=[],
            curation_advisories=[advisory],
            now=BASE_NOW,
        )

        assert "javascript:alert" not in body
        assert "ABCDEFGHIJKLMNOPQRSTUV" not in body
        assert "\\[redacted:credential\\]" in body
        assert "\\[auth\\]" in body
        assert "../secret.txt" not in body
        assert "bad path.py" not in body
        assert "src/auth/tokens.py" in body

    def test_rejects_artifact_urls_with_credentials(self) -> None:
        advisory = CurationAdvisory(
            entry_id="auth-token-decision",
            entry_title="Auth token decision",
            entry_type=EntryType.DECISION,
            suggested_action="revalidate",
            reason="completed artifact changed matching metadata",
            signal_id="github:org/api:pull:12",
            signal_source="org/api",
            artifact_ref="https://user:pass@github.com/org/api/pull/12?token=secret",
            artifact_title="Refactor auth token rotation",
            actor="alice",
            changed_paths=("src/auth/tokens.py",),
            matched_terms=("auth",),
            merged_at=BASE_NOW,
        )

        body = build_hygiene_pr_body(
            stale_entries=[],
            revalidation_entries=[],
            contradictions=[],
            curation_advisories=[advisory],
            now=BASE_NOW,
        )

        assert "user:pass" not in body
        assert "?token=secret" not in body
        assert "[Refactor auth token rotation](" not in body
        assert "Refactor auth token rotation" in body

    def test_empty_report(self) -> None:
        body = build_hygiene_pr_body(
            stale_entries=[],
            revalidation_entries=[],
            contradictions=[],
            now=BASE_NOW,
        )
        assert "No issues" in body or "clean" in body.lower()
