from __future__ import annotations

import pytest
from pydantic import ValidationError

from jurati.core.schema import (
    EntryType,
    EscalationLevel,
    Frontmatter,
    is_level_allowed,
    requires_pr,
)

from .conftest import BASE_NOW


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
