"""Read-side payload formatting and retrieval helpers for the MCP server."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from jurati.core.context_compiler import (
    Constraint,
    EntryHandle,
    compile_context_packet,
    constraints_from_context_payload,
    derive_freshness,
    entry_handles_from_context_payload,
)
from jurati.core.graph import EntryGraph
from jurati.core.hygiene import HygieneItem, HygieneReport
from jurati.core.index import Index
from jurati.core.schema import Entry, EntryStatus, EntryType, Sensitivity
from jurati.core.scoring import InvertedIndex, rank_entries
from jurati.core.search import SearchResult
from jurati.core.validate import is_expired
from jurati.server_guidance import _write_request_examples
from jurati.server_snapshot import snapshot_status_payload
from jurati.server_state import ServerState, SyncHealth

_SUMMARY_MAX_CHARS = 200


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
        "context_default_mode": state.config.context_default_mode,
        "context_snapshot": snapshot_status_payload(state),
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


def _truncate_summary(text: str, max_chars: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    truncated = normalized[:max_chars].rsplit(" ", 1)[0].rstrip()
    if not truncated:
        truncated = normalized[:max_chars].rstrip()
    return f"{truncated}..."


def _read_hint(entry_id: str) -> str:
    return f"read(id='{entry_id}') for full body"


def _derive_summary(entry: Entry, max_chars: int = _SUMMARY_MAX_CHARS) -> tuple[str | None, bool]:
    if entry.frontmatter.summary:
        summary = _truncate_summary(entry.frontmatter.summary, max_chars)
        if summary:
            return summary, False

    if not entry.body:
        return None, True

    lines = entry.body.split("\n")
    paragraph_lines: list[str] = []
    in_code_fence = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if not stripped:
            if paragraph_lines:
                break
            continue
        if stripped.startswith("#"):
            continue
        paragraph_lines.append(stripped)

    if not paragraph_lines:
        return None, True

    text = _truncate_summary(" ".join(paragraph_lines), max_chars)
    return text, False


def _format_entry_manifest(
    entry: Entry, *, relevance: dict[str, Any] | None = None
) -> dict[str, Any]:
    fm = entry.frontmatter
    summary_text, summary_missing = _derive_summary(entry)
    payload: dict[str, Any] = {
        "id": fm.id,
        "title": fm.title,
        "type": str(fm.type),
        "status": str(fm.status),
        "projects": fm.projects,
        "tags": fm.tags,
        "updated_at": fm.updated_at.isoformat(),
        "read_hint": _read_hint(fm.id),
    }
    if summary_missing:
        payload["summary_missing"] = True
    else:
        payload["summary"] = summary_text
    if relevance is not None:
        payload["relevance"] = relevance
    return payload


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


_BLOCKING_EFFECTS = {"pause", "revise"}


def _compact_coordination(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "status": payload["status"],
        "summary": payload["summary"],
        "privacy_ref": "standard",
    }
    guidance = []
    for g in payload.get("guidance", []):
        evidence = g.get("evidence", [])
        item: dict[str, Any] = {
            "effect": g["effect"],
            "urgency": g["urgency"],
            "summary": g["summary"],
            "source": evidence[0]["repo"] if evidence else None,
        }
        if g["effect"] in _BLOCKING_EFFECTS:
            item["confidence"] = g["confidence"]
            item["evidence_count"] = len(evidence)
            item["evidence_urls"] = [ev["url"] for ev in evidence]
        guidance.append(item)
    compact["guidance"] = guidance
    return compact


def _compact_curation(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "status": payload["status"],
        "summary": payload["summary"],
        "total_advisories": payload["total_advisories"],
        "shown_advisories": payload["shown_advisories"],
        "omitted_advisories": payload.get("omitted_advisories", 0),
        "policy_ref": "lifecycle-standard",
    }
    compact["expired_active"] = [
        {
            "id": item["id"],
            "title": item["title"],
            "reason": item["reason"],
            "effect": "verify_before_relying",
            "planning_constraint": (
                "Do not rely on expired active context unless current repo state confirms it."
            ),
            "read_hint": _read_hint(item["id"]),
        }
        for item in payload.get("expired_active", [])
    ]
    compact["revalidation_due"] = [
        {
            "id": item["id"],
            "title": item["title"],
            "reason": item["reason"],
            "effect": "verify_before_relying",
            "planning_constraint": "Verify this entry before relying on it for current work.",
            "read_hint": _read_hint(item["id"]),
        }
        for item in payload.get("revalidation_due", [])
    ]
    compact["completed_artifact_revalidation"] = [
        {
            "entry_id": item["entry_id"],
            "entry_title": item["entry_title"],
            "suggested_action": item["suggested_action"],
            "reason": item["reason"],
            "effect": "verify_before_relying",
            "planning_constraint": "Revalidate this entry before relying on it.",
            "read_hint": _read_hint(item["entry_id"]),
        }
        for item in payload.get("completed_artifact_revalidation", [])
    ]
    return compact


def _build_context_payload(
    index: Index,
    *,
    now: datetime,
    repo: str | None = None,
    goal: str | None = None,
    mode: str = "manifest",
    days_recent: int = 7,
    max_recent: int = 10,
    coordination: dict[str, Any] | None = None,
    curation: dict[str, Any] | None = None,
    prebuilt_index: InvertedIndex | None = None,
) -> dict[str, Any]:
    recent_cutoff = now - timedelta(days=days_recent)
    use_manifest = mode == "manifest"

    def _fmt(entry: Entry, *, relevance: dict[str, Any] | None = None) -> dict[str, Any]:
        if use_manifest:
            return _format_entry_manifest(entry, relevance=relevance)
        return _format_entry(entry)

    def _fmt_ranked(result: Any) -> dict[str, Any]:
        rel = {"score": result.relevance, "reasons": result.match_reasons}
        if use_manifest:
            return _format_entry_manifest(result.entry, relevance=rel)
        return _format_entry(result.entry)

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
        active = [_fmt_ranked(r) for r in ranked_active]
        unranked_active = [
            e
            for e in active_entries
            if e.frontmatter.id not in {r.entry.frontmatter.id for r in ranked_active}
        ]
        active.extend(_fmt(e) for e in unranked_active)

        ranked_recent = rank_entries(
            recent_entries,
            goal,
            now=now,
            repo=repo,
            max_results=max_recent,
            prebuilt_index=prebuilt_index,
        )
        ranked_ids = {r.entry.frontmatter.id for r in ranked_recent}
        recent = [_fmt_ranked(r) for r in ranked_recent]

        if repo:
            for e in recent_entries:
                if e.frontmatter.id not in ranked_ids and repo in e.frontmatter.projects:
                    recent.append(_fmt(e))
    else:
        active = [_fmt(e) for e in active_entries]
        recent = [_fmt(e) for e in recent_entries]
        recent.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
        recent = recent[:15]

    restricted_count = sum(
        1 for e in index.entries.values() if e.frontmatter.sensitivity == Sensitivity.RESTRICTED
    )

    coordination_signals = 0
    signal_excerpts_omitted = 0
    if coordination is not None and coordination.get("status") == "ok":
        coordination_signals = len(coordination.get("guidance", []))
        if use_manifest:
            signal_excerpts_omitted = sum(
                len(g.get("evidence", [])) for g in coordination.get("guidance", [])
            )

    curation_advisories = 0
    if curation is not None and curation.get("status") == "ok":
        curation_advisories = curation.get("total_advisories", 0)

    bodies_omitted = len(active) + len(recent) if use_manifest else 0

    if use_manifest:
        if coordination is not None:
            coordination = _compact_coordination(coordination)
        if curation is not None:
            curation = _compact_curation(curation)

    payload: dict[str, Any] = {
        "context_schema": "manifest-v1" if use_manifest else "full-v1",
        "mode": mode,
        "active": active,
        "recent": recent,
    }
    if coordination is not None:
        payload["coordination"] = coordination
    if curation is not None:
        payload["curation"] = curation
    payload["coverage"] = {
        "active_returned": len(active),
        "recent_returned": len(recent),
        "coordination_signals_returned": coordination_signals,
        "curation_advisories_returned": curation_advisories,
        "entry_bodies_omitted": bodies_omitted,
        "signal_excerpts_omitted": signal_excerpts_omitted,
        "hidden_restricted_entries": restricted_count,
    }
    return payload


def _build_compiler_payload(
    index: Index,
    *,
    now: datetime,
    sync_health: SyncHealth,
    freshness_warning_seconds: int,
    stale_after_seconds: int,
    repo: str | None = None,
    goal: str | None = None,
    days_recent: int = 7,
    max_recent: int = 10,
    coordination: dict[str, Any] | None = None,
    curation: dict[str, Any] | None = None,
    prebuilt_index: InvertedIndex | None = None,
    coverage_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = _build_context_payload(
        index,
        now=now,
        repo=repo,
        goal=goal,
        mode="manifest",
        days_recent=days_recent,
        max_recent=max_recent,
        coordination=coordination,
        curation=curation,
        prebuilt_index=prebuilt_index,
    )
    constraints = constraints_from_context_payload(manifest)
    entries = entry_handles_from_context_payload(manifest)
    freshness = derive_freshness(
        now=now,
        last_success=sync_health.last_success,
        warning_threshold_seconds=freshness_warning_seconds,
        stale_threshold_seconds=stale_after_seconds,
        last_failure=sync_health.last_failure,
        last_error=sync_health.last_error,
        consecutive_failures=sync_health.consecutive_failures,
    )
    return compile_context_packet(
        summary=_compiler_summary(constraints, entries),
        freshness=freshness,
        constraints=constraints,
        relevant_entries=entries,
        coverage=_compiler_coverage(manifest, coverage_overrides=coverage_overrides),
    )


def _build_unavailable_compiler_payload(
    *,
    now: datetime,
    reason: str,
    freshness_warning_seconds: int,
    stale_after_seconds: int,
    coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    freshness = derive_freshness(
        now=now,
        last_success=None,
        warning_threshold_seconds=freshness_warning_seconds,
        stale_threshold_seconds=stale_after_seconds,
        last_failure=now,
        last_error=reason,
        consecutive_failures=1,
    )
    return compile_context_packet(
        summary=reason,
        freshness=freshness,
        constraints=(),
        relevant_entries=(),
        coverage=coverage or {},
    )


def _compiler_coverage(
    manifest: dict[str, Any],
    *,
    coverage_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    coverage = manifest.get("coverage", {})
    if not isinstance(coverage, dict):
        return {}
    active_returned = int(coverage.get("active_returned", 0))
    recent_returned = int(coverage.get("recent_returned", 0))
    if coverage_overrides is not None:
        coverage = {**coverage, **coverage_overrides}
    return {
        **coverage,
        "entries_returned": active_returned + recent_returned,
        "bodies_omitted": coverage.get("entry_bodies_omitted", 0),
        "signals_returned": coverage.get("coordination_signals_returned", 0),
    }


def _compiler_summary(constraints: tuple[Constraint, ...], entries: tuple[EntryHandle, ...]) -> str:
    if constraints:
        count = len(constraints)
        noun = "constraint" if count == 1 else "constraints"
        return f"{count} planning {noun} found across {len(entries)} relevant entries."
    if entries:
        return f"No planning constraints found across {len(entries)} relevant entries."
    return "No relevant team context found in the current snapshot."


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
    body_mode: str = "none",
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
    results: list[dict[str, Any]] = []
    for r in ranked:
        item: dict[str, Any] = {
            "id": r.entry.frontmatter.id,
            "title": r.entry.frontmatter.title,
            "type": str(r.entry.frontmatter.type),
            "relevance": r.relevance,
            "reasons": r.match_reasons,
        }
        if body_mode == "full":
            item["snippet"] = r.entry.body[:200] if r.entry.body else ""
        results.append(item)
    return results


def _parse_tag_filter(tags: str | None) -> set[str]:
    if not tags:
        return set()
    return {tag.strip().lower() for tag in tags.split(",") if tag.strip()}


def _format_result(result: SearchResult, *, body_mode: str = "none") -> dict[str, Any]:
    if body_mode == "full":
        out = _format_entry(result.entry)
    else:
        relevance = {"score": result.relevance, "reasons": result.match_reasons}
        out = _format_entry_manifest(result.entry, relevance=relevance)
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
