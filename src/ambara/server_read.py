# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Read-side payload formatting and retrieval helpers for the MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from ambara.core.context_accounting import (
    AccountingInputs,
    BudgetMode,
    compact_value_receipt,
    detailed_cost_accounting,
    estimate_text_tokens,
    estimate_tokens,
)
from ambara.core.context_compiler import (
    Constraint,
    EntryHandle,
    compile_context_packet,
    compile_startup_packet,
    constraints_from_context_payload,
    derive_freshness,
    entry_handles_from_context_payload,
)
from ambara.core.graph import EntryGraph, build_entry_graph
from ambara.core.hygiene import HygieneItem, HygieneReport
from ambara.core.index import Index
from ambara.core.schema import Entry, EntryStatus, EntryType, Sensitivity
from ambara.core.scope_policy import scope_policy_summary
from ambara.core.scoring import InvertedIndex, rank_entries
from ambara.core.search import SearchResult
from ambara.core.validate import is_expired
from ambara.server_curation import _signals_configured
from ambara.server_guidance import _write_request_examples
from ambara.server_snapshot import (
    compiler_health_for_context,
    render_coordination_from_snapshot,
    render_curation_from_snapshot,
    snapshot_coverage,
    snapshot_status_payload,
)
from ambara.server_state import ServerState, SyncHealth

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


