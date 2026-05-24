"""Read-side payload formatting and retrieval helpers for the MCP server."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from jurati.core.graph import EntryGraph
from jurati.core.hygiene import HygieneItem, HygieneReport
from jurati.core.index import Index
from jurati.core.schema import Entry, EntryStatus, EntryType, Sensitivity
from jurati.core.scoring import InvertedIndex, rank_entries
from jurati.core.search import SearchResult
from jurati.core.validate import is_expired
from jurati.server_guidance import _write_request_examples
from jurati.server_state import ServerState, SyncHealth


def _health_dict(health: SyncHealth) -> dict[str, Any]:
    return {
        "last_success": health.last_success.isoformat() if health.last_success else None,
        "last_failure": health.last_failure.isoformat() if health.last_failure else None,
        "last_error": health.last_error,
        "consecutive_failures": health.consecutive_failures,
    }


def _entry_counts(index: Index) -> dict[str, int]:
    counts = {str(entry_type): 0 for entry_type in EntryType}
    for entry in index.entries.values():
        counts[str(entry.frontmatter.type)] += 1
    return counts


def _parse_enum(
    raw: str | None, enum_cls: type[StrEnum], label: str
) -> tuple[Any, dict[str, Any] | None]:
    if raw is None:
        return None, None
    try:
        return enum_cls(raw), None
    except ValueError:
        valid = ", ".join(str(v) for v in enum_cls)
        return None, {"error": f"Invalid {label}: {raw!r}. Valid values: {valid}"}


def _state_status_payload(state: ServerState) -> dict[str, Any]:
    return {
        "status": "ok",
        "what_this_server_is_doing": [
            "reading markdown entries from the configured knowledge repo cache",
            "answering query/read/list/validate calls from the in-memory index",
            "writing only when record/propose/expire is explicitly called",
        ],
        "knowledge_remote": state.config.remote_url,
        "local_cache": state.repo_path,
        "main_branch": state.config.main_branch,
        "active_ref_prefix": state.config.active_ref_prefix,
        "client_slug": state.config.client_slug,
        "entries_indexed": len(state.index.entries),
        "entries_by_type": _entry_counts(state.index),
        "last_sync": state.last_sync.isoformat(),
        "sync_health": _health_dict(state.sync_health),
        "write_paths": {
            "active": "record(type='active') writes to a non-main active ref",
            "project": "record(type='project') creates a lightweight pull request",
            "workflow_decision_principle": "propose(...) creates a reviewed pull request",
        },
        "privacy_boundary": [
            "no query logging",
            "no read receipts",
            "no participation tracking",
            "no inferred presence from editor, terminal, or agent activity",
        ],
    }


def _format_entry(entry: Entry, *, graph: EntryGraph | None = None) -> dict[str, Any]:
    fm = entry.frontmatter
    payload: dict[str, Any] = {
        "id": fm.id,
        "title": fm.title,
        "type": str(fm.type),
        "level": str(fm.level),
        "status": str(fm.status),
        "created_at": fm.created_at.isoformat(),
        "updated_at": fm.updated_at.isoformat(),
        "expires_at": fm.expires_at.isoformat() if fm.expires_at else None,
        "projects": fm.projects,
        "tags": fm.tags,
        "path": entry.path,
        "body": entry.body,
    }
    if graph is not None:
        payload["links"] = _links_for_entry(entry, graph)
    return payload


def _links_for_entry(entry: Entry, graph: EntryGraph) -> dict[str, Any]:
    links = graph.links_for(entry.frontmatter.id)
    visible_backlinks = [
        entry_id for entry_id in links["backlinks"] if entry_id not in graph.restricted_entry_ids
    ]
    return {**links, "backlinks": visible_backlinks}


def _build_context_payload(
    index: Index,
    *,
    now: datetime,
    repo: str | None = None,
    goal: str | None = None,
    days_recent: int = 7,
    max_recent: int = 10,
    coordination: dict[str, Any] | None = None,
    prebuilt_index: InvertedIndex | None = None,
) -> dict[str, Any]:
    recent_cutoff = now - timedelta(days=days_recent)

    active_entries = [
        e
        for e in index.entries.values()
        if e.frontmatter.type == EntryType.ACTIVE
        and not is_expired(e, now)
        and e.frontmatter.sensitivity != Sensitivity.RESTRICTED
    ]

    recent_entries = [
        e
        for e in index.entries.values()
        if e.frontmatter.type != EntryType.ACTIVE
        and e.frontmatter.updated_at >= recent_cutoff
        and e.frontmatter.status in (EntryStatus.ACTIVE, EntryStatus.PROPOSED)
        and e.frontmatter.sensitivity != Sensitivity.RESTRICTED
    ]

    if goal:
        ranked_active = rank_entries(
            active_entries,
            goal,
            now=now,
            repo=repo,
            max_results=len(active_entries),
            prebuilt_index=prebuilt_index,
        )
        active = [_format_entry(r.entry) for r in ranked_active]
        unranked_active = [
            e
            for e in active_entries
            if e.frontmatter.id not in {r.entry.frontmatter.id for r in ranked_active}
        ]
        active.extend(_format_entry(e) for e in unranked_active)

        ranked_recent = rank_entries(
            recent_entries,
            goal,
            now=now,
            repo=repo,
            max_results=max_recent,
            prebuilt_index=prebuilt_index,
        )
        ranked_ids = {r.entry.frontmatter.id for r in ranked_recent}
        recent = [_format_entry(r.entry) for r in ranked_recent]

        if repo:
            for e in recent_entries:
                if e.frontmatter.id not in ranked_ids and repo in e.frontmatter.projects:
                    recent.append(_format_entry(e))
    else:
        active = [_format_entry(e) for e in active_entries]
        recent = [_format_entry(e) for e in recent_entries]
        recent.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
        recent = recent[:15]

    payload: dict[str, Any] = {"active": active, "recent": recent}
    if coordination is not None:
        payload["coordination"] = coordination
    return payload


def _build_search_results(
    index: Index,
    query: str,
    *,
    now: datetime,
    repo: str | None = None,
    max_results: int = 10,
    entry_type: EntryType | None = None,
    project: str | None = None,
    tags: str | None = None,
    include_expired: bool = False,
    prebuilt_index: InvertedIndex | None = None,
) -> list[dict[str, Any]]:
    entries = index.list_entries(
        now=now,
        entry_type=entry_type,
        project=project,
        include_expired=include_expired,
    )
    tag_filter = _parse_tag_filter(tags)
    if tag_filter:
        entries = [
            e
            for e in entries
            if tag_filter.intersection({tag.lower() for tag in e.frontmatter.tags})
        ]
    ranked = rank_entries(
        entries, query, now=now, repo=repo, max_results=max_results, prebuilt_index=prebuilt_index
    )
    return [
        {
            "id": r.entry.frontmatter.id,
            "title": r.entry.frontmatter.title,
            "type": str(r.entry.frontmatter.type),
            "relevance": r.relevance,
            "reasons": r.match_reasons,
            "snippet": r.entry.body[:200] if r.entry.body else "",
        }
        for r in ranked
    ]


def _parse_tag_filter(tags: str | None) -> set[str]:
    if not tags:
        return set()
    return {tag.strip().lower() for tag in tags.split(",") if tag.strip()}


def _format_result(result: SearchResult) -> dict[str, Any]:
    out = _format_entry(result.entry)
    out["match"] = {
        "relevance": result.relevance,
        "reasons": result.match_reasons,
        "source": {
            "path": result.entry.path,
            "type": str(result.entry.frontmatter.type),
            "status": str(result.entry.frontmatter.status),
            "projects": result.entry.frontmatter.projects,
            "tags": result.entry.frontmatter.tags,
        },
    }
    return out


def _explain_payload() -> dict[str, Any]:
    return {
        "summary": "Jurati is shared agent context backed by a git knowledge repo.",
        "reads": [
            "project state, workflows, decisions, and principles from markdown entries",
            "a local cache after sync, not the live remote on every query",
        ],
        "writes": [
            "record(active): short-lived active context on a non-main active ref",
            "record(project): lightweight pull request",
            "propose(workflow/decision/principle): reviewed pull request",
            "expire(id): active ref deletion or expiry pull request",
        ],
        "does_not": [
            "persist query text",
            "track who read what",
            "infer presence from editor, terminal, or agent activity",
            "bypass normal git provenance or review",
        ],
        "daily_loop": [
            "query before work starts",
            "record explicit active context during work",
            "propose durable decisions or workflows after work",
        ],
        "request_mapping": _write_request_examples(),
        "capture_triggers": {
            "handoff": {
                "phrases": [
                    "save this handoff",
                    "pass this to",
                    "leave this for tomorrow",
                    "hand off",
                ],
                "tool": "record(type='active')",
            },
            "project_update": {
                "phrases": [
                    "note this down",
                    "save this status",
                    "capture this update",
                    "the progress is",
                ],
                "tool": "record(type='project')",
            },
            "decision": {
                "phrases": [
                    "we decided",
                    "the decision is",
                    "going forward",
                    "record this decision",
                ],
                "tool": "propose(type='decision')",
            },
            "workflow": {
                "phrases": [
                    "this is how we do X",
                    "document this process",
                ],
                "tool": "propose(type='workflow')",
            },
        },
        "startup_anti_patterns": [
            "Do not use git log, grep, or file reads instead of query()",
            "Do not skip startup for quick questions",
            "Do not proceed with local-only context if sync/context fails",
            "If you realize you skipped startup, run it before continuing",
        ],
        "storage_model": [
            "Markdown with YAML frontmatter is the human-reviewable source format",
            "runtime indexes are derived from the knowledge repo cache",
            (
                "future query stores such as SQLite, FTS, vector, or graph "
                "projections should remain rebuildable derived indexes"
            ),
        ],
        "retrieval": {
            "query": (
                "Exact substring matching on title, id, tags, body. Best for known terms or IDs."
            ),
            "search": (
                "BM25 keyword ranking with recency and type-weight signals. "
                "Best for exploratory lookups and multi-word topics."
            ),
            "recommendation": (
                "Start with search() for discovery. "
                "Use query() when you know the exact term, ID, or tag."
            ),
        },
    }


def _format_hygiene_item(item: HygieneItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "type": str(item.type),
        "status": str(item.status),
        "path": item.path,
        "updated_at": item.updated_at.isoformat(),
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "review_after": item.review_after.isoformat() if item.review_after else None,
        "reason": item.reason,
        "next_step": item.next_step,
    }


def _format_hygiene_report(report: HygieneReport) -> dict[str, Any]:
    return {
        "summary": {
            "expired_active": len(report.expired_active),
            "stale_proposed": len(report.stale_proposed),
            "revalidation": len(report.revalidation),
            "supersession": len(report.supersession),
            "stale_after_days": report.stale_after_days,
        },
        "expired_active": [_format_hygiene_item(item) for item in report.expired_active],
        "stale_proposed": [_format_hygiene_item(item) for item in report.stale_proposed],
        "revalidation": [_format_hygiene_item(item) for item in report.revalidation],
        "supersession": [
            {
                "id": item.id,
                "title": item.title,
                "path": item.path,
                "supersedes": item.supersedes,
                "superseded_by": item.superseded_by,
                "next_step": item.next_step,
            }
            for item in report.supersession
        ],
        "privacy_boundary": report.privacy_boundary,
    }
