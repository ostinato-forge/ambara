"""MCP tool handlers — orchestration glue between core and git layers."""

from __future__ import annotations

import contextlib
import logging
import queue
import sys
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
from mcp import types
from mcp.server.fastmcp import Context, FastMCP
from mcp.shared.message import SessionMessage

from jurati.core.changes import ExpireIntent, WriteIntent, plan_expire, plan_propose, plan_record
from jurati.core.content_policy import (
    CallerScope,
    PolicyAction,
    PolicySubject,
    PolicyVerdict,
    WritePolicy,
)
from jurati.core.content_policy_config import default_config as default_policy
from jurati.core.graph import (
    build_entry_graph,
    validate_entry_links,
    validate_graph_links,
)
from jurati.core.hygiene import summarize_lifecycle
from jurati.core.schema import (
    EntryStatus,
    EntryType,
    EscalationLevel,
    Sensitivity,
    Visibility,
)
from jurati.core.search import query as core_query
from jurati.core.validate import validate_entry
from jurati.git.auth import AuthCandidate, generate_candidates, parse_github_remote
from jurati.git.branch import (
    cleanup_branch,
    create_branch,
    delete_active_ref,
    push_active_ref,
    push_branch,
)
from jurati.git.commit import materialize_expire, materialize_write
from jurati.git.config import MAX_ACTIVE_REF_TTL_HOURS, load_config_from_env
from jurati.git.pr import PRResult, create_pr, list_open_prs
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo
from jurati.providers.signals import fetch_all_signals
from jurati.server_coordination import (  # noqa: F401
    _format_guidance,
    _privacy_boundary,
    build_coordination_payload,
)
from jurati.server_curation import (  # noqa: F401
    _curation_privacy_boundary,
    _format_curation_advisory,
    _format_revalidation_item,
    build_curation_payload,
)
from jurati.server_guidance import _write_request_examples  # noqa: F401
from jurati.server_index import (
    _add_entry_to_index,
    _get_bm25_index,
    _get_context_snapshot,
    _invalidate_index_cache,
    _remove_entry_from_index,
    _set_context_snapshot,
)
from jurati.server_read import (  # noqa: F401
    _build_compiler_payload,
    _build_context_payload,
    _build_search_results,
    _entry_counts,
    _explain_payload,
    _format_entry,
    _format_entry_manifest,
    _format_hygiene_item,
    _format_hygiene_report,
    _format_result,
    _health_dict,
    _links_for_entry,
    _parse_enum,
    _parse_tag_filter,
    _state_status_payload,
)
from jurati.server_snapshot import (
    build_context_snapshot,
    refresh_signal_cache,
    render_coordination_from_snapshot,
    render_curation_from_snapshot,
    snapshot_coverage,
)
from jurati.server_state import ServerState, SyncHealth
from jurati.server_write import (  # noqa: F401
    _agent_guidance,
    _expire_receipt,
    _format_conflict_entry,
    _format_write_advisories,
    _propose_correction,
    _record_correction,
    _write_advisories_for_intent,
    _write_path_error,
    _write_receipt,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[ServerState]:
    config = load_config_from_env()
    repo_path = await _run_blocking(lambda: ensure_repo(config.remote_url, config.cache_dir))
    await _run_blocking(
        lambda: fetch_all(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
    )
    index = await _run_blocking(
        lambda: load_index_from_repo(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
    )
    now = datetime.now(UTC)
    health = SyncHealth(last_success=now)
    policy_config = default_policy()
    policy = WritePolicy(policy_config)
    state = ServerState(
        config=config,
        repo_path=repo_path,
        index=index,
        last_sync=now,
        sync_health=health,
        content_policy=policy,
        content_policy_config=policy_config,
    )
    _set_context_snapshot(state, build_context_snapshot(state, now=now))
    yield state


mcp = FastMCP("jurati", lifespan=app_lifespan)


def run_stdio() -> None:
    """Run the MCP server over stdio without AnyIO file-wrapper reads.

    In this sandbox, AnyIO's file wrapper can block forever on stdin.readline()
    inside worker threads. The MCP protocol is newline-delimited JSON, so this
    transport keeps the same wire format while using a plain reader thread and
    an async queue poller.
    """

    anyio.run(_run_stdio_async)


async def _run_stdio_async() -> None:
    async with _stdio_server_without_anyio_file_threads() as (read_stream, write_stream):
        await mcp._mcp_server.run(  # noqa: SLF001 - FastMCP exposes no public transport hook.
            read_stream,
            write_stream,
            mcp._mcp_server.create_initialization_options(),  # noqa: SLF001
        )


@asynccontextmanager
async def _stdio_server_without_anyio_file_threads() -> AsyncIterator[tuple[Any, Any]]:
    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](
        0
    )
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)
    stdin_queue: queue.Queue[str | Exception | None] = queue.Queue()

    def read_stdin() -> None:
        try:
            for line in sys.stdin:
                stdin_queue.put(line)
        except Exception as exc:
            stdin_queue.put(exc)
        finally:
            stdin_queue.put(None)

    threading.Thread(target=read_stdin, daemon=True).start()

    async def stdin_pump() -> None:
        async with read_stream_writer:
            while True:
                item = await _poll_queue(stdin_queue)
                if item is None:
                    return
                if isinstance(item, Exception):
                    await read_stream_writer.send(item)
                    continue
                try:
                    message = types.JSONRPCMessage.model_validate_json(item)
                except Exception as exc:  # pragma: no cover - malformed client message
                    logger.exception("Failed to parse JSON-RPC message from stdin")
                    await read_stream_writer.send(exc)
                    continue
                await read_stream_writer.send(SessionMessage(message))

    async def stdout_pump() -> None:
        async with write_stream_reader:
            async for session_message in write_stream_reader:
                payload = session_message.message.model_dump_json(
                    by_alias=True,
                    exclude_none=True,
                )
                sys.stdout.write(payload + "\n")
                sys.stdout.flush()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdin_pump)
        tg.start_soon(stdout_pump)
        try:
            yield read_stream, write_stream
        finally:
            tg.cancel_scope.cancel()


