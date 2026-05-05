"""BM25 inverted index and multi-signal ranking for Jurati search."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .schema import Entry, EntryType, Sensitivity
from .search import SearchResult

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_TYPE_WEIGHTS: dict[EntryType, float] = {
    EntryType.PRINCIPLE: 1.4,
    EntryType.DECISION: 1.2,
    EntryType.WORKFLOW: 1.1,
    EntryType.PROJECT: 1.0,
    EntryType.ACTIVE: 0.8,
}

_BM25_K1 = 1.5
_BM25_B = 0.75
_RECENCY_HALF_LIFE_DAYS = 14.0
_MIN_RELEVANCE_THRESHOLD = 0.1


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class InvertedIndex:
    doc_count: int = 0
    avg_doc_len: float = 0.0
    doc_lengths: dict[str, int] = field(default_factory=dict)
    doc_term_freq: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    term_doc_freq: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def build_inverted_index(entries: list[Entry]) -> InvertedIndex:
    idx = InvertedIndex()
    total_len = 0
    indexable = [e for e in entries if e.frontmatter.sensitivity != Sensitivity.RESTRICTED]
    idx.doc_count = len(indexable)

    for entry in indexable:
        doc_id = entry.frontmatter.id
        fm = entry.frontmatter
        text = f"{fm.title} {fm.title} {fm.title} {' '.join(fm.tags)} {entry.body}"
        tokens = tokenize(text)
        idx.doc_lengths[doc_id] = len(tokens)
        total_len += len(tokens)

        seen_terms: set[str] = set()
        for token in tokens:
            idx.doc_term_freq[doc_id][token] += 1
            if token not in seen_terms:
                idx.term_doc_freq[token] += 1
                seen_terms.add(token)

    idx.avg_doc_len = total_len / max(idx.doc_count, 1)
    return idx


def bm25_score(idx: InvertedIndex, doc_id: str, query: str) -> float:
    query_tokens = tokenize(query)
    if not query_tokens:
        return 0.0

    doc_len = idx.doc_lengths.get(doc_id, 0)
    if doc_len == 0:
        return 0.0

    score = 0.0
    for token in query_tokens:
        df = idx.term_doc_freq.get(token, 0)
        if df == 0:
            continue
        idf = math.log((idx.doc_count - df + 0.5) / (df + 0.5) + 1.0)
        tf = idx.doc_term_freq.get(doc_id, {}).get(token, 0)
        numerator = tf * (_BM25_K1 + 1)
        denominator = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * doc_len / idx.avg_doc_len)
        score += idf * numerator / denominator

    return score


def _recency_factor(entry: Entry, now: datetime) -> float:
    age_days = (now - entry.frontmatter.updated_at).total_seconds() / 86400.0
    return math.exp(-0.693 * age_days / _RECENCY_HALF_LIFE_DAYS)


def rank_entries(
    entries: list[Entry],
    query: str,
    *,
    now: datetime,
    repo: str | None = None,
    repo_deps: set[str] | None = None,
    max_results: int = 10,
    prebuilt_index: InvertedIndex | None = None,
) -> list[SearchResult]:
    idx = prebuilt_index if prebuilt_index is not None else build_inverted_index(entries)
    query_lower = query.lower()
    scored: list[tuple[float, Entry, list[str]]] = []

    for entry in (e for e in entries if e.frontmatter.sensitivity != Sensitivity.RESTRICTED):
        doc_id = entry.frontmatter.id

        # Check for exact match first (ID or title substring)
        exact_match = query_lower == doc_id or query_lower in entry.frontmatter.title.lower()

        bm25 = bm25_score(idx, doc_id, query)

        # If no BM25 match and no exact match, skip
        if bm25 == 0.0 and not exact_match:
            continue

        # For exact matches with zero BM25, give a small base score
        if bm25 == 0.0 and exact_match:
            bm25 = 0.5

        reasons: list[str] = ["bm25"]
        recency = _recency_factor(entry, now)
        type_w = _TYPE_WEIGHTS.get(entry.frontmatter.type, 1.0)

        repo_w = 1.0
        source = getattr(entry.frontmatter, "source", None)
        if repo and source:
            src_repo = source.repo
            if src_repo == repo:
                repo_w = 1.5
                reasons.append("same-repo")
            elif repo_deps and src_repo in repo_deps:
                repo_w = 1.2
                reasons.append("dependency-repo")

        # Exact match escalation: entry ID or title substring → large boost
        exact_boost = 1.0
        if exact_match:
            exact_boost = 10.0
            reasons.append("exact-match")

        combined = bm25 * recency * type_w * repo_w * exact_boost

        if combined >= _MIN_RELEVANCE_THRESHOLD:
            scored.append((combined, entry, reasons))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        SearchResult(entry=e, relevance=round(s, 4), match_reasons=r)
        for s, e, r in scored[:max_results]
    ]
