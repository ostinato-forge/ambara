"""Integration contract — stable interface for external systems.

Pure functions consuming Index. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from jurati.core.index import Index
from jurati.core.schema import Entry, EntryType, Sensitivity, Visibility
from jurati.core.validate import is_expired


class AccessMode(StrEnum):
    CONTEXT = "context"
    EXTERNAL_CONTEXT = "external_context"
    GATE_EVIDENCE = "gate_evidence"
    DURABLE_SOURCE = "durable_source"


@dataclass(frozen=True)
class KnowledgeQuery:
    topic: str | None = None
    entry_type: str | None = None
    project: str | None = None
    access_mode: AccessMode = AccessMode.CONTEXT
    system_id: str | None = None
    max_results: int = 10


@dataclass(frozen=True)
class KnowledgeResult:
    entries: list[dict[str, Any]]
    coordination: list[dict[str, Any]] = field(default_factory=list)
    provenance: str = ""


def _passes_access_filter(entry: Entry, mode: AccessMode) -> bool:
    if entry.frontmatter.sensitivity == Sensitivity.RESTRICTED:
        return False

    match mode:
        case AccessMode.CONTEXT:
            return True
        case AccessMode.EXTERNAL_CONTEXT:
            return entry.frontmatter.visibility == Visibility.EXTERNAL
        case AccessMode.GATE_EVIDENCE:
            return entry.frontmatter.visibility == Visibility.EXTERNAL and entry.on_source_branch
        case AccessMode.DURABLE_SOURCE:
            return entry.on_source_branch
        case _:
            return False


def query_knowledge(
    index: Index,
    q: KnowledgeQuery,
    *,
    now: datetime,
) -> KnowledgeResult:
    if q.access_mode != AccessMode.CONTEXT and q.system_id is None:
        raise ValueError("system_id is required for non-CONTEXT access modes")

    entries = []
    for entry in index.entries.values():
        if is_expired(entry, now):
            continue
        if not _passes_access_filter(entry, q.access_mode):
            continue
        if q.project and q.project not in entry.frontmatter.projects:
            continue
        if q.entry_type:
            try:
                et = EntryType(q.entry_type)
                if entry.frontmatter.type != et:
                    continue
            except ValueError:
                continue
        entries.append(
            {
                "id": entry.frontmatter.id,
                "title": entry.frontmatter.title,
                "type": str(entry.frontmatter.type),
                "level": str(entry.frontmatter.level),
                "status": str(entry.frontmatter.status),
            }
        )

    return KnowledgeResult(entries=entries[: q.max_results])


def check_constraints(
    index: Index,
    project: str,
    *,
    now: datetime,
    constraint_types: tuple[EntryType, ...] = (EntryType.DECISION, EntryType.PRINCIPLE),
) -> list[Entry]:
    results = []
    for entry in index.entries.values():
        if is_expired(entry, now):
            continue
        if entry.frontmatter.type not in constraint_types:
            continue
        if project not in entry.frontmatter.projects:
            continue
        results.append(entry)
    return results
