from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from ambara.core.schema import (
    EntryType,
    EscalationLevel,
    Frontmatter,
    RecordedBy,
    Visibility,
    is_level_allowed,
    requires_pr,
)

from .conftest import BASE_NOW, make_entry


def test_frontmatter_accepts_valid_entry_id() -> None:
    fm = Frontmatter(
        id="principle-deterministic-core",
        title="Deterministic Core",
        type=EntryType.PRINCIPLE,
        level=EscalationLevel.L3,
        created_at=BASE_NOW,
        updated_at=BASE_NOW,
    )

    assert fm.id == "principle-deterministic-core"


@pytest.mark.parametrize("entry_id", ["ab", "Upper", "-starts-bad", "has space"])
def test_frontmatter_rejects_invalid_entry_ids(entry_id: str) -> None:
    with pytest.raises(ValidationError):
        Frontmatter(
            id=entry_id,
            title="Invalid",
            type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            created_at=BASE_NOW,
            updated_at=BASE_NOW,
        )


@pytest.mark.parametrize(
    ("entry_type", "level"),
    [
        (EntryType.ACTIVE, EscalationLevel.L0),
        (EntryType.PROJECT, EscalationLevel.L1),
        (EntryType.WORKFLOW, EscalationLevel.L2),
        (EntryType.DECISION, EscalationLevel.L3),
        (EntryType.PRINCIPLE, EscalationLevel.L3),
    ],
)
def test_allowed_escalation_levels(entry_type: EntryType, level: EscalationLevel) -> None:
    assert is_level_allowed(entry_type, level)


def test_disallowed_escalation_level() -> None:
    assert not is_level_allowed(EntryType.PRINCIPLE, EscalationLevel.L1)


@pytest.mark.parametrize("level", [EscalationLevel.L2, EscalationLevel.L3])
def test_requires_pr_for_high_stakes_levels(level: EscalationLevel) -> None:
    assert requires_pr(level)


@pytest.mark.parametrize("level", [EscalationLevel.L0, EscalationLevel.L1])
def test_lower_stakes_levels_do_not_require_pr_by_schema_rule(level: EscalationLevel) -> None:
    assert not requires_pr(level)


class TestVisibility:
    def test_values(self) -> None:
        assert Visibility.INTERNAL == "internal"
        assert Visibility.EXTERNAL == "external"

    def test_frontmatter_defaults_to_internal(self) -> None:
        fm = Frontmatter(
            id="test-viz",
            title="Test Visibility",
            type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            created_at=BASE_NOW,
            updated_at=BASE_NOW,
        )
        assert fm.visibility == Visibility.INTERNAL

    def test_frontmatter_accepts_external(self) -> None:
        fm = Frontmatter(
            id="test-ext",
            title="External",
            type=EntryType.DECISION,
            level=EscalationLevel.L2,
            created_at=BASE_NOW,
            updated_at=BASE_NOW,
            visibility=Visibility.EXTERNAL,
        )
        assert fm.visibility == Visibility.EXTERNAL


class TestRecordedBy:
    def test_is_frozen(self) -> None:
        rb = RecordedBy(client="claude-code")
        assert rb.client == "claude-code"
        with pytest.raises(ValidationError):
            rb.client = "other"  # type: ignore[misc]

    def test_frontmatter_defaults_to_none(self) -> None:
        fm = Frontmatter(
            id="test-rb",
            title="Test RB",
            type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            created_at=BASE_NOW,
            updated_at=BASE_NOW,
        )
        assert fm.recorded_by is None

    def test_frontmatter_accepts_recorded_by(self) -> None:
        fm = Frontmatter(
            id="test-rb-set",
            title="Test RB Set",
            type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            created_at=BASE_NOW,
            updated_at=BASE_NOW,
            recorded_by=RecordedBy(client="cursor"),
        )
        assert fm.recorded_by is not None
        assert fm.recorded_by.client == "cursor"


class TestReviewAfter:
    def test_frontmatter_defaults_to_no_review_after(self) -> None:
        fm = Frontmatter(
            id="review-after-default",
            title="Review After Default",
            type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            created_at=BASE_NOW,
            updated_at=BASE_NOW,
        )
        assert fm.review_after is None

    def test_frontmatter_accepts_review_after(self) -> None:
        fm = Frontmatter(
            id="review-after-set",
            title="Review After Set",
            type=EntryType.DECISION,
            level=EscalationLevel.L2,
            created_at=BASE_NOW,
            updated_at=BASE_NOW,
            review_after=BASE_NOW + timedelta(days=90),
        )
        assert fm.review_after == BASE_NOW + timedelta(days=90)


class TestSchemaV2:
    def test_schema_version_defaults_to_2(self) -> None:
        fm = Frontmatter(
            id="test-v2",
            title="V2 Default",
            type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            created_at=BASE_NOW,
            updated_at=BASE_NOW,
        )
        assert fm.schema_version == 2

    @pytest.mark.parametrize("version", [0, 3, 99])
    def test_unsupported_schema_version_rejected(self, version: int) -> None:
        with pytest.raises(ValidationError, match="schema_version"):
            Frontmatter(
                id="test-future",
                title="Future Schema",
                type=EntryType.PROJECT,
                level=EscalationLevel.L1,
                schema_version=version,
                created_at=BASE_NOW,
                updated_at=BASE_NOW,
            )

    def test_schema_version_1_accepted(self) -> None:
        fm = Frontmatter(
            id="test-v1",
            title="V1 Compat",
            type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            schema_version=1,
            created_at=BASE_NOW,
            updated_at=BASE_NOW,
        )
        assert fm.schema_version == 1


class TestOnSourceBranch:
    def test_entry_defaults_to_false(self) -> None:
        entry = make_entry()
        assert entry.on_source_branch is False

    def test_entry_accepts_true(self) -> None:
        entry = make_entry(on_source_branch=True)
        assert entry.on_source_branch is True
