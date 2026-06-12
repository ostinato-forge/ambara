# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Contradiction detection, staleness scanning, and curation advisories."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from .pr_signals import (
    CoordinationSignal,
    SignalLike,
    SourceInputLike,
    coordination_signal_from_any,
)
from .schema import Entry, EntryStatus, EntryType
from .scoring import tokenize

_COMPLETED_SOURCE_INPUT_STATES = frozenset({"merged", "resolved"})
_LOW_VALUE_SOURCE_INPUT_TERMS = frozenset({"ambara", "src", "test", "tests", "api"})
_LOW_VALUE_CURATION_TERMS = _LOW_VALUE_SOURCE_INPUT_TERMS | frozenset(
    {
        "app",
        "code",
        "config",
        "decision",
        "decisions",
        "doc",
        "docs",
        "file",
        "issue",
        "lib",
        "project",
        "readme",
        "service",
        "system",
        "workflow",
        "workflows",
    }
)
_MIN_REVALIDATION_CONFIDENCE = 0.45
_MIN_SINGLE_TERM_CONFIDENCE = 0.55
_ENTRY_TERM_WEIGHTS = {
    "project": 1.15,
    "tag": 1.25,
    "title": 0.55,
}
_SOURCE_INPUT_TERM_WEIGHTS = {
    "label": 0.75,
    "subject_area": 1.15,
    "subject_ref": 1.35,
}


@dataclass(frozen=True)
class CurationAdvisory:
    entry_id: str
    entry_title: str
    entry_type: EntryType
    suggested_action: Literal["revalidate"]
    reason: str
    signal_id: str
    signal_source: str
    artifact_ref: str
    artifact_title: str
    actor: str
    changed_paths: tuple[str, ...]
    matched_terms: tuple[str, ...]
    merged_at: datetime
    confidence: float = 0.0
    match_reasons: tuple[str, ...] = ()

    @property
    def source_input_id(self) -> str:
        return self.signal_id

    @property
    def source_input_source(self) -> str:
        return self.signal_source


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


def suggest_revalidation_from_source_inputs(
    entries: Sequence[Entry],
    source_inputs: Sequence[SourceInputLike],
    *,
    now: datetime,
    recency_days: int = 30,
) -> list[CurationAdvisory]:
    """Suggest durable entries to revalidate after completed source artifacts."""

    cutoff = now - timedelta(days=recency_days)
    advisories: list[CurationAdvisory] = []
    term_stats = _build_entry_term_stats(entries)

    for source_input in source_inputs:
        coordination = coordination_signal_from_any(source_input, now=now)
        merged_at = coordination.resolved_at or coordination.updated_at
        if coordination.state not in _COMPLETED_SOURCE_INPUT_STATES or merged_at < cutoff:
            continue

        source_input_evidence = _source_input_term_evidence(coordination)
        if not source_input_evidence.terms:
            continue

        for entry in entries:
            if not _is_revalidation_candidate(entry, merged_at):
                continue

            match = _score_revalidation_match(entry, source_input_evidence, term_stats)
            if match is None:
                continue

            advisories.append(
                CurationAdvisory(
                    entry_id=entry.frontmatter.id,
                    entry_title=entry.frontmatter.title,
                    entry_type=entry.frontmatter.type,
                    suggested_action="revalidate",
                    reason=(
                        "completed ambara-labeled artifact changed a path or label "
                        "matching entry metadata"
                    ),
                    signal_id=coordination.signal_id,
                    signal_source=coordination.source,
                    artifact_ref=coordination.artifact_ref,
                    artifact_title=coordination.title,
                    actor=coordination.actor,
                    changed_paths=coordination.subject_refs,
                    matched_terms=match.matched_terms,
                    merged_at=merged_at,
                    confidence=match.confidence,
                    match_reasons=match.reasons,
                )
            )

    advisories.sort(key=lambda item: (-item.confidence, item.entry_id, item.source_input_id))
    return _dedupe_advisories(advisories)


def suggest_revalidation_from_signals(
    entries: Sequence[Entry],
    signals: Sequence[SignalLike],
    *,
    now: datetime,
    recency_days: int = 30,
) -> list[CurationAdvisory]:
    return suggest_revalidation_from_source_inputs(
        entries,
        signals,
        now=now,
        recency_days=recency_days,
    )


def _is_revalidation_candidate(entry: Entry, merged_at: datetime) -> bool:
    fm = entry.frontmatter
    if fm.type == EntryType.ACTIVE:
        return False
    return fm.status == EntryStatus.ACTIVE and fm.updated_at < merged_at


def _entry_terms(entry: Entry) -> set[str]:
    return _entry_term_evidence(entry).terms


