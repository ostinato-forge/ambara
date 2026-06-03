"""Local scope filtering for muted Ambara context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ambara.core.index import Index

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ambara.core.pr_signals import CoordinationSignal, PRSignal
    from ambara.core.schema import Entry


def _normalize(value: str) -> str:
    return value.strip().lower()


def _normalized_tuple(values: Iterable[object] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(
        sorted({_normalize(value) for value in values if isinstance(value, str) and value.strip()})
    )


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
            projects=_normalized_tuple(raw.get("projects") if isinstance(raw, dict) else None),
            repos=_normalized_tuple(raw.get("repos") if isinstance(raw, dict) else None),
            signal_sources=_normalized_tuple(
                raw.get("signal_sources") if isinstance(raw, dict) else None
            ),
            tags=_normalized_tuple(raw.get("tags") if isinstance(raw, dict) else None),
        )

    def to_dict(self) -> dict[str, list[str]]:
        data: dict[str, list[str]] = {}
        if self.projects:
            data["projects"] = list(self.projects)
        if self.repos:
            data["repos"] = list(self.repos)
        if self.signal_sources:
            data["signal_sources"] = list(self.signal_sources)
        if self.tags:
            data["tags"] = list(self.tags)
        return data

    def is_empty(self) -> bool:
        return not (self.projects or self.repos or self.signal_sources or self.tags)

    def count(self) -> int:
        return len(self.projects) + len(self.repos) + len(self.signal_sources) + len(self.tags)

    def merge(self, other: ScopeMutePolicy) -> ScopeMutePolicy:
        return ScopeMutePolicy(
            projects=tuple(sorted(set(self.projects).union(other.projects))),
            repos=tuple(sorted(set(self.repos).union(other.repos))),
            signal_sources=tuple(sorted(set(self.signal_sources).union(other.signal_sources))),
            tags=tuple(sorted(set(self.tags).union(other.tags))),
        )

    def without(self, other: ScopeMutePolicy) -> ScopeMutePolicy:
        return ScopeMutePolicy(
            projects=tuple(sorted(set(self.projects).difference(other.projects))),
            repos=tuple(sorted(set(self.repos).difference(other.repos))),
            signal_sources=tuple(sorted(set(self.signal_sources).difference(other.signal_sources))),
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


def is_signal_muted(signal: PRSignal | CoordinationSignal, policy: ScopeMutePolicy) -> bool:
    if policy.is_empty():
        return False
    source = _normalize(getattr(signal, "source", getattr(signal, "repo", "")))
    provider = _normalize(getattr(signal, "provider", ""))
    labels = {_normalize(label) for label in getattr(signal, "labels", ())}
    subject_areas = {
        _normalize(area)
        for area in getattr(signal, "subject_areas", getattr(signal, "target_areas", ()))
    }

    return bool(
        source in policy.repos
        or source in policy.signal_sources
        or provider in policy.signal_sources
        or labels.intersection(policy.tags)
        or subject_areas.intersection(policy.projects)
    )


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


def filter_signals(
    signals: Sequence[PRSignal | CoordinationSignal], policy: ScopeMutePolicy
) -> tuple[PRSignal | CoordinationSignal, ...]:
    if policy.is_empty():
        return tuple(signals)
    return tuple(signal for signal in signals if not is_signal_muted(signal, policy))


def scope_policy_summary(policy: ScopeMutePolicy) -> dict[str, Any]:
    return {
        "total": policy.count(),
        "projects": list(policy.projects),
        "repos": list(policy.repos),
        "signal_sources": list(policy.signal_sources),
        "tags": list(policy.tags),
    }
