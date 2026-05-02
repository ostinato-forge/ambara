"""Entry validation and escalation rules."""

from __future__ import annotations

from datetime import datetime, timezone

from jurati.core.schema import Entry, EntryType, requires_pr


def validate_entry(entry: Entry) -> list[str]:
    errors: list[str] = []

    if not entry.frontmatter.title.strip():
        errors.append("Title must not be empty")

    if not entry.frontmatter.author.strip():
        errors.append("Author must not be empty")

    if entry.frontmatter.type == EntryType.ACTIVE and entry.frontmatter.expires is None:
        errors.append("Active entries must have an expiration date")

    if entry.frontmatter.expires is not None and entry.frontmatter.type != EntryType.ACTIVE:
        errors.append("Only active entries should have an expiration date")

    return errors


def is_expired(entry: Entry) -> bool:
    if entry.frontmatter.expires is None:
        return False
    return datetime.now(timezone.utc) >= entry.frontmatter.expires


def check_escalation(entry: Entry) -> str:
    if requires_pr(entry.frontmatter.type):
        return "pr"
    return "direct"
