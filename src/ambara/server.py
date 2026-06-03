# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""MCP tool handlers — orchestration glue between core and git layers."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ambara.core.changes import ExpireIntent, WriteIntent, plan_expire, plan_propose, plan_record
from ambara.core.content_policy import PolicyAction
from ambara.core.graph import (
    validate_entry_links,
    validate_graph_links,
)
from ambara.core.hygiene import summarize_lifecycle
from ambara.core.index import Index
from ambara.core.schema import (
    EntryStatus,
    EntryType,
    EscalationLevel,
    Sensitivity,
    Visibility,
)
from ambara.core.scope_policy import filter_index
from ambara.core.search import query as core_query
from ambara.core.validate import validate_entry
from ambara.git.auth import AuthCandidate, generate_candidates, parse_github_remote
from ambara.git.branch import (
    cleanup_branch,
    create_branch,
    delete_active_ref,
    push_active_ref,
    push_branch,
)
from ambara.git.commit import materialize_expire, materialize_write
from ambara.git.config import (
    MAX_ACTIVE_REF_TTL_HOURS,
    MAX_STARTUP_ENTRIES,
    VALID_CONTEXT_MODES,
    load_config_from_env,
)
from ambara.git.pr import PRResult, create_pr, list_open_prs
from ambara.git.repo import ensure_repo, fetch_all, get_main_tree_hash, load_index_from_repo
from ambara.providers.signals import fetch_all_signals
from ambara.server_async import run_blocking as _run_blocking
from ambara.server_content_policy import (
    content_policy_block_response,
    content_policy_labels,
    content_policy_metadata,
    content_policy_review_required_response,
    evaluate_content_policy,
)
from ambara.server_coordination import build_coordination_payload  # noqa: F401
from ambara.server_curation import (
    _signals_configured,
    build_curation_payload,  # noqa: F401
)
from ambara.server_index import (
    _add_entry_to_index,
    _get_bm25_index,
    _get_context_snapshot,
    _invalidate_index_cache,
    _remove_entry_from_index,
    _set_context_snapshot,
)
from ambara.server_lifespan import app_lifespan as _app_lifespan
from ambara.server_read import (
    _build_compiler_payload,
    _build_disabled_startup_v2_payload,
    _build_search_results,
    _build_unavailable_compiler_payload,
    _build_unavailable_startup_v2_payload,
    _entry_graph_for_state,
    _explain_payload,
    _format_entry,
    _format_entry_manifest,
    _format_hygiene_report,
    _format_result,
    _health_dict,
    _parse_enum,
    _render_s2_from_snapshot,
    _state_status_payload,
    build_context_payload,
)
from ambara.server_snapshot import (
    compiler_health_for_context,
    refresh_context_snapshot,
    render_coordination_from_snapshot,
    render_curation_from_snapshot,
    snapshot_coverage,
    snapshot_status_payload,
)
from ambara.server_state import ServerState, SyncHealth  # noqa: F401
from ambara.server_stdio import run_stdio as _run_stdio
from ambara.server_value import (
    _feedback_suppressed_ids,
    _mark_payload_entries_seen,
    _pinned_ids,
    _recently_seen_ids,
    _record_feedback_signal,
    _record_packet_value_event,
    _record_read_many_value_event,
)
from ambara.server_write import (
    _agent_guidance,
    _expire_receipt,
    _propose_correction,
    _record_correction,
    _write_advisories_for_intent,
    _write_path_error,
    _write_receipt,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[ServerState]:
    async with _app_lifespan(
        server,
        load_config=load_config_from_env,
        ensure_repo_fn=ensure_repo,
        fetch_all_fn=fetch_all,
        load_index_fn=load_index_from_repo,
        tree_hash_fn=get_main_tree_hash,
        fetch_signals=fetch_all_signals,
        run_blocking=_run_blocking,
        logger=logger,
    ) as state:
        yield state


mcp = FastMCP("ambara", lifespan=app_lifespan)


def run_stdio() -> None:
    _run_stdio(mcp, logger=logger)


def _state(ctx: Context[Any, Any]) -> ServerState:
    return ctx.request_context.lifespan_context  # type: ignore[no-any-return]


def _read_index(state: ServerState, *, include_muted: bool = False) -> Index:
    if include_muted:
        return state.index
    return filter_index(state.index, state.config.muted_scopes)


def _prebuilt_bm25_for_index(state: ServerState, index: Index) -> Any | None:
    if index is state.index:
        return _get_bm25_index(state)
    return None


async def _build_coordination(state: ServerState, **kw: Any) -> dict[str, Any]:
    return await build_coordination_payload(
        state,
        **kw,
        fetch_signals=fetch_all_signals,
        run_blocking=_run_blocking,
        logger=logger,
    )


async def _build_curation(state: ServerState, **kw: Any) -> dict[str, Any] | None:
    return await build_curation_payload(
        state,
        **kw,
        fetch_signals=fetch_all_signals,
        run_blocking=_run_blocking,
        logger=logger,
    )


@mcp.tool()
async def explain() -> dict[str, Any]:
    """Explain what Ambara does, what it writes, and what it does not track."""
    return _explain_payload()


@mcp.tool()
async def status(ctx: Context[Any, Any]) -> dict[str, Any]:
    """Show the connected knowledge repo, local cache, and sync health."""
    return _state_status_payload(_state(ctx))


@mcp.tool()
async def hygiene(
    ctx: Context[Any, Any],
    stale_after_days: int = 30,
    include_muted: bool = False,
) -> dict[str, Any]:
    """Summarize expired, stale, and superseded entries."""
    state = _state(ctx)
    report = summarize_lifecycle(
        _read_index(state, include_muted=include_muted),
        now=datetime.now(UTC),
        stale_after_days=stale_after_days,
    )
    payload = _format_hygiene_report(report)

    try:
        stale_prs = await _run_blocking(
            lambda: list_open_prs(
                state.repo_path,
                label="ambara",
                older_than_days=stale_after_days,
            )
        )
        payload["stale_prs"] = [
            {
                "number": pr.number,
                "title": pr.title,
                "url": pr.url,
                "created_at": pr.created_at,
                "branch": pr.branch,
                "next_step": (
                    "Treat this as a coordination signal; do not ask the developer "
                    "to manage the knowledge workflow."
                ),
            }
            for pr in stale_prs
        ]
        payload["summary"]["stale_prs"] = len(stale_prs)
    except Exception:
        payload["stale_prs"] = []
        payload["summary"]["stale_prs"] = 0

    return payload


_VALID_BODY_MODES = {"none", "full"}
_BODY_MODE_ERR = "Invalid body_mode: {!r}. Valid values: full, none"


@mcp.tool()
async def query(
    topic: str,
    ctx: Context[Any, Any],
    type: str | None = None,
    project: str | None = None,
    status: str | None = None,
    include_expired: bool = False,
    include_muted: bool = False,
    body_mode: str = "none",
) -> list[dict[str, Any]]:
    """Search knowledge entries by topic. Returns matching entries ranked by relevance."""
    if body_mode not in _VALID_BODY_MODES:
        return [{"error": _BODY_MODE_ERR.format(body_mode)}]

    state = _state(ctx)
    entry_type, err = _parse_enum(type, EntryType, "type")
    if err:
        return [err]
    entry_status, err = _parse_enum(status, EntryStatus, "status")
    if err:
        return [err]

    now = datetime.now(UTC)
    index = _read_index(state, include_muted=include_muted)
    results = core_query(
        index,
        topic,
        now=now,
        entry_type=entry_type,
        project=project,
        status=entry_status,
        include_expired=include_expired,
    )
    if results:
        return [_format_result(r, body_mode=body_mode) for r in results]

    fallback = _build_search_results(
        index,
        topic,
        now=now,
        entry_type=entry_type,
        project=project,
        include_expired=include_expired,
        body_mode=body_mode,
        prebuilt_index=_prebuilt_bm25_for_index(state, index),
    )
    if fallback:
        return [
            {
                "hint": (
                    "No exact topic matches; showing keyword-ranked results. "
                    "Use search() directly for keyword lookups."
                ),
            },
            *fallback,
        ]
    return []


_VALID_MODES = {*VALID_CONTEXT_MODES, "default"}
READ_MANY_MAX_IDS = 10


@mcp.tool()
async def context(
    ctx: Context[Any, Any],
    repo: str | None = None,
    goal: str | None = None,
    paths: list[str] | None = None,
    include_pr_signals: bool = True,
    mode: str = "default",
) -> dict[str, Any]:
    """Get session-start context; call before starting work."""
    if mode not in _VALID_MODES:
        return {"error": f"Invalid mode: {mode!r}. Valid values: {', '.join(sorted(_VALID_MODES))}"}

    state = _state(ctx)
    mode = state.config.context_default_mode if mode == "default" else mode
    now = datetime.now(UTC)

    if state.config.disabled:
        payload = _build_disabled_startup_v2_payload()
        _record_packet_value_event(
            state, tool_name="context", context_schema="startup-s2", payload=payload, now=now
        )
        return payload

    if mode == "startup":
        snapshot = _get_context_snapshot(state, now=now)
        if snapshot is None:
            payload = _build_unavailable_startup_v2_payload(
                now=now,
                reason="context snapshot unavailable; run sync() before context()",
                freshness_warning_seconds=state.config.context_freshness_warning_seconds,
                stale_after_seconds=state.config.context_stale_after_seconds,
            )
            _record_packet_value_event(
                state, tool_name="context", context_schema="startup-s2", payload=payload, now=now
            )
            return payload
        payload = _render_s2_from_snapshot(
            state,
            snapshot,
            repo=repo,
            goal=goal,
            paths=paths,
            now=now,
            max_entries=state.config.startup_max_entries,
            include_pr_signals=include_pr_signals,
            recently_seen_ids=_recently_seen_ids(state, now=now),
            feedback_suppressed_ids=_feedback_suppressed_ids(state),
            pinned_ids=_pinned_ids(state),
        )
        _mark_payload_entries_seen(state, payload, now=now)
        _record_packet_value_event(
            state, tool_name="context", context_schema="startup-s2", payload=payload, now=now
        )
        return payload

    if mode == "compiler":
        snapshot = _get_context_snapshot(state, now=now)
        if snapshot is None:
            payload = _build_unavailable_compiler_payload(
                now=now,
                reason="context snapshot unavailable; run sync() before context()",
                freshness_warning_seconds=state.config.context_freshness_warning_seconds,
                stale_after_seconds=state.config.context_stale_after_seconds,
                coverage={"prepared_snapshot_required": True},
            )
            _record_packet_value_event(
                state, tool_name="context", context_schema="compiler-v1", payload=payload, now=now
            )
            return payload
        snapshot_coordination: dict[str, Any] | None = None
        if include_pr_signals and _signals_configured(state.config.pr_signals):
            snapshot_coordination = render_coordination_from_snapshot(
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
        payload = _build_compiler_payload(
            snapshot.index,
            now=now,
            sync_health=compiler_health_for_context(state, include_signals=include_pr_signals),
            freshness_warning_seconds=state.config.context_freshness_warning_seconds,
            stale_after_seconds=state.config.context_stale_after_seconds,
            repo=repo,
            goal=goal,
            coordination=snapshot_coordination,
            curation=curation,
            prebuilt_index=snapshot.bm25_index,
            coverage_overrides=snapshot_coverage(snapshot),
            budget_mode=state.config.context_budget_mode,
            recently_seen_ids=_recently_seen_ids(state, now=now),
            feedback_suppressed_ids=_feedback_suppressed_ids(state),
            pinned_ids=_pinned_ids(state),
        )
        _mark_payload_entries_seen(state, payload, now=now)
        _record_packet_value_event(
            state, tool_name="context", context_schema="compiler-v1", payload=payload, now=now
        )
        return payload

    coordination: dict[str, Any] | None = None
    if include_pr_signals and _signals_configured(state.config.pr_signals):
        coordination = await build_coordination_payload(
            state,
            repo=repo,
            goal=goal,
            paths=paths,
            now=now,
            fetch_signals=fetch_all_signals,
            run_blocking=_run_blocking,
            logger=logger,
        )
    curation = await build_curation_payload(
        state,
        now=now,
        include_signals=include_pr_signals,
        repo=repo,
        goal=goal,
        fetch_signals=fetch_all_signals,
        run_blocking=_run_blocking,
        logger=logger,
    )

    index = _read_index(state)
    payload = build_context_payload(
        index,
        now=now,
        repo=repo,
        goal=goal,
        mode=mode,
        coordination=coordination,
        curation=curation,
        prebuilt_index=_prebuilt_bm25_for_index(state, index),
    )
    _record_packet_value_event(
        state,
        tool_name="context",
        context_schema=str(payload.get("context_schema", mode)),
        payload=payload,
        now=now,
    )
    _mark_payload_entries_seen(state, payload, now=now)
    return payload


@mcp.tool()
async def search(
    query: str,
    ctx: Context[Any, Any],
    type: str | None = None,
    project: str | None = None,
    tags: str | None = None,
    max_results: int = 10,
    include_expired: bool = False,
    include_muted: bool = False,
    body_mode: str = "none",
) -> list[dict[str, Any]]:
    """Search knowledge entries with BM25 relevance ranking."""
    if body_mode not in _VALID_BODY_MODES:
        return [{"error": _BODY_MODE_ERR.format(body_mode)}]

    state = _state(ctx)
    now = datetime.now(UTC)
    entry_type, err = _parse_enum(type, EntryType, "type")
    if err:
        return [err]
    index = _read_index(state, include_muted=include_muted)
    return _build_search_results(
        index,
        query,
        now=now,
        max_results=max_results,
        entry_type=entry_type,
        project=project,
        tags=tags,
        include_expired=include_expired,
        body_mode=body_mode,
        prebuilt_index=_prebuilt_bm25_for_index(state, index),
    )


@mcp.tool()
async def read(
    id: str,
    ctx: Context[Any, Any],
    include_expired: bool = False,
) -> dict[str, Any]:
    """Read a single knowledge entry by ID. Returns the full entry including body."""
    state = _state(ctx)
    entry = state.index.get(id)
    if entry is None:
        return {"error": f"Entry {id!r} not found"}
    if entry.frontmatter.sensitivity == Sensitivity.RESTRICTED:
        return {"error": f"Entry {id!r} not found"}

    if not include_expired:
        now = datetime.now(UTC)
        if (
            entry.frontmatter.expires_at is not None
            and now >= entry.frontmatter.expires_at
            or entry.frontmatter.status in (EntryStatus.EXPIRED, EntryStatus.SUPERSEDED)
        ):
            return {"error": f"Entry {id!r} is expired"}

    graph = _entry_graph_for_state(state)
    return _format_entry(entry, graph=graph)


@mcp.tool()
async def read_many(
    ids: list[str],
    ctx: Context[Any, Any],
    include_expired: bool = False,
) -> list[dict[str, Any]]:
    """Read multiple knowledge entries by ID. Returns full entries including bodies."""
    if len(ids) > READ_MANY_MAX_IDS:
        return [
            {
                "error": "read_many_batch_too_large",
                "requested": len(ids),
                "max_ids": READ_MANY_MAX_IDS,
                "next_step": (
                    f"Call read_many again with at most {READ_MANY_MAX_IDS} ids, "
                    "or narrow first with context(), query(), or search()."
                ),
            }
        ]

    state = _state(ctx)
    graph = _entry_graph_for_state(state)
    now = datetime.now(UTC)
    results: list[dict[str, Any]] = []
    for entry_id in ids:
        entry = state.index.get(entry_id)
        if entry is None or entry.frontmatter.sensitivity == Sensitivity.RESTRICTED:
            results.append({"id": entry_id, "error": f"Entry {entry_id!r} not found"})
            continue
        if not include_expired and (
            entry.frontmatter.expires_at is not None
            and now >= entry.frontmatter.expires_at
            or entry.frontmatter.status in (EntryStatus.EXPIRED, EntryStatus.SUPERSEDED)
        ):
            results.append({"id": entry_id, "error": f"Entry {entry_id!r} is expired"})
            continue
        results.append(_format_entry(entry, graph=graph))
    _record_read_many_value_event(state, result=results, now=now)
    return results


@mcp.tool()
async def feedback(
    entry_id: str,
    signal: str,
    ctx: Context[Any, Any],
    scope: str = "session",
) -> dict[str, Any]:
    """Record local relevance feedback for future context packing."""
    state = _state(ctx)
    return _record_feedback_signal(state, entry_id=entry_id, signal=signal, scope=scope)


@mcp.tool()
async def list_entries(
    ctx: Context[Any, Any],
    type: str | None = None,
    project: str | None = None,
    status: str | None = None,
    include_expired: bool = False,
    include_muted: bool = False,
    body_mode: str = "none",
) -> list[dict[str, Any]]:
    """List knowledge entries with optional filters."""
    if body_mode not in _VALID_BODY_MODES:
        return [{"error": _BODY_MODE_ERR.format(body_mode)}]

    state = _state(ctx)
    entry_type, err = _parse_enum(type, EntryType, "type")
    if err:
        return [err]
    entry_status, err = _parse_enum(status, EntryStatus, "status")
    if err:
        return [err]

    index = _read_index(state, include_muted=include_muted)
    entries = index.list_entries(
        now=datetime.now(UTC),
        entry_type=entry_type,
        project=project,
        status=entry_status,
        include_expired=include_expired,
    )
    fmt = _format_entry_manifest if body_mode == "none" else _format_entry
    return [fmt(e) for e in entries]


@mcp.tool()
async def validate(
    ctx: Context[Any, Any],
    id: str | None = None,
) -> dict[str, Any]:
    """Validate knowledge entries. If id is given, validates that entry."""
    state = _state(ctx)

    if id is not None:
        entry = state.index.get(id)
        if entry is None:
            return {"error": f"Entry {id!r} not found"}
        errors = validate_entry(entry)
        errors.extend(validate_entry_links(state.index, entry_id=id))
        return {"id": id, "valid": len(errors) == 0, "errors": errors}

    graph = _entry_graph_for_state(state)
    all_results = []
    for entry_id, entry in state.index.entries.items():
        errors = validate_entry(entry)
        errors.extend(validate_graph_links(graph, entry_id=entry_id))
        all_results.append({"id": entry_id, "valid": len(errors) == 0, "errors": errors})
    return {"results": all_results}


_FETCH_THROTTLE_SECONDS = 30


async def _sync_state(state: ServerState) -> Any:
    config = state.config
    now_pre = datetime.now(UTC)
    fetch_skipped = (
        state._last_fetch_at is not None
        and (now_pre - state._last_fetch_at).total_seconds() < _FETCH_THROTTLE_SECONDS
    )
    if not fetch_skipped:
        await _run_blocking(
            lambda: fetch_all(
                state.repo_path,
                config.main_branch,
                config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
        )
        state._last_fetch_at = datetime.now(UTC)
    new_tree_hash = await _run_blocking(
        lambda: get_main_tree_hash(state.repo_path, config.main_branch)
    )
    tree_changed = new_tree_hash != state._index_tree_hash
    if tree_changed or config.active_refs_enabled:
        new_index = await _run_blocking(
            lambda: load_index_from_repo(
                state.repo_path,
                config.main_branch,
                config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
        )
        state.index = new_index
        state._index_tree_hash = new_tree_hash
        _invalidate_index_cache(state)
    now = datetime.now(UTC)
    state.sync_health.last_success = now
    state.sync_health.consecutive_failures = 0
    state.sync_health.last_error = None
    state.last_sync = now
    snapshot = await refresh_context_snapshot(
        state,
        now=now,
        fetch_signals=fetch_all_signals,
        run_blocking=_run_blocking,
        logger=logger,
    )
    _set_context_snapshot(state, snapshot)
    return snapshot, now, state.index


@mcp.tool()
async def sync(ctx: Context[Any, Any]) -> dict[str, Any]:
    """Fetch latest changes, rebuild the index, and prepare a context snapshot."""
    state = _state(ctx)
    if state.config.disabled:
        return {
            "status": "disabled",
            "what_happened": "Ambara is disabled for this project.",
            "agent_instruction": (
                "Proceed from local project context; do not treat this as a team-context failure."
            ),
            "health": _health_dict(state.sync_health),
        }
    try:
        _, now, new_index = await _sync_state(state)
        return {
            "status": "ok",
            "what_happened": "Fetched source-of-truth branch and rebuilt the index.",
            "entries": len(new_index.entries),
            "last_sync": now.isoformat(),
            "health": _health_dict(state.sync_health),
            "context_snapshot": snapshot_status_payload(state, now=now),
        }
    except Exception as exc:
        fail_now = datetime.now(UTC)
        state.sync_health.last_failure = fail_now
        state.sync_health.last_error = str(exc)
        state.sync_health.consecutive_failures += 1
        return {
            "status": "error",
            "what_happened": "Sync failed; kept last known index.",
            "error": type(exc).__name__,
            "agent_instruction": "Tell the developer shared context is unavailable.",
            "health": _health_dict(state.sync_health),
        }


@mcp.tool()
async def startup(
    ctx: Context[Any, Any],
    repo: str | None = None,
    goal: str | None = None,
    max_entries: int | None = None,
) -> dict[str, Any]:
    """Sync and compile project context. Call before local exploration."""
    state = _state(ctx)
    config = state.config

    if config.disabled:
        payload = _build_disabled_startup_v2_payload()
        _record_packet_value_event(
            state,
            tool_name="startup",
            context_schema="startup-s2",
            payload=payload,
            now=datetime.now(UTC),
        )
        return payload

    if max_entries is None:
        max_entries = config.startup_max_entries
    max_entries = min(max(max_entries, 1), MAX_STARTUP_ENTRIES)

    try:
        snapshot, now, _ = await _sync_state(state)
    except Exception as exc:
        fail_now = datetime.now(UTC)
        state.sync_health.last_failure = fail_now
        state.sync_health.last_error = str(exc)
        state.sync_health.consecutive_failures += 1
        payload = _build_unavailable_startup_v2_payload(
            now=fail_now,
            reason=f"Sync failed: {type(exc).__name__}. Shared context unavailable.",
            freshness_warning_seconds=config.context_freshness_warning_seconds,
            stale_after_seconds=config.context_stale_after_seconds,
        )
        _record_packet_value_event(
            state, tool_name="startup", context_schema="startup-s2", payload=payload, now=fail_now
        )
        return payload

    payload = _render_s2_from_snapshot(
        state,
        snapshot,
        repo=repo,
        goal=goal,
        paths=None,
        now=now,
        max_entries=max_entries,
        recently_seen_ids=_recently_seen_ids(state, now=now),
        feedback_suppressed_ids=_feedback_suppressed_ids(state),
        pinned_ids=_pinned_ids(state),
    )
    _mark_payload_entries_seen(state, payload, now=now)
    _record_packet_value_event(
        state, tool_name="startup", context_schema="startup-s2", payload=payload, now=now
    )
    return payload


def _gen_entry_id() -> str:
    return uuid.uuid4().hex[:12]


@mcp.tool()
async def record(
    type: str,
    title: str,
    content: str,
    ctx: Context[Any, Any],
    entry_id: str | None = None,
    level: str | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    expires_at: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """Record a handoff, project update, or breaking change note (L0/L1).

    Use for: "save this", "note", "hand off", "status update".
    For project decisions or workflows, use propose() instead.
    Confirm in one sentence about the work. Never expose entry IDs."""
    state = _state(ctx)
    config = state.config
    now = datetime.now(UTC)
    eid = entry_id or _gen_entry_id()
    entry_type, err = _parse_enum(type, EntryType, "type")
    if err:
        return err
    esc_level, err = _parse_enum(level, EscalationLevel, "level")
    if err:
        return err

    if entry_type == EntryType.ACTIVE and not config.active_refs_enabled:
        return {
            "error": (
                "Active context is disabled by repo policy. Set "
                "active_refs_enabled: true in .ambara/config.yaml and regenerate "
                "project MCP config to opt in."
            )
        }

    viz, err = _parse_enum(visibility, Visibility, "visibility")
    if err:
        return err

    try:
        exp = datetime.fromisoformat(expires_at) if expires_at else None
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
    except ValueError:
        return {"error": f"Invalid expires_at: {expires_at!r}. Expected ISO-8601 format."}

    if entry_type == EntryType.ACTIVE and config.active_refs_enabled:
        if not 1 <= config.active_ref_ttl_hours <= MAX_ACTIVE_REF_TTL_HOURS:
            return {
                "error": (
                    "Active context repo policy TTL must be between 1 and "
                    f"{MAX_ACTIVE_REF_TTL_HOURS}h."
                )
            }
        max_expiry = now + timedelta(hours=config.active_ref_ttl_hours)
        if exp is None:
            exp = max_expiry
        elif exp > max_expiry:
            return {
                "error": (
                    "Active context expires_at exceeds repo policy TTL "
                    f"({config.active_ref_ttl_hours}h)."
                )
            }

    policy_verdict = evaluate_content_policy(
        state,
        source="record",
        title=title,
        content=content,
        entry_type=entry_type,
        level=esc_level,
        projects=projects,
        tags=tags,
        visibility=viz,
    )
    if policy_verdict is not None and policy_verdict.action == PolicyAction.BLOCK:
        return content_policy_block_response(policy_verdict)

    try:
        intent = plan_record(
            entry_type,
            title,
            content,
            entry_id=eid,
            level=esc_level,
            projects=projects,
            tags=tags,
            now=now,
            expires_at=exp,
            branch_prefix=config.branch_prefix,
            active_ref_prefix=config.active_ref_prefix,
            client=config.client_slug,
            visibility=viz,
        )
    except ValueError as exc:
        return _write_path_error(
            message=str(exc),
            correction=_record_correction(
                entry_type=entry_type,
                level=esc_level,
                title=title,
                content=content,
                entry_id=eid,
                projects=projects,
                tags=tags,
                visibility=viz,
            ),
        )

    write_advisories = _write_advisories_for_intent(state.index, intent, now=now)

    if intent.write_mode == "active_ref":
        if policy_verdict is not None and policy_verdict.action == PolicyAction.REQUIRE_REVIEW:
            return content_policy_review_required_response(policy_verdict)
        sha = await _run_blocking(
            lambda: _do_active_record(state.write_lock, state.repo_path, intent, config.main_branch)
        )
        if intent.entry is not None:
            _add_entry_to_index(state, intent.entry)
        response = {
            "status": "ok",
            "entry_id": eid,
            "write_mode": "active_ref",
            **_write_receipt(
                entry_id=eid,
                write_mode="active_ref",
                commit=sha,
                active_ref=f"refs/heads/{intent.branch}",
            ),
        }
        policy_metadata = content_policy_metadata(policy_verdict)
        if policy_metadata is not None:
            response["content_policy"] = policy_metadata
        if write_advisories is not None:
            response["write_advisories"] = write_advisories
        return response

    if intent.branch is None:
        return {"error": "branch must not be None for L1 record"}
    sha, pr_result, new_cached = await _run_blocking(
        lambda: _finish_pr_write(
            state.write_lock,
            state.repo_path,
            intent,
            title=f"feat(kb): add {eid}",
            body=f"Add {entry_type} entry: {title}",
            labels=["ambara", "low-ceremony", *content_policy_labels(policy_verdict)],
            base=config.main_branch,
            remote_url=config.remote_url,
            cached_candidate=state.cached_pr_candidate,
        )
    )
    if new_cached is not None:
        state.cached_pr_candidate = new_cached
    if intent.entry is not None:
        _add_entry_to_index(state, intent.entry)
    write_mode = "lightweight_pr" if pr_result.kind == "pr" else "branch_only"
    response = {
        "status": "ok",
        "entry_id": eid,
        "write_mode": write_mode,
        **_write_receipt(
            entry_id=eid,
            write_mode=write_mode,
            commit=sha,
            branch=intent.branch,
            pr_url=pr_result.url,
            pr_number=pr_result.number,
        ),
    }
    policy_metadata = content_policy_metadata(policy_verdict)
    if policy_metadata is not None:
        response["content_policy"] = policy_metadata
    if write_advisories is not None:
        response["write_advisories"] = write_advisories
    return response


def _do_active_record(
    lock: threading.Lock, repo_path: str, intent: WriteIntent, main_branch: str
) -> str:
    assert intent.branch is not None
    with lock:
        try:
            create_branch(repo_path, intent.branch, f"origin/{main_branch}")
            sha = materialize_write(repo_path, intent)
            push_active_ref(repo_path, intent.branch, sha)
        finally:
            with suppress(Exception):
                cleanup_branch(repo_path, intent.branch, main_branch)
    return sha


def _check_remote_branch(repo_path: str, branch_prefix: str, entry_id: str) -> bool:
    import git as gitpkg

    repo = gitpkg.Repo(repo_path)
    target = f"origin/{branch_prefix}/{entry_id}"
    return any(ref.name == target for ref in repo.refs)


def _finish_pr_write(
    lock: threading.Lock,
    repo_path: str,
    intent: WriteIntent | ExpireIntent,
    *,
    title: str,
    body: str,
    labels: list[str],
    base: str,
    remote_url: str,
    cached_candidate: AuthCandidate | None,
    now: datetime | None = None,
) -> tuple[str, PRResult, AuthCandidate | None]:
    if intent.branch is None:
        raise ValueError("branch must not be None for PR write")
    branch = intent.branch
    parsed = parse_github_remote(remote_url)
    if parsed is not None:
        owner, repo = parsed
        candidates: list[AuthCandidate] = []
        if cached_candidate is not None:
            candidates.append(cached_candidate)
        candidates.extend(generate_candidates(owner, repo))
    else:
        candidates = []
    with lock:
        try:
            create_branch(repo_path, branch, f"origin/{base}")
            if isinstance(intent, ExpireIntent):
                if now is None:
                    raise ValueError("now is required for ExpireIntent")
                sha = materialize_expire(repo_path, intent, now)
            elif isinstance(intent, WriteIntent):
                sha = materialize_write(repo_path, intent)
            else:
                raise TypeError(f"unexpected intent type: {type(intent)}")
            push_branch(repo_path, branch)
            pr_result, winning_candidate = create_pr(
                repo_path,
                branch,
                title,
                body,
                labels=labels,
                base=base,
                candidates=candidates,
            )
            return sha, pr_result, winning_candidate
        finally:
            with suppress(Exception):
                cleanup_branch(repo_path, branch, base)


def _do_active_expire(lock: threading.Lock, repo_path: str, ref_path: str) -> None:
    with lock:
        delete_active_ref(repo_path, ref_path)


@mcp.tool()
async def propose(
    type: str,
    title: str,
    content: str,
    ctx: Context[Any, Any],
    entry_id: str | None = None,
    level: str | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """Propose a project decision or workflow for review (L2/L3).

    Use for: "we decided", "going forward", "this is how we do X".
    For handoffs or status updates, use record() instead.
    Confirm in one sentence. Never expose workflow details."""
    state = _state(ctx)
    config = state.config
    now = datetime.now(UTC)
    eid = entry_id or _gen_entry_id()
    entry_type, err = _parse_enum(type, EntryType, "type")
    if err:
        return err
    esc_level, err = _parse_enum(level, EscalationLevel, "level")
    if err:
        return err
    viz, err = _parse_enum(visibility, Visibility, "visibility")
    if err:
        return err

    policy_verdict = evaluate_content_policy(
        state,
        source="propose",
        title=title,
        content=content,
        entry_type=entry_type,
        level=esc_level,
        projects=projects,
        tags=tags,
        visibility=viz,
    )
    if policy_verdict is not None and policy_verdict.action == PolicyAction.BLOCK:
        return content_policy_block_response(policy_verdict)

    try:
        intent = plan_propose(
            entry_type,
            title,
            content,
            entry_id=eid,
            level=esc_level,
            projects=projects,
            tags=tags,
            now=now,
            branch_prefix=config.branch_prefix,
            client=config.client_slug,
            visibility=viz,
        )
    except ValueError as exc:
        return _write_path_error(
            message=str(exc),
            correction=_propose_correction(
                entry_type=entry_type,
                level=esc_level,
                title=title,
                content=content,
                entry_id=eid,
                projects=projects,
                tags=tags,
                visibility=viz,
            ),
        )

    if intent.branch is None:
        return {"error": "branch must not be None for propose"}

    write_advisories = _write_advisories_for_intent(state.index, intent, now=now)

    sha, pr_result, new_cached = await _run_blocking(
        lambda: _finish_pr_write(
            state.write_lock,
            state.repo_path,
            intent,
            title=f"feat(kb): propose {eid}",
            body=f"Propose {entry_type} entry: {title}",
            labels=["ambara", "review-required", *content_policy_labels(policy_verdict)],
            base=config.main_branch,
            remote_url=config.remote_url,
            cached_candidate=state.cached_pr_candidate,
        )
    )
    if new_cached is not None:
        state.cached_pr_candidate = new_cached

    if intent.entry is not None:
        _add_entry_to_index(state, intent.entry)

    write_mode = "review_pr" if pr_result.kind == "pr" else "branch_only"
    response = {
        "status": "ok",
        "entry_id": eid,
        "write_mode": write_mode,
        **_write_receipt(
            entry_id=eid,
            write_mode=write_mode,
            commit=sha,
            branch=intent.branch,
            pr_url=pr_result.url,
            pr_number=pr_result.number,
        ),
    }
    policy_metadata = content_policy_metadata(policy_verdict)
    if policy_metadata is not None:
        response["content_policy"] = policy_metadata
    if write_advisories is not None:
        response["write_advisories"] = write_advisories
    return response


@mcp.tool()
async def expire(
    id: str,
    ctx: Context[Any, Any],
    reason: str | None = None,
) -> dict[str, Any]:
    """Expire an active knowledge entry. L0 deletes ref, L1+ creates a PR."""
    state = _state(ctx)
    config = state.config
    now = datetime.now(UTC)

    entry = state.index.get(id)
    if entry is None:
        has_branch = await _run_blocking(
            lambda: _check_remote_branch(state.repo_path, config.branch_prefix, id)
        )
        if has_branch:
            return {
                "error": "Entry is pending review and is not available to expire yet.",
                "entry_id": id,
                "branch": f"{config.branch_prefix}/{id}",
                "agent_guidance": _agent_guidance(
                    "That update is still pending review, so there is nothing to clear yet."
                ),
            }
        return {"error": "Entry not found.", "entry_id": id}

    intent = plan_expire(entry, now=now)

    if intent.write_mode == "active_ref":
        ref_path = f"{config.active_ref_prefix}/{config.client_slug}/{id}"
        await _run_blocking(lambda: _do_active_expire(state.write_lock, state.repo_path, ref_path))
        _remove_entry_from_index(state, id)
        return {
            "status": "ok",
            "entry_id": id,
            "write_mode": "active_ref",
            **_expire_receipt(
                entry_id=id,
                write_mode="active_ref",
                active_ref=f"refs/heads/{ref_path}",
            ),
        }

    if intent.branch is None:
        return {"error": "branch must not be None for non-L0 expire"}

    sha, pr_result, new_cached = await _run_blocking(
        lambda: _finish_pr_write(
            state.write_lock,
            state.repo_path,
            intent,
            title=f"chore(kb): expire {id}",
            body=reason or f"Expire entry: {entry.frontmatter.title}",
            labels=["ambara", "review-required"],
            base=config.main_branch,
            remote_url=config.remote_url,
            cached_candidate=state.cached_pr_candidate,
            now=now,
        )
    )
    if new_cached is not None:
        state.cached_pr_candidate = new_cached

    write_mode = intent.write_mode if pr_result.kind == "pr" else "branch_only"
    return {
        "status": "ok",
        "entry_id": id,
        "write_mode": write_mode,
        **_expire_receipt(
            entry_id=id,
            write_mode=write_mode,
            commit=sha,
            branch=intent.branch,
            pr_url=pr_result.url,
            pr_number=pr_result.number,
        ),
    }
