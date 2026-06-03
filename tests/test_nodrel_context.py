"""Tests for the public nodrel.context API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nodrel.context import (
    AccessMode,
    AvailabilityStatus,
    Constraint,
    ConstraintEffect,
    ConstraintKind,
    EntryType,
    EscalationLevel,
    Index,
    KnowledgeQuery,
    PacketVerdict,
    PlanningAction,
    Visibility,
    derive_freshness,
    derive_planning_state,
    query_knowledge,
)
from tests.core.conftest import BASE_NOW, make_entry


def test_context_query_surface_filters_entries() -> None:
    index = Index()
    index.add(
        make_entry(
            entry_id="external-decision",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            visibility=Visibility.EXTERNAL,
            on_source_branch=True,
        )
    )
    index.add(make_entry(entry_id="internal-project", visibility=Visibility.INTERNAL))

    result = query_knowledge(
        index,
        KnowledgeQuery(access_mode=AccessMode.EXTERNAL_CONTEXT, system_id="consumer"),
        now=BASE_NOW,
    )

    assert [entry["id"] for entry in result.entries] == ["external-decision"]


def test_context_planning_surface_derives_packet_action() -> None:
    freshness = derive_freshness(
        now=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        last_success=datetime(2026, 6, 2, 11, 59, tzinfo=UTC),
        warning_threshold_seconds=300,
        stale_threshold_seconds=900,
    )
    constraint = Constraint(
        kind=ConstraintKind.COORDINATION,
        effect=ConstraintEffect.VERIFY_BEFORE_RELYING,
        summary="Coordination source is unavailable.",
        read_hint="read coordination evidence before acting",
    )

    state = derive_planning_state(freshness, (constraint,))

    assert freshness.status == AvailabilityStatus.FRESH
    assert state.verdict == PacketVerdict.CAUTION
    assert state.action == PlanningAction.READ_OR_VERIFY_BEFORE_ACTING
    assert state.read_handles == ("read coordination evidence before acting",)


def test_context_planning_surface_marks_stale_context() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    freshness = derive_freshness(
        now=now,
        last_success=now - timedelta(seconds=901),
        warning_threshold_seconds=300,
        stale_threshold_seconds=900,
    )

    state = derive_planning_state(freshness, ())

    assert freshness.status == AvailabilityStatus.STALE
    assert state.verdict == PacketVerdict.STALE
    assert state.action == PlanningAction.STOP_OR_REQUEST_REFRESH
