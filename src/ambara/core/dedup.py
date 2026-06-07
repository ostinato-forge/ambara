# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Pure advisory checks for avoiding duplicate or stale write context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ambara.core.index import Index
from ambara.core.schema import Entry, EntryStatus, EntryType, Sensitivity
from ambara.core.validate import is_expired

_MIN_TITLE_MATCH_LENGTH = 5


@dataclass(frozen=True)
class ConflictEntry:
    id: str
    title: str
    type: EntryType
    status: EntryStatus
    path: str
    reason: str


@dataclass(frozen=True)
class WriteConflicts:
    duplicates: tuple[ConflictEntry, ...] = ()
    expired_active: tuple[ConflictEntry, ...] = ()
    stale_proposed: tuple[ConflictEntry, ...] = ()

    @property
    def has_conflicts(self) -> bool:
        return bool(self.duplicates or self.expired_active or self.stale_proposed)


def check_write_conflicts(
    index: Index,
    *,
    title: str,
    entry_type: EntryType,
    projects: list[str] | None = None,
    now: datetime,
    stale_after_days: int = 30,
) -> WriteConflicts:
    """Return non-blocking write advisories from explicit entry metadata only."""
    proposed_projects = set(projects or [])
    stale_cutoff = now - timedelta(days=stale_after_days)
    duplicates: list[ConflictEntry] = []
    expired_active: list[ConflictEntry] = []
    stale_proposed: list[ConflictEntry] = []

    for entry in index.entries.values():
        fm = entry.frontmatter
        if fm.sensitivity == Sensitivity.RESTRICTED:
            continue

        if (
            fm.type == entry_type
            and fm.status != EntryStatus.EXPIRED
            and not is_expired(entry, now)
            and _title_matches(title, fm.title)
        ):
            duplicates.append(
                _conflict_entry(
                    entry,
                    reason="existing non-expired entry has a similar title and type",
                )
            )

        if _has_project_overlap(proposed_projects, fm.projects):
            if _is_expired_active(entry, now):
                expired_active.append(
                    _conflict_entry(
                        entry,
                        reason="expired active context overlaps the proposed projects",
                    )
                )
            if (
                fm.type == entry_type
                and fm.status == EntryStatus.PROPOSED
                and fm.updated_at <= stale_cutoff
            ):
                stale_proposed.append(
                    _conflict_entry(
                        entry,
                        reason=(
                            f"proposed {entry_type} entry has not changed in "
                            f"{stale_after_days}+ days"
                        ),
                    )
                )

    return WriteConflicts(
        duplicates=tuple(sorted(duplicates, key=lambda item: item.id)),
        expired_active=tuple(sorted(expired_active, key=lambda item: item.id)),
        stale_proposed=tuple(sorted(stale_proposed, key=lambda item: item.id)),
    )


def _conflict_entry(entry: Entry, *, reason: str) -> ConflictEntry:
    fm = entry.frontmatter
    return ConflictEntry(
        id=fm.id,
        title=fm.title,
        type=fm.type,
        status=fm.status,
        path=entry.path,
        reason=reason,
    )


def _title_matches(proposed: str, existing: str) -> bool:
    proposed_normalized = _normalize_title(proposed)
    existing_normalized = _normalize_title(existing)
    if not proposed_normalized or not existing_normalized:
        return False
    if proposed_normalized == existing_normalized:
        return True
    if (
        len(proposed_normalized) < _MIN_TITLE_MATCH_LENGTH
        or len(existing_normalized) < _MIN_TITLE_MATCH_LENGTH
    ):
        return False
    return proposed_normalized in existing_normalized or existing_normalized in proposed_normalized


def _normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


def _has_project_overlap(proposed: set[str], existing: list[str]) -> bool:
    return bool(proposed and existing and proposed.intersection(existing))


def _is_expired_active(entry: Entry, now: datetime) -> bool:
    fm = entry.frontmatter
    return fm.type == EntryType.ACTIVE and fm.expires_at is not None and now >= fm.expires_at
