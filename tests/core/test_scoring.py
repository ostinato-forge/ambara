# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for ambara.core.scoring — BM25 inverted index and multi-signal ranking."""

from __future__ import annotations

from datetime import UTC, datetime

from ambara.core.schema import EntryType, EscalationLevel, Sensitivity
from ambara.core.scoring import (
    bm25_score,
    build_inverted_index,
    rank_entries,
    tokenize,
)

from .conftest import BASE_NOW, make_entry


class TestTokenize:
    def test_lowercase_split(self) -> None:
        tokens = tokenize("Postgres Pool Limit")
        assert tokens == ["postgres", "pool", "limit"]

    def test_strips_punctuation(self) -> None:
        tokens = tokenize("what's the caching strategy?")
        assert "whats" in tokens or "what" in tokens
        assert "caching" in tokens
        assert "strategy" in tokens

    def test_empty_string(self) -> None:
        assert tokenize("") == []


class TestBuildInvertedIndex:
    def test_builds_from_entries(self) -> None:
        entries = [
            make_entry(entry_id="entry-1", title="postgres pool limit", body="OOM fix"),
            make_entry(entry_id="entry-2", title="redis cache strategy", body="TTL design"),
        ]
        idx = build_inverted_index(entries)
        assert "postgres" in idx.term_doc_freq
        assert "redis" in idx.term_doc_freq
        assert idx.doc_count == 2

    def test_restricted_entries_excluded_from_index(self) -> None:
        normal = make_entry(
            entry_id="normal-entry", title="Auth config", body="Token rotation policy"
        )
        restricted = make_entry(
            entry_id="restricted-entry",
            title="Auth secrets",
            body="Token rotation policy for secrets",
            sensitivity=Sensitivity.RESTRICTED,
        )
        idx = build_inverted_index([normal, restricted])
        assert "normal-entry" in idx.doc_lengths
        assert "restricted-entry" not in idx.doc_lengths
        assert idx.doc_count == 1

    def test_term_frequency_counts(self) -> None:
        entries = [
            make_entry(entry_id="entry-1", title="pool pool pool", body="pool"),
        ]
        idx = build_inverted_index(entries)
        # Title is tripled in index text for title-boosting: 3×3 + 1 body = 10
        assert idx.doc_term_freq["entry-1"]["pool"] == 10


class TestBm25Score:
    def test_matching_query_scores_positive(self) -> None:
        entries = [
            make_entry(entry_id="entry-1", title="postgres pool limit"),
            make_entry(entry_id="entry-2", title="redis cache"),
        ]
        idx = build_inverted_index(entries)
        score = bm25_score(idx, "entry-1", "postgres pool")
        assert score > 0.0

    def test_non_matching_query_scores_zero(self) -> None:
        entries = [
            make_entry(entry_id="entry-1", title="postgres pool limit"),
        ]
        idx = build_inverted_index(entries)
        score = bm25_score(idx, "entry-1", "redis cache")
        assert score == 0.0

    def test_exact_title_match_scores_highest(self) -> None:
        entries = [
            make_entry(entry_id="entry-1", title="postgres pool limit", body="details"),
            make_entry(entry_id="entry-2", title="redis pool config", body="postgres note"),
        ]
        idx = build_inverted_index(entries)
        s1 = bm25_score(idx, "entry-1", "postgres pool limit")
        s2 = bm25_score(idx, "entry-2", "postgres pool limit")
        assert s1 > s2


class TestRankEntries:
    def test_returns_sorted_by_relevance(self) -> None:
        e1 = make_entry(entry_id="entry-1", title="postgres pool limit")
        e2 = make_entry(entry_id="entry-2", title="redis cache strategy")
        entries = [e1, e2]
        results = rank_entries(entries, "postgres pool", now=BASE_NOW)
        assert len(results) >= 1
        assert results[0].entry.frontmatter.id == "entry-1"

    def test_honest_zero(self) -> None:
        e1 = make_entry(entry_id="entry-1", title="postgres pool limit")
        results = rank_entries([e1], "kubernetes deployment", now=BASE_NOW)
        assert len(results) == 0

    def test_deterministic(self) -> None:
        entries = [
            make_entry(entry_id="entry-1", title="postgres pool"),
            make_entry(entry_id="entry-2", title="redis cache"),
        ]
        r1 = rank_entries(entries, "pool", now=BASE_NOW)
        r2 = rank_entries(entries, "pool", now=BASE_NOW)
        assert [r.entry.frontmatter.id for r in r1] == [r.entry.frontmatter.id for r in r2]

    def test_recency_boost(self) -> None:
        old = make_entry(
            entry_id="entry-old",
            title="pool limit",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        new = make_entry(
            entry_id="entry-new",
            title="pool limit",
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
            updated_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        results = rank_entries([old, new], "pool limit", now=BASE_NOW)
        assert results[0].entry.frontmatter.id == "entry-new"

    def test_exact_id_match_ranks_first(self) -> None:
        e1 = make_entry(entry_id="pool-limit", title="other stuff about pools")
        e2 = make_entry(entry_id="cache-ttl", title="pool limit config")
        results = rank_entries([e1, e2], "pool-limit", now=BASE_NOW)
        assert results[0].entry.frontmatter.id == "pool-limit"

    def test_exact_title_substring_ranks_first(self) -> None:
        e1 = make_entry(entry_id="entry-1", title="postgres pool limit")
        e2 = make_entry(entry_id="entry-2", title="pool configuration details and pool")
        results = rank_entries([e1, e2], "postgres pool limit", now=BASE_NOW)
        assert results[0].entry.frontmatter.id == "entry-1"

    def test_restricted_entries_excluded_from_results(self) -> None:
        normal = make_entry(entry_id="visible-entry", title="Auth config", body="Token rotation")
        restricted = make_entry(
            entry_id="hidden-entry",
            title="Auth config",
            body="Token rotation",
            sensitivity=Sensitivity.RESTRICTED,
        )
        results = rank_entries([normal, restricted], "auth config", now=BASE_NOW)
        ids = [r.entry.frontmatter.id for r in results]
        assert "visible-entry" in ids
        assert "hidden-entry" not in ids

    def test_type_weight_principles_rank_higher(self) -> None:
        proj = make_entry(
            entry_id="entry-proj",
            title="deterministic cores",
            entry_type=EntryType.PROJECT,
            level=EscalationLevel.L1,
        )
        princ = make_entry(
            entry_id="entry-princ",
            title="deterministic cores",
            entry_type=EntryType.PRINCIPLE,
            level=EscalationLevel.L3,
        )
        results = rank_entries([proj, princ], "deterministic cores", now=BASE_NOW)
        assert results[0].entry.frontmatter.id == "entry-princ"
