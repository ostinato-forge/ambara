"""Schema, escalation, status, expiry, and supersession validation."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ambara.core.paths import entry_path
from ambara.core.schema import (
    ID_PATTERN,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Sensitivity,
    Visibility,
    is_level_allowed,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ambara.core.schema import Entry


def validate_entry(entry: Entry) -> list[str]:
    errors: list[str] = []
    fm = entry.frontmatter

    if not fm.title.strip():
        errors.append("title must not be empty")

    if not ID_PATTERN.match(fm.id):
        errors.append(f"id must match {ID_PATTERN.pattern}, got {fm.id!r}")

    if not is_level_allowed(fm.type, fm.level):
        errors.append(f"level {fm.level} is not allowed for type {fm.type}")

    expected_path = entry_path(fm.type, fm.id)
    if entry.path != expected_path:
        errors.append(f"path {entry.path!r} does not match expected {expected_path!r}")

    if fm.type == EntryType.ACTIVE and fm.expires_at is None:
        errors.append("active entries must have expires_at")

    if fm.expires_at is not None and fm.type != EntryType.ACTIVE:
        errors.append("only active entries should have expires_at")

    if fm.review_after is not None and fm.type == EntryType.ACTIVE:
        errors.append("active entries should use expires_at instead of review_after")

    if fm.updated_at < fm.created_at:
        errors.append("updated_at must be >= created_at")

    if fm.expires_at is not None and fm.expires_at <= fm.created_at:
        errors.append("expires_at must be > created_at")

    if fm.review_after is not None and fm.review_after < fm.created_at:
        errors.append("review_after must be >= created_at")

    if (
        fm.status == EntryStatus.ACTIVE
        and fm.level != EscalationLevel.L0
        and fm.review.pr is None
        and fm.review.required
    ):
        errors.append("L1/L2/L3 active entries must have review.pr set")

    for sid in fm.supersedes:
        if not ID_PATTERN.match(sid):
            errors.append(f"supersedes entry {sid!r} has invalid ID format")

    if fm.superseded_by is not None and not ID_PATTERN.match(fm.superseded_by):
        errors.append(f"superseded_by {fm.superseded_by!r} has invalid ID format")

    if fm.sensitivity == Sensitivity.RESTRICTED and fm.visibility == Visibility.EXTERNAL:
        errors.append("restricted entries cannot have visibility external")

    if fm.sensitivity == Sensitivity.RESTRICTED and fm.level == EscalationLevel.L0:
        errors.append("restricted entries cannot be L0 (active refs have no access control)")

    if (
        fm.level == EscalationLevel.L0
        and fm.expires_at is not None
        and (fm.expires_at - fm.created_at) > timedelta(hours=168)
    ):
        errors.append("L0 entries cannot have TTL exceeding 168 hours (7 days)")

    return errors


def is_expired(entry: Entry, now: datetime) -> bool:
    if entry.frontmatter.expires_at is None:
        return False
    return now >= entry.frontmatter.expires_at


def check_write_path(entry_type: EntryType, level: EscalationLevel) -> str:
    match level:
        case EscalationLevel.L0:
            return "active_ref"
        case EscalationLevel.L1:
            return "lightweight_pr"
        case EscalationLevel.L2 | EscalationLevel.L3:
            return "review_pr"
        case _:
            raise ValueError(f"Unexpected escalation level: {level}")
