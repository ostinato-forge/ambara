"""Tests for jurati.curation.hygiene_pr — weekly hygiene PR generation."""

from __future__ import annotations

from datetime import UTC, datetime

from jurati.core.hygiene import summarize_lifecycle
from jurati.core.index import Index
from jurati.core.schema import EntryStatus
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

    def test_includes_contradictions(self) -> None:
        body = build_hygiene_pr_body(
            stale_entries=[],
            revalidation_entries=[],
            contradictions=[("new-entry", ["existing-1", "existing-2"])],
            now=BASE_NOW,
        )
        assert "Contradiction" in body or "contradiction" in body
        assert "new-entry" in body

    def test_empty_report(self) -> None:
        body = build_hygiene_pr_body(
            stale_entries=[],
            revalidation_entries=[],
            contradictions=[],
            now=BASE_NOW,
        )
        assert "No issues" in body or "clean" in body.lower()
