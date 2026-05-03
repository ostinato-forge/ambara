"""Tests for jurati.curation.hygiene_pr — weekly hygiene PR generation."""

from __future__ import annotations

from datetime import UTC, datetime

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
        body = build_hygiene_pr_body(stale_entries=stale, contradictions=[], now=BASE_NOW)
        assert "old-decision" in body
        assert "Stale" in body

    def test_includes_contradictions(self) -> None:
        body = build_hygiene_pr_body(
            stale_entries=[],
            contradictions=[("new-entry", ["existing-1", "existing-2"])],
            now=BASE_NOW,
        )
        assert "Contradiction" in body or "contradiction" in body
        assert "new-entry" in body

    def test_empty_report(self) -> None:
        body = build_hygiene_pr_body(stale_entries=[], contradictions=[], now=BASE_NOW)
        assert "No issues" in body or "clean" in body.lower()
