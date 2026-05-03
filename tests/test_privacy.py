"""Privacy regression tests — ensure jurati produces no telemetry."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from jurati.core.index import Index
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
)
from jurati.core.search import query as core_query


def _make_entry(entry_id: str = "test-entry") -> Entry:
    return Entry(
        path=f"decisions/{entry_id}.md",
        frontmatter=Frontmatter(
            id=entry_id,
            title="Test decision",
            type=EntryType.DECISION,
            level=EscalationLevel.L2,
            status=EntryStatus.ACTIVE,
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            updated_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            review=ReviewMeta(required=True, pr="https://github.com/org/repo/pull/1"),
        ),
        body="Decision body.",
    )


class TestNoTelemetry:
    def test_query_produces_no_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        index = Index()
        index.add(_make_entry())
        core_query(index, "test")

        created = list(tmp_path.rglob("*"))
        assert len(created) == 0

    def test_index_operations_produce_no_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        index = Index()
        entry = _make_entry()
        index.add(entry)
        index.get("test-entry")
        index.list_entries()
        index.remove("test-entry")

        created = list(tmp_path.rglob("*"))
        assert len(created) == 0

    def test_no_query_text_in_index(self) -> None:
        index = Index()
        index.add(_make_entry())
        core_query(index, "secret-search-term")

        index_repr = str(index.entries)
        assert "secret-search-term" not in index_repr
