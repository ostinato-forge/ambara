"""Pure write-intent planning — no I/O, no git, no filesystem."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from jurati.core.paths import entry_path
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
    is_level_allowed,
)
from jurati.core.validate import check_write_path


@dataclass(frozen=True)
class WriteIntent:
    path: str
    content: str
    branch: str | None
    write_mode: str
    entry_id: str
    level: EscalationLevel


@dataclass(frozen=True)
class ExpireIntent:
    entry_id: str
    path: str
    write_mode: str
    branch: str | None
    new_status: EntryStatus


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
    branch_prefix: str = "jurati",
    active_ref_prefix: str = "jurati/active",
    client: str | None = None,
) -> WriteIntent:
    if level is None:
        from jurati.core.schema import DEFAULT_LEVEL_MAP
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
    )

    content = _render_entry(fm, body)

    return WriteIntent(
        path=path,
        content=content,
        branch=branch,
        write_mode=write_mode,
        entry_id=entry_id,
        level=level,
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
    branch_prefix: str = "jurati",
) -> WriteIntent:
    if level is None:
        from jurati.core.schema import DEFAULT_LEVEL_MAP
        level = DEFAULT_LEVEL_MAP[entry_type][0]

    if not is_level_allowed(entry_type, level):
        raise ValueError(f"Level {level} not allowed for type {entry_type}")

    if level in (EscalationLevel.L0, EscalationLevel.L1):
        raise ValueError(f"propose() cannot create {level} content; use record()")

    path = entry_path(entry_type, entry_id)
    branch = f"{branch_prefix}/{entry_id}"

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
    )

    content = _render_entry(fm, body)

    return WriteIntent(
        path=path,
        content=content,
        branch=branch,
        write_mode="review_pr",
        entry_id=entry_id,
        level=level,
    )


def plan_expire(entry: Entry, *, now: datetime) -> ExpireIntent:
    write_mode = check_write_path(entry.frontmatter.type, entry.frontmatter.level)

    if entry.frontmatter.level == EscalationLevel.L0:
        branch = None
    else:
        branch = f"jurati/expire-{entry.frontmatter.id}"

    return ExpireIntent(
        entry_id=entry.frontmatter.id,
        path=entry.path,
        write_mode=write_mode,
        branch=branch,
        new_status=EntryStatus.EXPIRED,
    )


def _render_entry(fm: Frontmatter, body: str) -> str:
    lines = ["---"]
    lines.append(f"schema_version: {fm.schema_version}")
    lines.append(f"id: {fm.id}")
    lines.append(f"title: {fm.title}")
    lines.append(f"type: {fm.type}")
    lines.append(f"level: {fm.level}")
    lines.append(f"status: {fm.status}")
    lines.append(f"created_at: {_format_timestamp(fm.created_at)}")
    lines.append(f"updated_at: {_format_timestamp(fm.updated_at)}")
    if fm.expires_at is not None:
        lines.append(f"expires_at: {_format_timestamp(fm.expires_at)}")
    else:
        lines.append("expires_at: null")
    lines.append(f"projects: {fm.projects}")
    lines.append(f"tags: {fm.tags}")
    lines.append(f"supersedes: {fm.supersedes}")
    if fm.superseded_by:
        lines.append(f"superseded_by: {fm.superseded_by!r}")
    else:
        lines.append("superseded_by: null")
    lines.append(f"sensitivity: {fm.sensitivity}")
    lines.append("review:")
    lines.append(f"  required: {str(fm.review.required).lower()}")
    lines.append(f"  pr: {fm.review.pr!r}" if fm.review.pr else "  pr: null")
    lines.append("---")
    lines.append("")
    lines.append(body)
    return "\n".join(lines)


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
