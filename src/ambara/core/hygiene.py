# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Pure lifecycle hygiene summaries for knowledge entries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ambara.core.index import Index
from ambara.core.schema import Entry, EntryStatus, EntryType


@dataclass(frozen=True)
class HygieneItem:
    id: str
    title: str
    type: EntryType
    status: EntryStatus
    path: str
    updated_at: datetime
    expires_at: datetime | None
    review_after: datetime | None
    reason: str
    next_step: str


@dataclass(frozen=True)
class SupersessionLink:
    id: str
    title: str
    path: str
    supersedes: list[str]
    superseded_by: str | None
    next_step: str


@dataclass(frozen=True)
class HygieneReport:
    expired_active: list[HygieneItem]
    stale_proposed: list[HygieneItem]
    revalidation: list[HygieneItem]
    supersession: list[SupersessionLink]
    stale_after_days: int
    privacy_boundary: list[str]


def summarize_lifecycle(
    index: Index,
    *,
    now: datetime,
    stale_after_days: int = 30,
) -> HygieneReport:
    """Summarize stale knowledge without using activity or participation signals."""
    stale_cutoff = now - timedelta(days=stale_after_days)
    expired_active: list[HygieneItem] = []
    stale_proposed: list[HygieneItem] = []
    revalidation: list[HygieneItem] = []
    supersession: list[SupersessionLink] = []

    for entry in index.entries.values():
        if _is_expired_active(entry, now):
            expired_active.append(
                _hygiene_item(
                    entry,
                    reason="active context is past expires_at",
                    next_step=(
                        "Clean it up silently if it no longer affects the current work; "
                        "do not ask the developer to manage lifecycle details."
                    ),
                )
            )

        if _is_stale_proposed(entry, stale_cutoff):
            stale_proposed.append(
                _hygiene_item(
                    entry,
                    reason=f"proposed entry has not changed in {stale_after_days}+ days",
                    next_step=(
                        "Treat it as review context only when it affects the task; "
                        "do not ask the developer to manage the knowledge workflow."
                    ),
                )
            )

        if _needs_revalidation(entry, now):
            revalidation.append(
                _hygiene_item(
                    entry,
                    reason="review_after has passed",
                    next_step=(
                        "Treat it as a prompt to verify the entry if it affects the task; "
                        "do not ask the developer to manage the knowledge workflow."
                    ),
                )
            )

        if entry.frontmatter.supersedes or entry.frontmatter.superseded_by:
            supersession.append(
                SupersessionLink(
                    id=entry.frontmatter.id,
                    title=entry.frontmatter.title,
                    path=entry.path,
                    supersedes=entry.frontmatter.supersedes,
                    superseded_by=entry.frontmatter.superseded_by,
                    next_step=(
                        "Use the current replacement when it affects the work; "
                        "keep cleanup mechanics out of developer-facing replies."
                    ),
                )
            )

    return HygieneReport(
        expired_active=sorted(expired_active, key=lambda item: item.updated_at),
        stale_proposed=sorted(stale_proposed, key=lambda item: item.updated_at),
        revalidation=sorted(revalidation, key=lambda item: item.review_after or item.updated_at),
        supersession=sorted(supersession, key=lambda item: item.id),
        stale_after_days=stale_after_days,
        privacy_boundary=[
            "based only on entry metadata and explicit expires_at values",
            "review_after is an explicit repo-owned lifecycle field",
            "does not infer absence or participation from missing updates",
            "does not use query logs, read receipts, editor activity, or telemetry",
        ],
    )


def _is_expired_active(entry: Entry, now: datetime) -> bool:
    fm = entry.frontmatter
    return (
        fm.type == EntryType.ACTIVE
        and fm.status == EntryStatus.ACTIVE
        and fm.expires_at is not None
        and now >= fm.expires_at
    )


def _is_stale_proposed(entry: Entry, stale_cutoff: datetime) -> bool:
    fm = entry.frontmatter
    return fm.status == EntryStatus.PROPOSED and fm.updated_at <= stale_cutoff


def _needs_revalidation(entry: Entry, now: datetime) -> bool:
    fm = entry.frontmatter
    return (
        fm.type != EntryType.ACTIVE
        and fm.review_after is not None
        and fm.review_after <= now
        and fm.status == EntryStatus.ACTIVE
    )


def _hygiene_item(entry: Entry, *, reason: str, next_step: str) -> HygieneItem:
    fm = entry.frontmatter
    return HygieneItem(
        id=fm.id,
        title=fm.title,
        type=fm.type,
        status=fm.status,
        path=entry.path,
        updated_at=fm.updated_at,
        expires_at=fm.expires_at,
        review_after=fm.review_after,
        reason=reason,
        next_step=next_step,
    )
