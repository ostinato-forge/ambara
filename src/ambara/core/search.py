# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Pure query, filter, and relevance logic against the index."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from ambara.core.index import Index
    from ambara.core.schema import Entry, EntryStatus, EntryType


@dataclass
class SearchResult:
    entry: Entry
    relevance: float
    match_reasons: list[str]


def query(
    index: Index,
    topic: str,
    *,
    now: datetime,
    entry_type: EntryType | None = None,
    project: str | None = None,
    status: EntryStatus | None = None,
    include_expired: bool = False,
    since: datetime | None = None,
) -> list[SearchResult]:
    candidates = index.list_entries(
        now=now,
        entry_type=entry_type,
        project=project,
        status=status,
        include_expired=include_expired,
    )

    if since is not None:
        candidates = [e for e in candidates if e.frontmatter.updated_at >= since]

    topic_lower = topic.lower()
    results: list[SearchResult] = []

    for entry in candidates:
        score, reasons = _score(entry, topic_lower)
        if score > 0:
            results.append(
                SearchResult(
                    entry=entry,
                    relevance=score,
                    match_reasons=reasons,
                )
            )

    return sorted(results, key=lambda r: r.relevance, reverse=True)


def _score(entry: Entry, topic: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    title = entry.frontmatter.title.lower()
    entry_id = entry.frontmatter.id.lower()
    body = entry.body.lower()
    tags = [t.lower() for t in entry.frontmatter.tags]

    if topic in title:
        score += 3.0
        reasons.append("title contains the query topic")
    if topic in entry_id:
        score += 2.5
        reasons.append("id contains the query topic")
    if topic in tags:
        score += 2.0
        reasons.append("tag exactly matches the query topic")
    if topic in body:
        score += 1.0
        reasons.append("body contains the query topic")

    return score, reasons
