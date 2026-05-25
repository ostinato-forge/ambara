"""Contradiction detection, staleness scanning, and curation advisories."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from .pr_signals import CoordinationSignal, PRSignal
from .schema import Entry, EntryStatus, EntryType
from .scoring import tokenize

_COMPLETED_SIGNAL_STATES = frozenset({"merged", "resolved"})
_LOW_VALUE_SIGNAL_TERMS = frozenset({"jurati", "src", "test", "tests", "api"})


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


def suggest_revalidation_from_signals(
    entries: Sequence[Entry],
    signals: Sequence[PRSignal | CoordinationSignal],
    *,
    now: datetime,
    recency_days: int = 30,
) -> list[CurationAdvisory]:
    """Suggest durable entries to revalidate after explicit merged coordination signals."""

    cutoff = now - timedelta(days=recency_days)
    advisories: list[CurationAdvisory] = []

    for raw_signal in signals:
        signal = (
            CoordinationSignal.from_pr_signal(raw_signal)
            if isinstance(raw_signal, PRSignal)
            else raw_signal
        )
        merged_at = signal.resolved_at or signal.updated_at
        if signal.state not in _COMPLETED_SIGNAL_STATES or merged_at < cutoff:
            continue

        signal_terms = _signal_terms(signal)
        if not signal_terms:
            continue

        for entry in entries:
            if not _is_revalidation_candidate(entry, merged_at):
                continue

            matched = tuple(sorted(_entry_terms(entry) & signal_terms))
            if not matched:
                continue

            advisories.append(
                CurationAdvisory(
                    entry_id=entry.frontmatter.id,
                    entry_title=entry.frontmatter.title,
                    entry_type=entry.frontmatter.type,
                    suggested_action="revalidate",
                    reason=(
                        "completed jurati-labeled artifact changed a path or label "
                        "matching entry metadata"
                    ),
                    signal_id=signal.signal_id,
                    signal_source=signal.source,
                    artifact_ref=signal.artifact_ref,
                    artifact_title=signal.title,
                    actor=signal.actor,
                    changed_paths=signal.subject_refs,
                    matched_terms=matched,
                    merged_at=merged_at,
                )
            )

    advisories.sort(key=lambda item: (item.entry_id, item.signal_id))
    return _dedupe_advisories(advisories)


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


def _signal_terms(signal: CoordinationSignal) -> set[str]:
    terms: set[str] = set()
    for value in (
        *signal.labels,
        *signal.subject_areas,
        *signal.subject_refs,
    ):
        terms.update(tokenize(value))
    return terms - _LOW_VALUE_SIGNAL_TERMS


def _dedupe_advisories(advisories: list[CurationAdvisory]) -> list[CurationAdvisory]:
    seen: set[tuple[str, str]] = set()
    deduped: list[CurationAdvisory] = []
    for advisory in advisories:
        key = (advisory.entry_id, advisory.signal_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(advisory)
    return deduped
