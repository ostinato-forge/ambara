"""Tests for ambara.core.hygiene lifecycle summaries."""

from __future__ import annotations

from datetime import timedelta

from ambara.core.hygiene import summarize_lifecycle
from ambara.core.index import Index
from ambara.core.schema import EntryStatus, EntryType, EscalationLevel

from .conftest import BASE_NOW, make_entry


def test_summarize_lifecycle_flags_expired_active_entries() -> None:
    index = Index()
    index.add(
        make_entry(
            entry_id="expired-handoff",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            expires_at=BASE_NOW - timedelta(hours=1),
        )
    )

    report = summarize_lifecycle(index, now=BASE_NOW)

    assert [item.id for item in report.expired_active] == ["expired-handoff"]


def test_summarize_lifecycle_ignores_already_expired_active_entries() -> None:
    index = Index()
    index.add(
        make_entry(
            entry_id="expired-handoff",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.EXPIRED,
            expires_at=BASE_NOW - timedelta(hours=1),
        )
    )

    report = summarize_lifecycle(index, now=BASE_NOW)

    assert report.expired_active == []
