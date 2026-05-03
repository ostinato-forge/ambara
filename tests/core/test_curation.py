"""Tests for jurati.core.curation — contradiction detection and staleness."""

from __future__ import annotations

from datetime import UTC, datetime

from jurati.core.curation import (
    detect_contradictions,
    find_stale_entries,
)
from jurati.core.schema import EntryStatus, EntryType, EscalationLevel

from .conftest import BASE_NOW, make_entry


class TestDetectContradictions:
    def test_overlapping_titles_flagged(self) -> None:
        existing = [
            make_entry(entry_id="pool-entry-1", title="postgres pool capped at 20 connections"),
        ]
        new_title = "postgres pool capped at 30 connections"
        conflicts = detect_contradictions(new_title, existing)
        assert len(conflicts) == 1
        assert conflicts[0].frontmatter.id == "pool-entry-1"

    def test_different_titles_not_flagged(self) -> None:
        existing = [
            make_entry(entry_id="pool-entry-1", title="postgres pool capped at 20"),
        ]
        conflicts = detect_contradictions("redis cache TTL set to 30s", existing)
        assert len(conflicts) == 0

    def test_same_type_directory_only(self) -> None:
        existing = [
            make_entry(
                entry_id="pool-decision-1",
                title="pool limit decision",
                entry_type=EntryType.DECISION,
                level=EscalationLevel.L2,
            ),
        ]
        conflicts = detect_contradictions(
            "pool limit project update",
            existing,
            entry_type=EntryType.PROJECT,
        )
        assert len(conflicts) == 0


class TestFindStaleEntries:
    def test_old_entries_flagged(self) -> None:
        old = make_entry(
            entry_id="old",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        stale = find_stale_entries([old], now=BASE_NOW, stale_after_days=90)
        assert len(stale) == 1

    def test_recent_entries_not_flagged(self) -> None:
        recent = make_entry(entry_id="recent")
        stale = find_stale_entries([recent], now=BASE_NOW, stale_after_days=90)
        assert len(stale) == 0

    def test_expired_entries_excluded(self) -> None:
        expired = make_entry(
            entry_id="expired",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.EXPIRED,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            expires_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        stale = find_stale_entries([expired], now=BASE_NOW, stale_after_days=90)
        assert len(stale) == 0
