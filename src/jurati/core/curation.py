"""Contradiction detection and staleness scanning."""

from __future__ import annotations

from datetime import datetime, timedelta

from .schema import Entry, EntryStatus, EntryType
from .scoring import tokenize


def detect_contradictions(
    new_title: str,
    existing_entries: list[Entry],
    *,
    entry_type: EntryType | None = None,
    threshold: float = 0.4,
) -> list[Entry]:
    new_tokens = set(tokenize(new_title))
    if not new_tokens:
        return []

    conflicts: list[Entry] = []
    for entry in existing_entries:
        if entry_type and entry.frontmatter.type != entry_type:
            continue
        if entry.frontmatter.status in (EntryStatus.EXPIRED, EntryStatus.SUPERSEDED):
            continue

        existing_tokens = set(tokenize(entry.frontmatter.title))
        if not existing_tokens:
            continue

        overlap = len(new_tokens & existing_tokens) / min(len(new_tokens), len(existing_tokens))
        if overlap >= threshold:
            conflicts.append(entry)

    return conflicts


def find_stale_entries(
    entries: list[Entry],
    *,
    now: datetime,
    stale_after_days: int = 90,
) -> list[Entry]:
    cutoff = now - timedelta(days=stale_after_days)
    stale: list[Entry] = []
    for entry in entries:
        if entry.frontmatter.type == EntryType.ACTIVE:
            continue
        if entry.frontmatter.status in (EntryStatus.EXPIRED, EntryStatus.SUPERSEDED):
            continue
        if entry.frontmatter.updated_at < cutoff:
            stale.append(entry)
    return stale
