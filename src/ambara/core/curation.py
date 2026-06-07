# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Contradiction detection, staleness scanning, and curation advisories."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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

    for source_input in source_inputs:
        coordination = coordination_signal_from_any(source_input, now=now)
        merged_at = coordination.resolved_at or coordination.updated_at
        if coordination.state not in _COMPLETED_SOURCE_INPUT_STATES or merged_at < cutoff:
            continue

        source_input_terms = _source_input_terms(coordination)
        if not source_input_terms:
            continue

        for entry in entries:
            if not _is_revalidation_candidate(entry, merged_at):
                continue

            matched = tuple(sorted(_entry_terms(entry) & source_input_terms))
            if not matched:
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
                    matched_terms=matched,
                    merged_at=merged_at,
                )
            )

    advisories.sort(key=lambda item: (item.entry_id, item.source_input_id))
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
    fm = entry.frontmatter
    terms: set[str] = set()
    for value in (*fm.projects, *fm.tags):
        terms.update(tokenize(value))
    return terms


def _source_input_terms(source_input: CoordinationSignal) -> set[str]:
    terms: set[str] = set()
    for value in (
        *source_input.labels,
        *source_input.subject_areas,
        *source_input.subject_refs,
    ):
        terms.update(tokenize(value))
    return terms - _LOW_VALUE_SOURCE_INPUT_TERMS


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