async def _poll_queue[T](items: queue.Queue[T]) -> T:
    while True:
        try:
            return items.get_nowait()
        except queue.Empty:
            await anyio.sleep(0.01)


async def _run_blocking[T](function: Callable[[], T]) -> T:
    """Run blocking git/provider work off the event loop."""

    return await anyio.to_thread.run_sync(function)


def _state(ctx: Context[Any, Any]) -> ServerState:
    return ctx.request_context.lifespan_context  # type: ignore[no-any-return]


async def _build_coordination(
    state: ServerState,
    *,
    repo: str | None,
    goal: str | None,
    paths: list[str] | None,
    now: datetime,
) -> dict[str, Any]:
    return await build_coordination_payload(
        state,
        repo=repo,
        goal=goal,
        paths=paths,
        now=now,
        fetch_signals=fetch_all_signals,
        run_blocking=_run_blocking,
        logger=logger,
    )


async def _build_curation(
    state: ServerState,
    *,
    now: datetime,
    include_signals: bool,
    repo: str | None = None,
    goal: str | None = None,
    max_items: int = 5,
) -> dict[str, Any] | None:
    return await build_curation_payload(
        state,
        now=now,
        include_signals=include_signals,
        repo=repo,
        goal=goal,
        max_items=max_items,
        fetch_signals=fetch_all_signals,
        run_blocking=_run_blocking,
        logger=logger,
    )


@mcp.tool()
async def explain() -> dict[str, Any]:
    """Explain what Jurati does, what it writes, and what it does not track."""
    return _explain_payload()


@mcp.tool()
async def status(ctx: Context[Any, Any]) -> dict[str, Any]:
    """Show the connected knowledge repo, local cache, sync health, and privacy boundary."""
    return _state_status_payload(_state(ctx))


