from __future__ import annotations

from datetime import timedelta

from jurati.core.schema import EntryStatus, EntryType, EscalationLevel
from jurati.core.validate import check_write_path, is_expired, validate_entry

from .conftest import make_entry, minutes_after


def test_valid_project_entry_has_no_validation_errors() -> None:
    entry = make_entry()

    assert validate_entry(entry) == []


def test_validation_rejects_empty_title() -> None:
    entry = make_entry(title=" ")

    assert "title must not be empty" in validate_entry(entry)


def test_validation_rejects_path_not_derived_from_entry_type_and_id() -> None:
    entry = make_entry(path="decisions/test-entry.md")

    assert "path 'decisions/test-entry.md' does not match expected 'projects/test-entry.md'" in (
        validate_entry(entry)
    )


def test_active_entries_must_have_expires_at() -> None:
    entry = make_entry(
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        review_required=False,
    )

    assert "active entries must have expires_at" in validate_entry(entry)


def test_only_active_entries_may_have_expires_at() -> None:
    entry = make_entry(expires_at=minutes_after(10))

    assert "only active entries should have expires_at" in validate_entry(entry)


def test_expiry_must_be_after_creation() -> None:
    entry = make_entry(
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        expires_at=minutes_after(0),
        review_required=False,
    )

    assert "expires_at must be > created_at" in validate_entry(entry)


def test_updated_at_cannot_precede_created_at() -> None:
    entry = make_entry(updated_at=minutes_after(-1))

    assert "updated_at must be >= created_at" in validate_entry(entry)


def test_active_reviewed_content_needs_pr_metadata() -> None:
    entry = make_entry(status=EntryStatus.ACTIVE)

    assert "L1/L2/L3 active entries must have review.pr set" in validate_entry(entry)


def test_active_l0_content_does_not_need_pr_metadata() -> None:
    entry = make_entry(
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        expires_at=minutes_after(10),
        review_required=False,
    )

    assert validate_entry(entry) == []


def test_is_expired_uses_explicit_now() -> None:
    entry = make_entry(
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        expires_at=minutes_after(5),
        review_required=False,
    )

    assert not is_expired(entry, minutes_after(4))
    assert is_expired(entry, minutes_after(5))


def test_entries_without_expires_at_are_not_expired() -> None:
    entry = make_entry()

    assert not is_expired(entry, entry.frontmatter.created_at + timedelta(days=365))


def test_write_path_by_escalation_level() -> None:
    assert check_write_path(EntryType.ACTIVE, EscalationLevel.L0) == "active_ref"
    assert check_write_path(EntryType.PROJECT, EscalationLevel.L1) == "lightweight_pr"
    assert check_write_path(EntryType.PRINCIPLE, EscalationLevel.L3) == "review_pr"