def _entry_graph_for_state(state: ServerState) -> EntryGraph:
    if (
        state.cache._entry_graph is not None
        and state.cache._entry_graph_generation == state.cache.generation
    ):
        return state.cache._entry_graph
    graph = build_entry_graph(state.index)
    state.cache._entry_graph = graph
    state.cache._entry_graph_generation = state.cache.generation
    return graph


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
    if state.config.disabled:
        return {
            "status": "disabled",
            "what_happened": "Ambara is disabled for this project.",
            "agent_instruction": (
                "Proceed from local project context; do not treat this as a team-context failure."
            ),
            "knowledge_remote": state.config.remote_url or None,
            "local_cache": state.repo_path or None,
            "sync_health": _health_dict(state.sync_health),
            "context_default_mode": state.config.context_default_mode,
            "muted_scopes": scope_policy_summary(state.config.muted_scopes),
            "privacy_boundary": [
                "disabled state is local configuration",
                "no query logging",
                "no read receipts",
                "no participation tracking",
            ],
        }

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
        "muted_scopes": scope_policy_summary(state.config.muted_scopes),
        "context_snapshot": snapshot_status_payload(state),
        "write_paths": {
            "active": "record(type='active') writes to a non-main active ref",
            "project": (
                "record(type='project') creates a lightweight review branch and may "
                "open a review request when the path supports it"
            ),
            "workflow_decision_principle": (
                "propose(...) creates a reviewed branch and may open a review request "
                "when the path supports it"
            ),
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


def build_context_payload(
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
    budget_mode: str = BudgetMode.BALANCED.value,
    recently_seen_ids: set[str] | None = None,
    feedback_suppressed_ids: set[str] | None = None,
    pinned_ids: set[str] | None = None,
) -> dict[str, Any]:
    max_recent = _budgeted_max_recent(max_recent, budget_mode)
    manifest = build_context_payload(
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
    all_entries = list(entry_handles_from_context_payload(manifest))
    selection = _select_entry_handles(
        all_entries,
        max_entries=len(all_entries),
        budget_mode=budget_mode,
        recently_seen_ids=recently_seen_ids,
        feedback_suppressed_ids=feedback_suppressed_ids,
        pinned_ids=pinned_ids,
    )
    entries = selection.displayed
    freshness = derive_freshness(
        now=now,
        last_success=sync_health.last_success,
        warning_threshold_seconds=freshness_warning_seconds,
        stale_threshold_seconds=stale_after_seconds,
        last_failure=sync_health.last_failure,
        last_error=sync_health.last_error,
        consecutive_failures=sync_health.consecutive_failures,
    )
    coverage = {
        **_compiler_coverage(manifest, coverage_overrides=coverage_overrides),
        "already_seen_suppressed": selection.already_seen_suppressed,
        "user_muted_suppressed": selection.user_muted_suppressed,
        "duplicates_suppressed": selection.duplicates_suppressed,
    }
    summary = _compiler_summary(constraints, entries)
    base_packet = compile_context_packet(
        summary=summary,
        freshness=freshness,
        constraints=constraints,
        relevant_entries=entries,
        coverage=coverage,
    )
    manifest_tokens = estimate_tokens(manifest)
    full_tokens = _full_context_tokens_est(index, manifest)
    first_cost = _context_cost_accounting(
        response_payload=base_packet,
        manifest_tokens=manifest_tokens,
        full_tokens=full_tokens,
        coverage=coverage,
        selected_entry_count=len(entries),
        budget_mode=budget_mode,
    )
    cost_accounting = _context_cost_accounting(
        response_payload=base_packet,
        receipt_payload=first_cost,
        manifest_tokens=manifest_tokens,
        full_tokens=full_tokens,
        coverage=coverage,
        selected_entry_count=len(entries),
        budget_mode=budget_mode,
    )
    return compile_context_packet(
        summary=summary,
        freshness=freshness,
        constraints=constraints,
        relevant_entries=entries,
        coverage=coverage,
        cost_accounting=cost_accounting,
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


def _manifest_entry_ids(manifest: dict[str, Any]) -> tuple[str, ...]:
    ids: list[str] = []
    for key in ("active", "recent"):
        for item in manifest.get(key, ()):
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                ids.append(item["id"])
    return tuple(ids)


def _deferred_body_tokens(index: Index, entry_ids: tuple[str, ...]) -> int:
    total = 0
    for entry_id in entry_ids:
        entry = index.get(entry_id)
        if entry is not None and entry.body:
            total += estimate_text_tokens(entry.body)
    return total


def _full_context_tokens_est(index: Index, manifest: dict[str, Any]) -> int:
    """Estimate a full-body manifest baseline without rendering body text."""
    return estimate_tokens(manifest) + _deferred_body_tokens(index, _manifest_entry_ids(manifest))


def _coverage_int(coverage: dict[str, Any], key: str) -> int:
    value = coverage.get(key, 0)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _context_cost_accounting(
    *,
    response_payload: dict[str, Any],
    manifest_tokens: int,
    full_tokens: int,
    coverage: dict[str, Any],
    selected_entry_count: int,
    receipt_payload: dict[str, Any] | None = None,
    budget_mode: str = BudgetMode.BALANCED.value,
) -> dict[str, Any]:
    entries_considered = _coverage_int(coverage, "entries_considered")
    entries_omitted = max(0, entries_considered - selected_entry_count)
    return detailed_cost_accounting(
        AccountingInputs(
            tool_name="context",
            context_schema="compiler-v1",
            budget_mode=budget_mode,
            response_payload=response_payload,
            receipt_payload=receipt_payload,
            eligible_candidate_count=entries_considered,
            selected_entry_count=selected_entry_count,
            entries_omitted_count=entries_omitted,
            restricted_hidden_count=_coverage_int(coverage, "hidden_restricted_entries"),
            duplicates_suppressed_count=_coverage_int(coverage, "duplicates_suppressed"),
            already_seen_suppressed_count=_coverage_int(coverage, "already_seen_suppressed"),
            user_muted_suppressed_count=(
                _coverage_int(coverage, "muted_entries_hidden")
                + _coverage_int(coverage, "user_muted_suppressed")
            ),
            notices_omitted_count=_coverage_int(coverage, "omitted_advisories"),
            signal_excerpts_omitted_count=_coverage_int(coverage, "signal_excerpts_omitted"),
            deferred_body_count=_coverage_int(coverage, "bodies_omitted"),
            full_context_tokens_est=full_tokens,
            manifest_tokens_est=manifest_tokens,
        )
    )


def _compiler_summary(constraints: tuple[Constraint, ...], entries: tuple[EntryHandle, ...]) -> str:
    if constraints:
        count = len(constraints)
        noun = "constraint" if count == 1 else "constraints"
        return f"{count} planning {noun} found across {len(entries)} relevant entries."
    if entries:
        return f"No planning constraints found across {len(entries)} relevant entries."
    return "No relevant project context found in the current snapshot."


_ENTRY_WHY_TYPE_LABELS = {
    "active": "Active work",
    "decision": "Decision",
    "workflow": "Required workflow",
    "project": "Project context",
    "principle": "Guiding principle",
}


@dataclass(frozen=True)
class EntrySelection:
    displayed: tuple[EntryHandle, ...]
    entries_omitted: int
    already_seen_suppressed: int
    user_muted_suppressed: int
    duplicates_suppressed: int = 0


def _entry_why(entry_type: str, match_reasons: list[str] | None) -> str:
    label = _ENTRY_WHY_TYPE_LABELS.get(entry_type, "Entry")
    if match_reasons and "project-match" in match_reasons:
        return f"{label} in this project."
    if match_reasons and "exact-match" in match_reasons:
        return f"{label} directly matching request."
    return f"{label} relevant to current work."


def _budgeted_max_entries(max_entries: int, budget_mode: str) -> int:
    if budget_mode == BudgetMode.QUIET:
        return min(max_entries, 1)
    if budget_mode == BudgetMode.DEEP:
        return max(max_entries, 5)
    return max_entries


def _budgeted_max_recent(max_recent: int, budget_mode: str) -> int:
    if budget_mode == BudgetMode.QUIET:
        return min(max_recent, 3)
    if budget_mode == BudgetMode.DEEP:
        return max(max_recent, 20)
    return max_recent


def _select_entry_handles(
    handles: list[EntryHandle],
    *,
    max_entries: int,
    budget_mode: str,
    recently_seen_ids: set[str] | None = None,
    feedback_suppressed_ids: set[str] | None = None,
    pinned_ids: set[str] | None = None,
) -> EntrySelection:
    recently_seen_ids = recently_seen_ids or set()
    feedback_suppressed_ids = feedback_suppressed_ids or set()
    pinned_ids = pinned_ids or set()
    budgeted_max = _budgeted_max_entries(max_entries, budget_mode)
    pinned: list[EntryHandle] = []
    candidates: list[EntryHandle] = []
    already_seen = 0
    user_muted = 0
    seen_selected_ids: set[str] = set()
    for handle in handles:
        if handle.id in seen_selected_ids:
            continue
        if handle.id in pinned_ids:
            pinned.append(handle)
            seen_selected_ids.add(handle.id)
            continue
        if handle.id in feedback_suppressed_ids:
            user_muted += 1
            continue
        if budget_mode != BudgetMode.DEEP and handle.id in recently_seen_ids:
            already_seen += 1
            continue
        candidates.append(handle)
        seen_selected_ids.add(handle.id)
    eligible = pinned + candidates
    displayed = tuple(eligible[:budgeted_max])
    return EntrySelection(
        displayed=displayed,
        entries_omitted=max(0, len(eligible) - len(displayed)),
        already_seen_suppressed=already_seen,
        user_muted_suppressed=user_muted,
    )


def build_startup_v2_payload(
    index: Index,
    *,
    now: datetime,
    sync_health: SyncHealth,
    freshness_warning_seconds: int,
    stale_after_seconds: int,
    repo: str | None = None,
    goal: str | None = None,
    max_entries: int = 3,
    days_recent: int = 7,
    max_recent: int = 10,
    coordination: dict[str, Any] | None = None,
    curation: dict[str, Any] | None = None,
    prebuilt_index: InvertedIndex | None = None,
    coverage_overrides: dict[str, Any] | None = None,
    budget_mode: str = BudgetMode.BALANCED.value,
    recently_seen_ids: set[str] | None = None,
    feedback_suppressed_ids: set[str] | None = None,
    pinned_ids: set[str] | None = None,
) -> dict[str, Any]:
    max_recent = _budgeted_max_recent(max_recent, budget_mode)
    manifest = build_context_payload(
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

    all_constraints = constraints_from_context_payload(manifest)

    all_handles = _entry_handles_with_why(manifest)
    selection = _select_entry_handles(
        all_handles,
        max_entries=max_entries,
        budget_mode=budget_mode,
        recently_seen_ids=recently_seen_ids,
        feedback_suppressed_ids=feedback_suppressed_ids,
        pinned_ids=pinned_ids,
    )
    displayed = selection.displayed
    entries_omitted = selection.entries_omitted

    restricted_count = sum(
        1 for e in index.entries.values() if e.frontmatter.sensitivity == Sensitivity.RESTRICTED
    )
    if coverage_overrides and "hidden_restricted_entries" in coverage_overrides:
        restricted_count = int(coverage_overrides["hidden_restricted_entries"])

    freshness = derive_freshness(
        now=now,
        last_success=sync_health.last_success,
        warning_threshold_seconds=freshness_warning_seconds,
        stale_threshold_seconds=stale_after_seconds,
        last_failure=sync_health.last_failure,
        last_error=sync_health.last_error,
        consecutive_failures=sync_health.consecutive_failures,
    )
    first_packet = compile_startup_packet(
        freshness=freshness,
        constraints=all_constraints,
        relevant_entries=displayed,
        entries_omitted=entries_omitted,
        restricted_hidden=restricted_count,
        already_seen_suppressed=selection.already_seen_suppressed,
        duplicates_suppressed=selection.duplicates_suppressed,
        user_muted_suppressed=selection.user_muted_suppressed,
    )
    full_tokens = _full_context_tokens_est(index, manifest)
    first_packet_tokens = estimate_tokens(first_packet)
    total_notices = _startup_notices_omitted(first_packet, all_constraints)
    first_value = compact_value_receipt(
        packet_tokens_est=first_packet_tokens,
        full_context_tokens_est=full_tokens,
        deferred_body_count=len(all_handles),
        skipped_count=max(0, entries_omitted + total_notices),
        suppressed_count=(
            selection.already_seen_suppressed
            + selection.duplicates_suppressed
            + selection.user_muted_suppressed
        ),
        budget_mode=budget_mode,
    )
    value = compact_value_receipt(
        packet_tokens_est=first_packet_tokens + estimate_tokens(first_value),
        full_context_tokens_est=full_tokens,
        deferred_body_count=len(all_handles),
        skipped_count=max(0, entries_omitted + total_notices),
        suppressed_count=(
            selection.already_seen_suppressed
            + selection.duplicates_suppressed
            + selection.user_muted_suppressed
        ),
        budget_mode=budget_mode,
    )
    return compile_startup_packet(
        freshness=freshness,
        constraints=all_constraints,
        relevant_entries=displayed,
        entries_omitted=entries_omitted,
        restricted_hidden=restricted_count,
        already_seen_suppressed=selection.already_seen_suppressed,
        duplicates_suppressed=selection.duplicates_suppressed,
        user_muted_suppressed=selection.user_muted_suppressed,
        value=value,
    )


def _startup_notices_omitted(packet: dict[str, Any], constraints: tuple[Constraint, ...]) -> int:
    inline = len(packet.get("constraints", ()))
    return max(0, len(constraints) - inline)


def _entry_handles_with_why(manifest: dict[str, Any]) -> list[EntryHandle]:
    handles: list[EntryHandle] = []
    for key in ("active", "recent"):
        for item in manifest.get(key, ()):
            if not isinstance(item, dict):
                continue
            entry_id = item.get("id")
            title = item.get("title")
            entry_type = item.get("type")
            if not all((entry_id, title, entry_type)):
                continue
            relevance = item.get("relevance")
            match_reasons = relevance.get("reasons") if isinstance(relevance, dict) else None
            assert isinstance(entry_id, str)
            assert isinstance(title, str)
            assert isinstance(entry_type, str)
            handles.append(
                EntryHandle(
                    id=entry_id,
                    title=title,
                    type=entry_type,
                    summary=item.get("summary"),
                    read_hint=item.get("read_hint"),
                    why=_entry_why(entry_type, match_reasons),
                )
            )
    return handles


def _build_unavailable_startup_v2_payload(
    *,
    now: datetime,
    reason: str,
    freshness_warning_seconds: int,
    stale_after_seconds: int,
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
    return compile_startup_packet(freshness=freshness)


def _build_disabled_startup_v2_payload(
    reason: str = "Ambara is disabled for this project.",
) -> dict[str, Any]:
    return {
        "v": "s2",
        "availability": "disabled",
        "coordination": "clear",
        "action": "proceed_local_only",
        "reason": reason,
    }


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
        "summary": "Ambara is shared agent context backed by a git knowledge repo.",
        "reads": [
            "project state, workflows, decisions, and principles from markdown entries",
            "a local cache after sync, not the live remote on every query",
        ],
        "writes": [
            "record(active): short-lived active context on a non-main active ref",
            (
                "record(project): lightweight review branch, with review request creation "
                "when the path supports it"
            ),
            (
                "propose(workflow/decision/principle): reviewed branch, with review "
                "request creation when the path supports it"
            ),
            (
                "expire(id): active ref deletion or expiry review branch, with review "
                "request creation when the path supports it"
            ),
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


def _render_s2_from_snapshot(
    state: ServerState,
    snapshot: Any,
    *,
    repo: str | None,
    goal: str | None,
    paths: list[str] | None,
    now: datetime,
    max_entries: int,
    include_pr_signals: bool = True,
    recently_seen_ids: set[str] | None = None,
    feedback_suppressed_ids: set[str] | None = None,
    pinned_ids: set[str] | None = None,
) -> dict[str, Any]:
    coord: dict[str, Any] | None = None
    if include_pr_signals and _signals_configured(state.config.pr_signals):
        coord = render_coordination_from_snapshot(
            snapshot,
            state,
            repo=repo,
            goal=goal,
            paths=paths,
            now=now,
        )
    curation = render_curation_from_snapshot(
        snapshot,
        state,
        include_signals=include_pr_signals,
        repo=repo,
        goal=goal,
    )
    cfg = state.config
    return build_startup_v2_payload(
        snapshot.index,
        now=now,
        sync_health=compiler_health_for_context(state, include_signals=include_pr_signals),
        freshness_warning_seconds=cfg.context_freshness_warning_seconds,
        stale_after_seconds=cfg.context_stale_after_seconds,
        repo=repo,
        goal=goal,
        max_entries=max_entries,
        coordination=coord,
        curation=curation,
        prebuilt_index=snapshot.bm25_index,
        coverage_overrides=snapshot_coverage(snapshot),
        budget_mode=cfg.context_budget_mode,
        recently_seen_ids=recently_seen_ids,
        feedback_suppressed_ids=feedback_suppressed_ids,
        pinned_ids=pinned_ids,
    )
