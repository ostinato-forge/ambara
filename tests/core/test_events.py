"""Tests for event types and lifecycle records."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jurati.core.events import EventRecord, EventType


def test_event_types() -> None:
    assert EventType.ENTRY_PROPOSED == "entry_proposed"
    assert EventType.ENTRY_EXPIRED == "entry_expired"


def test_event_record_frozen() -> None:
    ev = EventRecord(
        timestamp=datetime(2026, 5, 5, 14, 30, 22, tzinfo=UTC),
        event_type=EventType.ENTRY_PROPOSED,
        entry_id="auth-token-format",
        entry_type="decision",
        level="L2",
        visibility="external",
    )
    assert ev.entry_id == "auth-token-format"
    with pytest.raises(AttributeError):
        ev.entry_id = "changed"  # type: ignore[misc]


def test_event_record_to_dict() -> None:
    ev = EventRecord(
        timestamp=datetime(2026, 5, 5, 14, 30, 22, tzinfo=UTC),
        event_type=EventType.ENTRY_PROPOSED,
        entry_id="auth-format",
        entry_type="decision",
        level="L2",
        visibility="external",
    )
    d = ev.to_dict()
    assert d["timestamp"] == "2026-05-05T14:30:22Z"
    assert d["event_type"] == "entry_proposed"
    assert d["entry_id"] == "auth-format"


def test_event_record_contains_no_identity_or_content() -> None:
    """Privacy contract: events never include author, body, query, or recorded_by."""
    ev = EventRecord(
        timestamp=datetime(2026, 5, 5, 14, 30, 22, tzinfo=UTC),
        event_type=EventType.ENTRY_PROPOSED,
        entry_id="privacy-test",
        entry_type="decision",
        level="L2",
        visibility="external",
    )
    d = ev.to_dict()
    forbidden = {"author", "body", "content", "query", "recorded_by", "client", "source"}
    assert forbidden.isdisjoint(d.keys()), (
        f"Event dict must not contain identity/content fields: {forbidden & d.keys()}"
    )

    json_str = ev.to_json()
    for field_name in forbidden:
        assert f'"{field_name}"' not in json_str


def test_event_record_path() -> None:
    ev = EventRecord(
        timestamp=datetime(2026, 5, 5, 14, 30, 22, tzinfo=UTC),
        event_type=EventType.ENTRY_PROPOSED,
        entry_id="auth-format",
        entry_type="decision",
        level="L2",
        visibility="external",
    )
    assert ev.path() == "events/2026-05-05/20260505T143022Z-auth-format.json"


def test_event_record_to_json_roundtrip() -> None:
    import json

    ev = EventRecord(
        timestamp=datetime(2026, 5, 5, 14, 30, 22, tzinfo=UTC),
        event_type=EventType.ENTRY_EXPIRED,
        entry_id="expired-entry",
        entry_type="project",
        level="L1",
        visibility="internal",
    )
    parsed = json.loads(ev.to_json())
    assert parsed == ev.to_dict()
