# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Pure write-intent planning — no I/O, no git, no filesystem."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import frontmatter

from ambara.core.events import EventRecord, EventType
from ambara.core.paths import entry_path
from ambara.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    RecordedBy,
    ReviewMeta,
    SourceMeta,
    Visibility,
    is_level_allowed,
    requires_pr,
)
from ambara.core.time import format_timestamp
from ambara.core.validate import check_write_path


@dataclass(frozen=True)
class WriteIntent:
    path: str
    content: str
    branch: str | None
    write_mode: str
    entry_id: str
    level: EscalationLevel
    entry: Entry | None = None
    event: EventRecord | None = None


@dataclass(frozen=True)
class ExpireIntent:
    entry_id: str
    path: str
    write_mode: str
    branch: str | None
    new_status: EntryStatus
    event: EventRecord | None = None


def plan_record(
    entry_type: EntryType,
    title: str,
    body: str,
    *,
    entry_id: str,
    level: EscalationLevel | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    now: datetime,
    expires_at: datetime | None = None,
    branch_prefix: str = "ambara",
    active_ref_prefix: str = "ambara/active",
    client: str | None = None,
    visibility: Visibility | None = None,
) -> WriteIntent:
    if level is None:
        from ambara.core.schema import DEFAULT_LEVEL_MAP

        level = DEFAULT_LEVEL_MAP[entry_type][0]

    if not is_level_allowed(entry_type, level):
        raise ValueError(f"Level {level} not allowed for type {entry_type}")

    if level in (EscalationLevel.L2, EscalationLevel.L3):
        raise ValueError(f"record() cannot create {level} content; use propose()")

    if entry_type == EntryType.ACTIVE and expires_at is None:
        raise ValueError("active records require expires_at")

    if entry_type != EntryType.ACTIVE and expires_at is not None:
        raise ValueError("only active records may set expires_at")

    path = entry_path(entry_type, entry_id)
    write_mode = check_write_path(entry_type, level)

    if write_mode == "active_ref":
        if client is None:
            raise ValueError("L0 active records require a client slug")
        branch = f"{active_ref_prefix}/{client}/{entry_id}"
    else:
        branch = f"{branch_prefix}/{entry_id}"

    recorded_by = RecordedBy(client=client) if client else None

    if level == EscalationLevel.L0:
        resolved_visibility = Visibility.INTERNAL
    else:
        resolved_visibility = visibility if visibility is not None else Visibility.INTERNAL

    fm = Frontmatter(
        id=entry_id,
        title=title,
        type=entry_type,
        level=level,
        status=EntryStatus.PROPOSED if level != EscalationLevel.L0 else EntryStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        expires_at=expires_at,
        projects=projects or [],
        tags=tags or [],
        review=ReviewMeta(required=level != EscalationLevel.L0),
        visibility=resolved_visibility,
        recorded_by=recorded_by,
    )

    content = _render_entry(fm, body)

    event = None
    if level != EscalationLevel.L0:
        event = EventRecord(
            timestamp=now,
            event_type=EventType.ENTRY_PROPOSED,
            entry_id=entry_id,
            entry_type=str(entry_type),
            level=str(level),
            visibility=str(resolved_visibility),
        )

    return WriteIntent(
        path=path,
        content=content,
        branch=branch,
        write_mode=write_mode,
        entry_id=entry_id,
        level=level,
        entry=Entry(path=path, frontmatter=fm, body=body),
        event=event,
    )


def plan_propose(
    entry_type: EntryType,
    title: str,
    body: str,
    *,
    entry_id: str,
    level: EscalationLevel | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    now: datetime,
    branch_prefix: str = "ambara",
    client: str | None = None,
    visibility: Visibility | None = None,
) -> WriteIntent:
    if level is None:
        from ambara.core.schema import DEFAULT_LEVEL_MAP

        level = DEFAULT_LEVEL_MAP[entry_type][0]

    if not is_level_allowed(entry_type, level):
        raise ValueError(f"Level {level} not allowed for type {entry_type}")

    if level in (EscalationLevel.L0, EscalationLevel.L1):
        raise ValueError(f"propose() cannot create {level} content; use record()")

    if entry_type == EntryType.ACTIVE:
        raise ValueError("propose() cannot create ACTIVE entries; use record()")

    path = entry_path(entry_type, entry_id)
    branch = f"{branch_prefix}/{entry_id}"

    recorded_by = RecordedBy(client=client) if client else None
    resolved_visibility = visibility if visibility is not None else Visibility.EXTERNAL

    fm = Frontmatter(
        id=entry_id,
        title=title,
        type=entry_type,
        level=level,
        status=EntryStatus.PROPOSED,
        created_at=now,
        updated_at=now,
        projects=projects or [],
        tags=tags or [],
        review=ReviewMeta(required=True),
        visibility=resolved_visibility,
        recorded_by=recorded_by,
    )

    content = _render_entry(fm, body)

    event = EventRecord(
        timestamp=now,
        event_type=EventType.ENTRY_PROPOSED,
        entry_id=entry_id,
        entry_type=str(entry_type),
        level=str(level),
        visibility=str(resolved_visibility),
    )

    return WriteIntent(
        path=path,
        content=content,
        branch=branch,
        write_mode="review_pr",
        entry_id=entry_id,
        level=level,
        entry=Entry(path=path, frontmatter=fm, body=body),
        event=event,
    )