@mcp.tool()
async def hygiene(
    ctx: Context[Any, Any],
    stale_after_days: int = 30,
) -> dict[str, Any]:
    """Summarize expired, stale, and superseded knowledge entries."""
    state = _state(ctx)
    report = summarize_lifecycle(
        state.index,
        now=datetime.now(UTC),
        stale_after_days=stale_after_days,
    )
    payload = _format_hygiene_report(report)

    try:
        stale_prs = await _run_blocking(
            lambda: list_open_prs(
                state.repo_path,
                label="jurati",
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
    body_mode: str = "none",
) -> list[dict[str, Any]]:
    """Search knowledge entries by topic. Returns matching entries ranked by relevance.

    Prefer this over git log, grep, or file reads when looking for team decisions,
    project updates, or coordination state."""
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
    results = core_query(
        state.index,
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
        state.index,
        topic,
        now=now,
        entry_type=entry_type,
        project=project,
        include_expired=include_expired,
        body_mode=body_mode,
        prebuilt_index=_get_bm25_index(state),
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


_VALID_MODES = {"compiler", "full", "manifest"}
READ_MANY_MAX_IDS = 10


@mcp.tool()
async def context(
    ctx: Context[Any, Any],
    repo: str | None = None,
    goal: str | None = None,
    paths: list[str] | None = None,
    include_pr_signals: bool = True,
    mode: str = "manifest",
) -> dict[str, Any]:
    """Get session-start context; call before starting work."""
    if mode not in _VALID_MODES:
        return {"error": f"Invalid mode: {mode!r}. Valid values: {', '.join(sorted(_VALID_MODES))}"}

    state = _state(ctx)
    now = datetime.now(UTC)

    if mode == "compiler":
        snapshot = _get_context_snapshot(state, now=now)
        snapshot_coordination: dict[str, Any] | None = None
        if include_pr_signals and state.config.pr_signals.repos:
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
        return _build_compiler_payload(
            snapshot.index,
            now=now,
            sync_health=state.sync_health,
            freshness_warning_seconds=state.config.context_freshness_warning_seconds,
            stale_after_seconds=state.config.context_stale_after_seconds,
            repo=repo,
            goal=goal,
            coordination=snapshot_coordination,
            curation=curation,
            prebuilt_index=snapshot.bm25_index,
            coverage_overrides=snapshot_coverage(snapshot),
        )

    coordination: dict[str, Any] | None = None
    if include_pr_signals and state.config.pr_signals.repos:
        coordination = await _build_coordination(state, repo=repo, goal=goal, paths=paths, now=now)
    curation = await _build_curation(
        state,
        now=now,
        include_signals=include_pr_signals,
        repo=repo,
        goal=goal,
    )

    return _build_context_payload(
        state.index,
        now=now,
        repo=repo,
        goal=goal,
        mode=mode,
        coordination=coordination,
        curation=curation,
        prebuilt_index=_get_bm25_index(state),
    )


@mcp.tool()
async def search(
    query: str,
    ctx: Context[Any, Any],
    type: str | None = None,
    project: str | None = None,
    tags: str | None = None,
    max_results: int = 10,
    include_expired: bool = False,
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
    return _build_search_results(
        state.index,
        query,
        now=now,
        max_results=max_results,
        entry_type=entry_type,
        project=project,
        tags=tags,
        include_expired=include_expired,
        body_mode=body_mode,
        prebuilt_index=_get_bm25_index(state),
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
        if entry.frontmatter.expires_at is not None and now >= entry.frontmatter.expires_at:
            return {"error": f"Entry {id!r} is expired"}

    graph = build_entry_graph(state.index)
    return _format_entry(entry, graph=graph)


@mcp.tool()
async def read_many(
    ids: list[str],
    ctx: Context[Any, Any],
    include_expired: bool = False,
) -> list[dict[str, Any]]:
    """Read multiple knowledge entries by ID. Returns full entries including bodies.

    More efficient than multiple read() calls — builds the entry graph once."""
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
    graph = build_entry_graph(state.index)
    now = datetime.now(UTC)
    results: list[dict[str, Any]] = []
    for entry_id in ids:
        entry = state.index.get(entry_id)
        if entry is None or entry.frontmatter.sensitivity == Sensitivity.RESTRICTED:
            results.append({"id": entry_id, "error": f"Entry {entry_id!r} not found"})
            continue
        if (
            not include_expired
            and entry.frontmatter.expires_at is not None
            and now >= entry.frontmatter.expires_at
        ):
            results.append({"id": entry_id, "error": f"Entry {entry_id!r} is expired"})
            continue
        results.append(_format_entry(entry, graph=graph))
    return results


@mcp.tool()
async def list_entries(
    ctx: Context[Any, Any],
    type: str | None = None,
    project: str | None = None,
    status: str | None = None,
    include_expired: bool = False,
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

    entries = state.index.list_entries(
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
    """Validate knowledge entries. If id is given, validates that entry; otherwise validates all."""
    state = _state(ctx)

    if id is not None:
        entry = state.index.get(id)
        if entry is None:
            return {"error": f"Entry {id!r} not found"}
        errors = validate_entry(entry)
        errors.extend(validate_entry_links(state.index, entry_id=id))
        return {"id": id, "valid": len(errors) == 0, "errors": errors}

    graph = build_entry_graph(state.index)
    all_results = []
    for entry_id, entry in state.index.entries.items():
        errors = validate_entry(entry)
        errors.extend(validate_graph_links(graph, entry_id=entry_id))
        all_results.append({"id": entry_id, "valid": len(errors) == 0, "errors": errors})
    return {"results": all_results}


@mcp.tool()
async def sync(ctx: Context[Any, Any]) -> dict[str, Any]:
    """Fetch latest changes from the knowledge repo and rebuild the index.

    Call this silently before context() to ensure fresh data. Do not ask the
    developer to call sync — it is an internal housekeeping operation."""
    state = _state(ctx)
    config = state.config

    try:
        await _run_blocking(
            lambda: fetch_all(
                state.repo_path,
                config.main_branch,
                config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
        )
        new_index = await _run_blocking(
            lambda: load_index_from_repo(
                state.repo_path,
                config.main_branch,
                config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
        )
        now = datetime.now(UTC)
        state.sync_health.last_success = now
        state.sync_health.consecutive_failures = 0
        state.sync_health.last_error = None
        state.last_sync = now
        state.index = new_index
        _invalidate_index_cache(state)
        await refresh_signal_cache(
            state,
            now=now,
            fetch_signals=fetch_all_signals,
            run_blocking=_run_blocking,
            logger=logger,
        )
        _set_context_snapshot(state, build_context_snapshot(state, now=now))
        return {
            "status": "ok",
            "what_happened": (
                "Fetched the source-of-truth branch and active refs, then rebuilt "
                "the in-memory index."
            ),
            "visibility": "No knowledge entries were written; this server's local index changed.",
            "entries": len(new_index.entries),
            "last_sync": now.isoformat(),
            "health": _health_dict(state.sync_health),
        }
    except Exception as exc:
        fail_now = datetime.now(UTC)
        state.sync_health.last_failure = fail_now
        state.sync_health.last_error = str(exc)
        state.sync_health.consecutive_failures += 1
        return {
            "status": "error",
            "what_happened": "Sync failed; Jurati kept the last known readable index.",
            "error": type(exc).__name__,
            "next_step": "Check git access, network reachability, and the configured remote.",
            "agent_instruction": (
                "Do not call context() or begin work. Tell the developer that team "
                "context is unavailable and do not proceed from local-only context."
            ),
            "health": _health_dict(state.sync_health),
        }


def _gen_entry_id() -> str:
    return uuid.uuid4().hex[:12]


def _evaluate_content_policy(
    state: ServerState,
    *,
    source: str,
    title: str,
    content: str,
    entry_type: EntryType | None = None,
    level: EscalationLevel | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    visibility: Visibility | None = None,
    sensitivity: Sensitivity | None = None,
) -> PolicyVerdict | None:
    """Evaluate content against policy. Returns a non-allow verdict when relevant."""
    if state.content_policy is None:
        return None

    subject = PolicySubject(
        source=source,  # type: ignore[arg-type]
        title=title,
        body=content,
        entry_type=entry_type,
        level=level,
        projects=tuple(projects or []),
        tags=tuple(tags or []),
        visibility=visibility,
        sensitivity=sensitivity,
    )
    verdict = state.content_policy.evaluate(subject, CallerScope(), now=datetime.now(UTC))

    if verdict.action == PolicyAction.ALLOW and not verdict.rule_ids:
        return None

    return verdict


def _content_policy_block_response(verdict: PolicyVerdict) -> dict[str, Any]:
    return {
        "status": "error",
        "error": "content_policy_block",
        "what_happened": verdict.message,
        "agent_instruction": (
            "Do not retry with the same content. Do not obfuscate the content. "
            "Ask the developer for a safe summary without the sensitive material."
        ),
        "policy_rules": list(verdict.rule_ids),
    }


def _content_policy_review_required_response(verdict: PolicyVerdict) -> dict[str, Any]:
    return {
        "status": "error",
        "error": "content_policy_requires_review",
        "what_happened": verdict.message,
        "agent_instruction": (
            "This content requires human review, so it cannot be written as instant "
            "active context. Propose durable reviewed knowledge, or ask for a safe "
            "handoff summary without the review-triggering material."
        ),
        "policy_rules": list(verdict.rule_ids),
    }


def _content_policy_metadata(verdict: PolicyVerdict | None) -> dict[str, Any] | None:
    if verdict is None or not verdict.rule_ids:
        return None
    return {
        "action": str(verdict.action),
        "policy_rules": list(verdict.rule_ids),
        "labels": list(verdict.review_labels),
        "warning": verdict.warning,
    }


def _content_policy_labels(verdict: PolicyVerdict | None) -> list[str]:
    if verdict is None:
        return []
    return list(verdict.review_labels)


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
    """Record an L0/L1 knowledge entry. L0 pushes via active ref, L1 creates a lightweight PR.

    Use this when the developer asks for a handoff, current focus, breaking
    change note, or project update. If they ask to save something as a team
    decision or workflow, translate that request to propose() instead of asking
    them to choose the API.

    Natural language triggers: "save", "note", "remember", "hand off", "update",
    "pass this to", "leave this for", "the status is", "capture this".

    After recording, confirm the action in one sentence focused on the work, not the
    audience (e.g., "Recorded the token format change."). Do not name or predict who
    will see the entry — you can surface authorship (who wrote something) because
    that's git provenance, but never predict or report readership. Unless debugging
    was explicitly requested, never show entry IDs, ref paths, expiry mechanics,
    branch names, sync instructions, or lifecycle instructions to the developer."""
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
                "active_refs_enabled: true in .jurati/config.yaml and regenerate "
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

    policy_verdict = _evaluate_content_policy(
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
        return _content_policy_block_response(policy_verdict)

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
            return _content_policy_review_required_response(policy_verdict)
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
        policy_metadata = _content_policy_metadata(policy_verdict)
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
            labels=["jurati", "low-ceremony", *_content_policy_labels(policy_verdict)],
            base=config.main_branch,
            remote_url=config.remote_url,
            cached_candidate=state.cached_pr_candidate,
        )
    )
    if new_cached is not None:
        state.cached_pr_candidate = new_cached

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
    policy_metadata = _content_policy_metadata(policy_verdict)
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
        create_branch(repo_path, intent.branch, f"origin/{main_branch}")
        sha = materialize_write(repo_path, intent)
        push_active_ref(repo_path, intent.branch, sha)
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
            with contextlib.suppress(Exception):
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
    """Propose an L2/L3 knowledge entry. Creates a branch and review PR.

    Use this when the developer asks to record a team decision, workflow, or
    lasting principle. If they ask for a short-lived handoff or lightweight
    project update, translate that request to record() instead of asking them
    to choose the API.

    Natural language triggers: "we decided", "the decision is", "going forward",
    "this is how we do X", "document this process", "record this as a decision".

    After proposing, confirm the submission in one sentence (e.g., "Submitted the
    token rotation decision for team review."). Unless debugging was explicitly
    requested, never show entry IDs, branch names, PR numbers, sync instructions,
    or knowledge workflow details to the developer."""
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

    policy_verdict = _evaluate_content_policy(
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
        return _content_policy_block_response(policy_verdict)

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
            labels=["jurati", "review-required", *_content_policy_labels(policy_verdict)],
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
    policy_metadata = _content_policy_metadata(policy_verdict)
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
    """Expire an active knowledge entry. L0 deletes ref, L1+ creates a PR.

    This is typically agent-initiated when work completes (e.g., a PR merges).
    Unless debugging was explicitly requested, do not surface entry IDs, ref paths,
    branch names, PR numbers, sync instructions, or expiry mechanics to the
    developer. If you expire entries after a task completes, do so silently — no
    confirmation needed."""
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
            labels=["jurati", "review-required"],
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
