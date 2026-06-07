# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Local scope filtering for muted Ambara context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ambara.core.index import Index
from ambara.core.pr_signals import SignalLike, SourceInputLike, coordination_signal_from_any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ambara.core.schema import Entry

_SCOPE_FILTER_NOW = datetime(1970, 1, 1, tzinfo=UTC)


def _normalize(value: str) -> str:
    return value.strip().lower()


def _normalized_tuple(values: Iterable[object] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(
        sorted({_normalize(value) for value in values if isinstance(value, str) and value.strip()})
    )


def _normalized_raw_values(raw: dict[str, Any], *keys: str) -> tuple[str, ...]:
    values: list[object] = []
    for key in keys:
        raw_value = raw.get(key)
        if isinstance(raw_value, str):
            values.append(raw_value)
        elif isinstance(raw_value, (list, tuple, set)):
            values.extend(raw_value)
    return _normalized_tuple(values)


@dataclass(frozen=True)
class ScopeMutePolicy:
    projects: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()
    signal_sources: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    @classmethod
    def from_raw(cls, raw: object) -> ScopeMutePolicy:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            projects=_normalized_raw_values(raw, "projects"),
            repos=_normalized_raw_values(raw, "repos"),
            signal_sources=_normalized_tuple(
                (
                    *_normalized_raw_values(raw, "signal_sources"),
                    *_normalized_raw_values(raw, "source_inputs"),
                )
            ),
            tags=_normalized_raw_values(raw, "tags"),
        )

    @property
    def source_inputs(self) -> tuple[str, ...]:
        return self.signal_sources

    def to_dict(self) -> dict[str, list[str]]:
        data: dict[str, list[str]] = {}
        if self.projects:
            data["projects"] = list(self.projects)
        if self.repos:
            data["repos"] = list(self.repos)
        if self.source_inputs:
            data["signal_sources"] = list(self.source_inputs)
        if self.tags:
            data["tags"] = list(self.tags)
        return data

    def is_empty(self) -> bool:
        return not (self.projects or self.repos or self.source_inputs or self.tags)

    def count(self) -> int:
        return len(self.projects) + len(self.repos) + len(self.source_inputs) + len(self.tags)

    def merge(self, other: ScopeMutePolicy) -> ScopeMutePolicy:
        return ScopeMutePolicy(
            projects=tuple(sorted(set(self.projects).union(other.projects))),
            repos=tuple(sorted(set(self.repos).union(other.repos))),
            signal_sources=tuple(sorted(set(self.source_inputs).union(other.source_inputs))),
            tags=tuple(sorted(set(self.tags).union(other.tags))),
        )

    def without(self, other: ScopeMutePolicy) -> ScopeMutePolicy:
        return ScopeMutePolicy(
            projects=tuple(sorted(set(self.projects).difference(other.projects))),
            repos=tuple(sorted(set(self.repos).difference(other.repos))),
            signal_sources=tuple(sorted(set(self.source_inputs).difference(other.source_inputs))),
            tags=tuple(sorted(set(self.tags).difference(other.tags))),
        )


def is_entry_muted(entry: Entry, policy: ScopeMutePolicy) -> bool:
    if policy.is_empty():
        return False
    fm = entry.frontmatter
    projects = {_normalize(value) for value in fm.projects}
    tags = {_normalize(value) for value in fm.tags}
    source = getattr(fm, "source", None)
    source_repo = _normalize(source.repo) if source and source.repo else None

    return bool(
        projects.intersection(policy.projects)
        or tags.intersection(policy.tags)
        or (source_repo is not None and source_repo in policy.repos)
    )


def is_source_input_muted(source_input: SourceInputLike, policy: ScopeMutePolicy) -> bool:
    if policy.is_empty():
        return False
    normalized_signal = coordination_signal_from_any(source_input, now=_SCOPE_FILTER_NOW)
    source = _normalize(normalized_signal.source)
    provider = _normalize(normalized_signal.provider)
    labels = {_normalize(label) for label in normalized_signal.labels}
    subject_areas = {_normalize(area) for area in normalized_signal.subject_areas}

    return bool(
        source in policy.repos
        or source in policy.source_inputs
        or provider in policy.source_inputs
        or labels.intersection(policy.tags)
        or subject_areas.intersection(policy.projects)
    )


def is_signal_muted(signal: SignalLike, policy: ScopeMutePolicy) -> bool:
    return is_source_input_muted(signal, policy)


def filter_index(index: Index, policy: ScopeMutePolicy) -> Index:
    if policy.is_empty():
        return index
    return Index(
        {
            entry_id: entry
            for entry_id, entry in index.entries.items()
            if not is_entry_muted(entry, policy)
        }
    )


def filter_entries(entries: Sequence[Entry], policy: ScopeMutePolicy) -> tuple[Entry, ...]:
    if policy.is_empty():
        return tuple(entries)
    return tuple(entry for entry in entries if not is_entry_muted(entry, policy))


def filter_source_inputs[SourceInputT: SourceInputLike](
    source_inputs: Sequence[SourceInputT], policy: ScopeMutePolicy
) -> tuple[SourceInputT, ...]:
    if policy.is_empty():
        return tuple(source_inputs)
    return tuple(
        source_input
        for source_input in source_inputs
        if not is_source_input_muted(source_input, policy)
    )


def filter_signals[SignalT: SignalLike](
    signals: Sequence[SignalT], policy: ScopeMutePolicy
) -> tuple[SignalT, ...]:
    return filter_source_inputs(signals, policy)


def scope_policy_summary(policy: ScopeMutePolicy) -> dict[str, Any]:
    return {
        "total": policy.count(),
        "projects": list(policy.projects),
        "repos": list(policy.repos),
        "source_inputs": list(policy.source_inputs),
        "signal_sources": list(policy.source_inputs),
        "tags": list(policy.tags),
    }
