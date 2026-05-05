from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from jurati.core.paths import entry_path
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
    Sensitivity,
    Visibility,
)

BASE_NOW = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)


@pytest.fixture
def fixed_now() -> datetime:
    return BASE_NOW


def make_entry(
    *,
    entry_id: str = "test-entry",
    title: str = "Test Entry",
    entry_type: EntryType = EntryType.PROJECT,
    level: EscalationLevel = EscalationLevel.L1,
    status: EntryStatus = EntryStatus.PROPOSED,
    created_at: datetime = BASE_NOW,
    updated_at: datetime | None = None,
    expires_at: datetime | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    body: str = "Body text",
    path: str | None = None,
    review_required: bool = True,
    review_pr: str | None = None,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    visibility: Visibility = Visibility.INTERNAL,
    on_source_branch: bool = False,
    **frontmatter_overrides: Any,
) -> Entry:
    fm = Frontmatter(
        id=entry_id,
        title=title,
        type=entry_type,
        level=level,
        status=status,
        created_at=created_at,
        updated_at=updated_at or created_at,
        expires_at=expires_at,
        projects=projects or [],
        tags=tags or [],
        review=ReviewMeta(required=review_required, pr=review_pr),
        sensitivity=sensitivity,
        visibility=visibility,
        **frontmatter_overrides,
    )
    return Entry(
        path=path or entry_path(entry_type, entry_id),
        frontmatter=fm,
        body=body,
        on_source_branch=on_source_branch,
    )


def minutes_after(value: int) -> datetime:
    return BASE_NOW + timedelta(minutes=value)