def _source_input_terms(source_input: CoordinationSignal) -> set[str]:
    return _source_input_term_evidence(source_input).terms


@dataclass(frozen=True)
class _TermEvidence:
    term: str
    source: str
    weight: float


@dataclass(frozen=True)
class _EvidenceSet:
    items: tuple[_TermEvidence, ...]

    @property
    def terms(self) -> set[str]:
        return {item.term for item in self.items}

    def sources_for(self, term: str) -> frozenset[str]:
        return frozenset(item.source for item in self.items if item.term == term)

    def weight_for(self, term: str) -> float:
        return max((item.weight for item in self.items if item.term == term), default=0.0)


@dataclass(frozen=True)
class _EntryTermStats:
    doc_count: int
    doc_freq: dict[str, int] = field(default_factory=dict)

    def idf(self, term: str) -> float:
        if self.doc_count <= 0:
            return 1.0
        df = self.doc_freq.get(term, 0)
        return math.log((self.doc_count + 1) / (df + 0.5)) + 1.0


@dataclass(frozen=True)
class _CurationMatch:
    matched_terms: tuple[str, ...]
    confidence: float
    reasons: tuple[str, ...]


def _entry_term_evidence(entry: Entry) -> _EvidenceSet:
    fm = entry.frontmatter
    evidence: list[_TermEvidence] = []
    evidence.extend(_weighted_terms(fm.projects, source="project"))
    evidence.extend(_weighted_terms(fm.tags, source="tag"))
    evidence.extend(_weighted_terms((fm.title,), source="title"))
    return _EvidenceSet(tuple(evidence))


def _source_input_term_evidence(source_input: CoordinationSignal) -> _EvidenceSet:
    evidence: list[_TermEvidence] = []
    evidence.extend(_weighted_terms(source_input.labels, source="label"))
    evidence.extend(_weighted_terms(source_input.subject_areas, source="subject_area"))
    evidence.extend(_weighted_terms(source_input.subject_refs, source="subject_ref"))
    return _EvidenceSet(tuple(evidence))


def _weighted_terms(values: Iterable[str], *, source: str) -> list[_TermEvidence]:
    source_weight = _ENTRY_TERM_WEIGHTS.get(source, _SOURCE_INPUT_TERM_WEIGHTS.get(source, 1.0))
    evidence: list[_TermEvidence] = []
    for value in values:
        for term in tokenize(value):
            if term in _LOW_VALUE_CURATION_TERMS:
                continue
            evidence.append(_TermEvidence(term=term, source=source, weight=source_weight))
    return evidence


def _build_entry_term_stats(entries: Sequence[Entry]) -> _EntryTermStats:
    doc_freq: dict[str, int] = {}
    doc_count = 0
    for entry in entries:
        if not _is_potential_revalidation_candidate(entry):
            continue
        doc_count += 1
        for term in _entry_term_evidence(entry).terms:
            doc_freq[term] = doc_freq.get(term, 0) + 1
    return _EntryTermStats(doc_count=doc_count, doc_freq=doc_freq)


def _is_potential_revalidation_candidate(entry: Entry) -> bool:
    fm = entry.frontmatter
    return fm.type != EntryType.ACTIVE and fm.status == EntryStatus.ACTIVE


def _score_revalidation_match(
    entry: Entry,
    source_input_evidence: _EvidenceSet,
    term_stats: _EntryTermStats,
) -> _CurationMatch | None:
    entry_evidence = _entry_term_evidence(entry)
    matched_terms = tuple(sorted(entry_evidence.terms & source_input_evidence.terms))
    if not matched_terms:
        return None

    raw_score = 0.0
    reasons: set[str] = set()
    for term in matched_terms:
        entry_weight = entry_evidence.weight_for(term)
        source_weight = source_input_evidence.weight_for(term)
        raw_score += entry_weight * source_weight * term_stats.idf(term)
        for entry_source in entry_evidence.sources_for(term):
            for input_source in source_input_evidence.sources_for(term):
                reasons.add(f"{entry_source}:{input_source}")

    confidence = round(min(1.0, raw_score / 3.0), 3)
    if confidence < _MIN_REVALIDATION_CONFIDENCE:
        return None
    if len(matched_terms) == 1 and confidence < _MIN_SINGLE_TERM_CONFIDENCE:
        return None

    return _CurationMatch(
        matched_terms=matched_terms,
        confidence=confidence,
        reasons=tuple(sorted(reasons)),
    )


def _dedupe_advisories(advisories: list[CurationAdvisory]) -> list[CurationAdvisory]:
    seen: set[tuple[str, str]] = set()
    deduped: list[CurationAdvisory] = []
    for advisory in advisories:
        key = (advisory.entry_id, advisory.source_input_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(advisory)
    return deduped