def plan_capture(
    entry_type: EntryType,
    title: str,
    body: str = "",
    *,
    entry_id: str,
    level: EscalationLevel,
    now: datetime,
    source: SourceMeta | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    branch_prefix: str = "ambara",
) -> WriteIntent:
    write_mode = check_write_path(entry_type, level)
    path = entry_path(entry_type, entry_id)

    # Branch uses repo slug from source for namespace isolation
    repo_slug = source.repo if source else None
    entry_suffix = entry_id
    if repo_slug and entry_id.startswith(f"{repo_slug}-"):
        entry_suffix = entry_id[len(repo_slug) + 1 :]

    if write_mode == "active_ref":
        branch = None
    elif repo_slug:
        branch = f"{branch_prefix}/{repo_slug}/{entry_suffix}"
    else:
        branch = f"{branch_prefix}/{entry_id}"

    status = EntryStatus.ACTIVE if level == EscalationLevel.L0 else EntryStatus.PROPOSED

    fm = Frontmatter(
        id=entry_id,
        title=title,
        type=entry_type,
        level=level,
        status=status,
        created_at=now,
        updated_at=now,
        projects=projects or [],
        tags=tags or [],
        review=ReviewMeta(required=requires_pr(level)),
        source=source,
    )

    content = _render_entry(fm, body)

    event = None
    if level != EscalationLevel.L0:
        event = EventRecord(
            timestamp=now,
            event_type=EventType.ENTRY_PROPOSED,
            entry_id=entry_id,
            entry_type=str(entry_type),
            level=str(level),
            visibility=str(fm.visibility),
        )

    return WriteIntent(
        path=path,
        content=content,
        branch=branch,
        write_mode=write_mode,
        entry_id=entry_id,
        level=level,
        entry=Entry(path=path, frontmatter=fm, body=body),
        event=event,
    )


def plan_expire(entry: Entry, *, now: datetime) -> ExpireIntent:
    write_mode = check_write_path(entry.frontmatter.type, entry.frontmatter.level)

    if entry.frontmatter.level == EscalationLevel.L0:
        branch = None
    else:
        branch = f"ambara/expire-{entry.frontmatter.id}"

    event = None
    if entry.frontmatter.level != EscalationLevel.L0:
        event = EventRecord(
            timestamp=now,
            event_type=EventType.ENTRY_EXPIRED,
            entry_id=entry.frontmatter.id,
            entry_type=str(entry.frontmatter.type),
            level=str(entry.frontmatter.level),
            visibility=str(entry.frontmatter.visibility),
        )

    return ExpireIntent(
        entry_id=entry.frontmatter.id,
        path=entry.path,
        write_mode=write_mode,
        branch=branch,
        new_status=EntryStatus.EXPIRED,
        event=event,
    )


def render_entry(fm: Frontmatter, body: str) -> str:
    return _render_entry(fm, body)


def _render_entry(fm: Frontmatter, body: str) -> str:
    post = frontmatter.Post(body)
    post.metadata.update(_frontmatter_dict(fm))
    rendered: str = frontmatter.dumps(post, sort_keys=False)
    return rendered


def _frontmatter_dict(fm: Frontmatter) -> dict[str, object]:
    metadata: dict[str, object] = {
        "schema_version": fm.schema_version,
        "id": fm.id,
        "title": fm.title,
        "type": str(fm.type),
        "level": str(fm.level),
        "status": str(fm.status),
        "created_at": format_timestamp(fm.created_at),
        "updated_at": format_timestamp(fm.updated_at),
        "expires_at": format_timestamp(fm.expires_at) if fm.expires_at is not None else None,
        "projects": fm.projects,
        "tags": fm.tags,
        "supersedes": fm.supersedes,
        "superseded_by": fm.superseded_by,
        "sensitivity": str(fm.sensitivity),
        "review": {
            "required": fm.review.required,
            "pr": fm.review.pr,
        },
    }
    if fm.source is not None:
        metadata["source"] = {
            "repo": fm.source.repo,
            "commit": fm.source.commit,
        }
    if fm.review_after is not None:
        metadata["review_after"] = format_timestamp(fm.review_after)
    metadata["visibility"] = str(fm.visibility)
    if fm.recorded_by is not None:
        metadata["recorded_by"] = {"client": fm.recorded_by.client}
    return metadata
