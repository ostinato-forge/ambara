from __future__ import annotations

from datetime import timedelta

from ambara.core.dedup import check_write_conflicts
from ambara.core.index import Index
from ambara.core.schema import EntryStatus, EntryType, EscalationLevel, Sensitivity

from .conftest import BASE_NOW, make_entry, minutes_after


def _index(*entries):
    return Index(entries={entry.frontmatter.id: entry for entry in entries})


def test_no_conflicts_on_empty_index() -> None:
    conflicts = check_write_conflicts(
        Index(),
        title="Deploy checklist",
        entry_type=EntryType.PROJECT,
        now=BASE_NOW,
    )

    assert not conflicts.has_conflicts
    assert conflicts.duplicates == ()
    assert conflicts.expired_active == ()
    assert conflicts.stale_proposed == ()


def test_exact_title_same_type_is_duplicate() -> None:
    existing = make_entry(entry_id="deploy-checklist", title="Deploy checklist")

    conflicts = check_write_conflicts(
        _index(existing),
        title="Deploy checklist",
        entry_type=EntryType.PROJECT,
        now=BASE_NOW,
    )

    assert [item.id for item in conflicts.duplicates] == ["deploy-checklist"]


def test_same_title_different_type_not_duplicate() -> None:
    existing = make_entry(
        entry_id="deploy-checklist",
        title="Deploy checklist",
        entry_type=EntryType.WORKFLOW,
        level=EscalationLevel.L2,
    )

    conflicts = check_write_conflicts(
        _index(existing),
        title="Deploy checklist",
        entry_type=EntryType.PROJECT,
        now=BASE_NOW,
    )

    assert conflicts.duplicates == ()


def test_case_insensitive_title_match() -> None:
    existing = make_entry(entry_id="deploy-checklist", title="Deploy Checklist")

    conflicts = check_write_conflicts(
        _index(existing),
        title="deploy CHECKLIST",
        entry_type=EntryType.PROJECT,
        now=BASE_NOW,
    )

    assert [item.id for item in conflicts.duplicates] == ["deploy-checklist"]


def test_substring_title_match() -> None:
    existing = make_entry(entry_id="deploy-checklist", title="Deploy checklist")

    conflicts = check_write_conflicts(
        _index(existing),
        title="Deploy checklist v2",
        entry_type=EntryType.PROJECT,
        now=BASE_NOW,
    )

    assert [item.id for item in conflicts.duplicates] == ["deploy-checklist"]


def test_expired_active_with_project_overlap() -> None:
    existing = make_entry(
        entry_id="old-handoff",
        title="Old auth handoff",
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        projects=["api-service"],
        expires_at=BASE_NOW - timedelta(minutes=5),
        review_required=False,
    )

    conflicts = check_write_conflicts(
        _index(existing),
        title="Auth status",
        entry_type=EntryType.PROJECT,
        projects=["api-service"],
        now=BASE_NOW,
    )

    assert [item.id for item in conflicts.expired_active] == ["old-handoff"]


def test_expired_active_different_project_not_flagged() -> None:
    existing = make_entry(
        entry_id="old-handoff",
        title="Old auth handoff",
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        projects=["frontend"],
        expires_at=BASE_NOW - timedelta(minutes=5),
        review_required=False,
    )

    conflicts = check_write_conflicts(
        _index(existing),
        title="Auth status",
        entry_type=EntryType.PROJECT,
        projects=["api-service"],
        now=BASE_NOW,
    )

    assert conflicts.expired_active == ()


def test_unexpired_active_not_flagged_as_expired() -> None:
    existing = make_entry(
        entry_id="current-handoff",
        title="Current auth handoff",
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        projects=["api-service"],
        expires_at=minutes_after(30),
        review_required=False,
    )

    conflicts = check_write_conflicts(
        _index(existing),
        title="Auth status",
        entry_type=EntryType.PROJECT,
        projects=["api-service"],
        now=BASE_NOW,
    )

    assert conflicts.expired_active == ()


def test_stale_proposed_same_type_and_project() -> None:
    existing = make_entry(
        entry_id="old-project-update",
        title="Auth project update",
        entry_type=EntryType.PROJECT,
        status=EntryStatus.PROPOSED,
        projects=["api-service"],
        updated_at=BASE_NOW - timedelta(days=31),
    )

    conflicts = check_write_conflicts(
        _index(existing),
        title="New auth project update",
        entry_type=EntryType.PROJECT,
        projects=["api-service"],
        now=BASE_NOW,
    )

    assert [item.id for item in conflicts.stale_proposed] == ["old-project-update"]


def test_stale_proposed_different_type_not_flagged() -> None:
    existing = make_entry(
        entry_id="old-workflow",
        title="Auth workflow",
        entry_type=EntryType.WORKFLOW,
        level=EscalationLevel.L2,
        status=EntryStatus.PROPOSED,
        projects=["api-service"],
        updated_at=BASE_NOW - timedelta(days=31),
    )

    conflicts = check_write_conflicts(
        _index(existing),
        title="New auth project update",
        entry_type=EntryType.PROJECT,
        projects=["api-service"],
        now=BASE_NOW,
    )

    assert conflicts.stale_proposed == ()


def test_restricted_entries_excluded() -> None:
    duplicate = make_entry(
        entry_id="restricted-duplicate",
        title="Deploy checklist",
        sensitivity=Sensitivity.RESTRICTED,
    )
    expired_active = make_entry(
        entry_id="restricted-active",
        title="Old handoff",
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        projects=["api-service"],
        expires_at=BASE_NOW - timedelta(minutes=5),
        review_required=False,
        sensitivity=Sensitivity.RESTRICTED,
    )

    conflicts = check_write_conflicts(
        _index(duplicate, expired_active),
        title="Deploy checklist",
        entry_type=EntryType.PROJECT,
        projects=["api-service"],
        now=BASE_NOW,
    )

    assert not conflicts.has_conflicts
