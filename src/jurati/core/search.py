"""Query and filter logic against the index."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from jurati.core.index import Index
from jurati.core.schema import Entry, EntryType


@dataclass
class SearchResult:
    entry: Entry
    relevance: float


def query(
    index: Index,
    topic: str,
    *,
    entry_type: EntryType | None = None,
    project: str | None = None,
    since: date | None = None,
) -> list[SearchResult]:
    candidates = index.list_entries(entry_type=entry_type, project=project)

    if since is not None:
        candidates = [e for e in candidates if e.frontmatter.date >= since]

    topic_lower = topic.lower()
    results: list[SearchResult] = []

    for entry in candidates:
        score = _score(entry, topic_lower)
        if score > 0:
            results.append(SearchResult(entry=entry, relevance=score))

    return sorted(results, key=lambda r: r.relevance, reverse=True)


def _score(entry: Entry, topic: str) -> float:
    score = 0.0
    title = entry.frontmatter.title.lower()
    body = entry.body.lower()
    tags = [t.lower() for t in entry.frontmatter.tags]

    if topic in title:
        score += 3.0
    if topic in tags:
        score += 2.0
    if topic in body:
        score += 1.0

    return score
