from __future__ import annotations

from datetime import timedelta

from ambara.core.schema import EntryStatus, EntryType, EscalationLevel, Sensitivity, Visibility
from ambara.core.validate import check_write_path, is_expired, validate_entry

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


def test_active_entries_should_not_have_review_after() -> None:
    entry = make_entry(
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        expires_at=minutes_after(10),
        review_after=minutes_after(20),
        review_required=False,
    )

    assert "active entries should use expires_at instead of review_after" in validate_entry(entry)


def test_review_after_must_not_precede_creation() -> None:
    entry = make_entry(review_after=minutes_after(-1))

    assert "review_after must be >= created_at" in validate_entry(entry)


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


class TestSensitivityEnforcement:
    def test_restricted_entry_cannot_be_external(self) -> None:
        entry = make_entry(
            sensitivity=Sensitivity.RESTRICTED,
            visibility=Visibility.EXTERNAL,
        )
        errors = validate_entry(entry)
        assert any("restricted" in e and "external" in e for e in errors)

    def test_restricted_entry_cannot_be_l0(self) -> None:
        entry = make_entry(
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            sensitivity=Sensitivity.RESTRICTED,
            expires_at=minutes_after(30),
            review_required=False,
        )
        errors = validate_entry(entry)
        assert any("restricted" in e and "L0" in e for e in errors)

    def test_restricted_internal_l1_is_valid(self) -> None:
        entry = make_entry(sensitivity=Sensitivity.RESTRICTED)
        errors = validate_entry(entry)
        assert not any("restricted" in e for e in errors)


class TestL0MaxTTL:
    def test_l0_exceeding_168h_rejected(self) -> None:
        from datetime import timedelta

        created = minutes_after(0)
        entry = make_entry(
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            created_at=created,
            expires_at=created + timedelta(hours=169),
            review_required=False,
        )
        errors = validate_entry(entry)
        assert any("168" in e for e in errors)

    def test_l0_at_exactly_168h_valid(self) -> None:
        from datetime import timedelta

        created = minutes_after(0)
        entry = make_entry(
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            created_at=created,
            expires_at=created + timedelta(hours=168),
            review_required=False,
        )
        errors = validate_entry(entry)
        assert not any("168" in e for e in errors)
