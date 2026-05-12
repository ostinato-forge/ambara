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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, cast

import anyio
from mcp import types
from mcp.server.fastmcp import Context, FastMCP
from mcp.shared.message import SessionMessage

from jurati.core.changes import ExpireIntent, WriteIntent, plan_expire, plan_propose, plan_record
from jurati.core.graph import (
    EntryGraph,
    build_entry_graph,
    validate_entry_links,
    validate_graph_links,
)
from jurati.core.hygiene import HygieneItem, HygieneReport, summarize_lifecycle
from jurati.core.index import Index
from jurati.core.pr_signals import CoordinationGuidance, classify_signals
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Sensitivity,
    Visibility,
)
from jurati.core.scoring import InvertedIndex, build_inverted_index, rank_entries
from jurati.core.search import SearchResult
from jurati.core.search import query as core_query
from jurati.core.validate import is_expired, validate_entry
from jurati.git.auth import AuthCandidate, generate_candidates, parse_github_remote
from jurati.git.branch import (
    cleanup_branch,
    create_branch,
    delete_active_ref,
    push_active_ref,
    push_branch,
)
from jurati.git.commit import materialize_expire, materialize_write
from jurati.git.config import JuratiConfig, load_config_from_env
from jurati.git.pr import PRResult, create_pr, list_open_prs
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo
from jurati.providers.cache import SignalCache
from jurati.providers.signals import fetch_all_signals

logger = logging.getLogger(__name__)


@dataclass
class SyncHealth:
    last_success: datetime | None = None
    last_failure: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0


@dataclass
class ServerState:
    config: JuratiConfig
    repo_path: str
    index: Index
    last_sync: datetime
    sync_health: SyncHealth
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    cached_pr_candidate: AuthCandidate | None = None
    signal_cache: SignalCache = field(default_factory=lambda: SignalCache(recency_days=30))
    _cached_bm25_index: InvertedIndex | None = field(default=None, repr=False)
    _index_generation: int = field(default=0, repr=False)


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
    yield ServerState(
        config=config,
        repo_path=repo_path,
        index=index,
        last_sync=now,
        sync_health=health,
    )


logger = logging.getLogger(__name__)

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
    """Run blocking git work without relying on the event loop's thread pool."""

    result_queue: queue.Queue[tuple[bool, T | BaseException]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            result_queue.put((True, function()))
        except BaseException as exc:
            result_queue.put((False, exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while True:
        try:
            success, result = result_queue.get_nowait()
        except queue.Empty:
            await anyio.sleep(0.01)
            continue
        thread.join(timeout=0)
        if success:
            return cast("T", result)
        assert isinstance(result, BaseException)
        raise result


def _state(ctx: Context[Any, Any]) -> ServerState:
    return ctx.request_context.lifespan_context  # type: ignore[no-any-return]


def _get_bm25_index(state: ServerState) -> InvertedIndex:
    if state._cached_bm25_index is None:
        all_entries = list(state.index.entries.values())
        state._cached_bm25_index = build_inverted_index(all_entries)
    return state._cached_bm25_index


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


def _write_request_examples() -> list[dict[str, str]]:
    return [
        {
            "developer_request": "Record this as a team decision.",
            "tool": "propose",
            "type": "decision",
            "why": (
                "durable team decisions require review before they become "
                "shared source-of-truth context"
            ),
        },
        {
            "developer_request": "Save this handoff for the next agent.",
            "tool": "record",
            "type": "active",
            "why": "short-lived handoffs belong on the active context path",
        },
        {
            "developer_request": "Capture this project update.",
            "tool": "record",
            "type": "project",
            "why": (
                "project updates are lightweight shared context, not reviewed decisions by default"
            ),
        },
    ]


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
    days_recent: int = 7,
    coordination: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recent_cutoff = now - timedelta(days=days_recent)

    active = [
        _format_entry(e)
        for e in index.entries.values()
        if e.frontmatter.type == EntryType.ACTIVE
        and not is_expired(e, now)
        and e.frontmatter.sensitivity != Sensitivity.RESTRICTED
    ]

    recent = [
        _format_entry(e)
        for e in index.entries.values()
        if e.frontmatter.type != EntryType.ACTIVE
        and e.frontmatter.updated_at >= recent_cutoff
        and e.frontmatter.status in (EntryStatus.ACTIVE, EntryStatus.PROPOSED)
        and e.frontmatter.sensitivity != Sensitivity.RESTRICTED
    ]

    recent.sort(key=lambda r: r.get("updated_at", ""), reverse=True)

    payload: dict[str, Any] = {"active": active, "recent": recent[:15]}
    if coordination is not None:
        payload["coordination"] = coordination
    return payload


def _format_guidance(g: CoordinationGuidance) -> dict[str, Any]:
    return {
        "effect": g.effect,
        "urgency": g.urgency,
        "summary": g.summary,
        "instruction": g.instruction,
        "confidence": g.confidence,
        "evidence": [
            {
                "repo": ev.repo,
                "number": ev.number,
                "url": ev.url,
                "title": ev.title,
                "author": ev.author,
                "state": ev.state,
                "updated_at": ev.updated_at.isoformat(),
                "merged_at": ev.merged_at.isoformat() if ev.merged_at else None,
                "matched_paths": list(ev.matched_paths),
                "changed_paths_status": ev.changed_paths_status,
                "body_excerpt": ev.body_excerpt,
                "reason": ev.reason,
            }
            for ev in g.evidence
        ],
    }


async def _build_coordination(
    state: ServerState,
    *,
    repo: str | None,
    goal: str | None,
    paths: list[str] | None,
    now: datetime,
) -> dict[str, Any]:
    cache = state.signal_cache
    config = state.config.pr_signals

    if cache.needs_refresh(now):
        try:
            signals = await _run_blocking(lambda: fetch_all_signals(config))
            cache.update(signals, now=now)
        except Exception:
            logger.warning("PR signal refresh failed; using cached data", exc_info=True)

    cached = cache.get_signals()
    if not cached:
        return {
            "status": "ok",
            "summary": "No jurati-labeled PRs in configured repos.",
            "guidance": [],
            "privacy_boundary": _privacy_boundary(),
        }

    guidance = classify_signals(
        cached,
        repo=repo,
        _goal=goal,
        paths=paths,
        now=now,
        recency_days=config.recency_days,
    )

    active_effects = [g for g in guidance if g.effect != "continue"]
    summary = (
        f"{len(active_effects)} jurati-labeled PR(s) may affect this plan."
        if active_effects
        else f"{len(guidance)} jurati-labeled PR(s) noted; none affect current targets."
    )

    return {
        "status": "ok",
        "summary": summary,
        "guidance": [_format_guidance(g) for g in guidance],
        "privacy_boundary": _privacy_boundary(),
    }


def _privacy_boundary() -> list[str]:
    return [
        "only configured repos are checked",
        "only PRs carrying the configured jurati label are used",
        "unlabeled PRs, comments, chats, editor activity, and read activity are not mined",
    ]


def _build_search_results(
    index: Index,
    query: str,
    *,
    now: datetime,
    repo: str | None = None,
    max_results: int = 10,
    entry_type: EntryType | None = None,
    project: str | None = None,
    include_expired: bool = False,
    prebuilt_index: InvertedIndex | None = None,
) -> list[dict[str, Any]]:
    entries = index.list_entries(
        now=now,
        entry_type=entry_type,
        project=project,
        include_expired=include_expired,
    )
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
        "reason": item.reason,
        "next_step": item.next_step,
    }


def _format_hygiene_report(report: HygieneReport) -> dict[str, Any]:
    return {
        "summary": {
            "expired_active": len(report.expired_active),
            "stale_proposed": len(report.stale_proposed),
            "supersession": len(report.supersession),
            "stale_after_days": report.stale_after_days,
        },
        "expired_active": [_format_hygiene_item(item) for item in report.expired_active],
        "stale_proposed": [_format_hygiene_item(item) for item in report.stale_proposed],
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


_DEVELOPER_RESPONSE_INSTRUCTION = (
    "For developer-facing replies, use developer_confirmation or write one "
    "equivalent sentence about the work. Unless debugging was explicitly "
    "requested, do not mention entry IDs, ref paths, expiry mechanics, branch "
    "names, knowledge repo lifecycle, sync, or PR chores."
)

_DEBUG_ONLY_FIELDS = [
    "entry_id",
    "active_ref",
    "branch",
    "pr_url",
    "pr_number",
    "review_url",
    "commit",
]

_WRITE_PATH_GUIDANCE = (
    "Translate the developer's normal request into the right write path. Do not "
    "ask them to choose between record() and propose() or to name entry levels."
)


def _agent_guidance(default_reply: str) -> dict[str, Any]:
    return {
        "default_reply": default_reply,
        "developer_reply": _DEVELOPER_RESPONSE_INSTRUCTION,
        "debug_only_fields": _DEBUG_ONLY_FIELDS,
    }


def _write_path_error(
    *,
    message: str,
    correction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": message,
        "agent_guidance": {
            "write_path": _WRITE_PATH_GUIDANCE,
            "request_mapping": _write_request_examples(),
        },
    }
    if correction is not None:
        payload["suggested_write_path"] = correction
    return payload


def _record_correction(
    *,
    entry_type: EntryType,
    level: EscalationLevel | None,
    title: str,
    content: str,
    entry_id: str,
    projects: list[str] | None,
    tags: list[str] | None,
    visibility: Visibility | None,
) -> dict[str, Any] | None:
    if entry_type in (EntryType.DECISION, EntryType.WORKFLOW, EntryType.PRINCIPLE) or level in (
        EscalationLevel.L2,
        EscalationLevel.L3,
    ):
        return {
            "tool": "propose",
            "arguments": {
                "type": str(entry_type),
                "title": title,
                "content": content,
                "entry_id": entry_id,
                "level": str(level) if level is not None else None,
                "projects": projects or [],
                "tags": tags or [],
                "visibility": str(visibility) if visibility is not None else None,
            },
            "why": "durable decisions, workflows, and principles go through the reviewed path",
        }
    return None


def _propose_correction(
    *,
    entry_type: EntryType,
    level: EscalationLevel | None,
    title: str,
    content: str,
    entry_id: str,
    projects: list[str] | None,
    tags: list[str] | None,
    visibility: Visibility | None,
) -> dict[str, Any] | None:
    if entry_type == EntryType.ACTIVE or level in (EscalationLevel.L0, EscalationLevel.L1):
        return {
            "tool": "record",
            "arguments": {
                "type": str(entry_type),
                "title": title,
                "content": content,
                "entry_id": entry_id,
                "level": str(level) if level is not None else None,
                "projects": projects or [],
                "tags": tags or [],
                "visibility": str(visibility) if visibility is not None else None,
            },
            "why": (
                "short-lived handoffs and lightweight project updates belong on the record path"
            ),
        }
    return None


def _write_receipt(
    *,
    entry_id: str,
    write_mode: str,
    commit: str | None = None,
    branch: str | None = None,
    active_ref: str | None = None,
    pr_url: str | None = None,
    pr_number: int | None = None,
) -> dict[str, Any]:
    if write_mode == "active_ref":
        confirmation = "Recorded the current work update."
        return {
            "developer_confirmation": confirmation,
            "agent_guidance": _agent_guidance(confirmation),
            "what_happened": confirmation,
            "visibility": "Current work context was captured.",
            "next_step": "No developer action needed.",
            "active_ref": active_ref,
            "commit": commit,
        }

    if write_mode == "lightweight_pr":
        confirmation = "Recorded the project update."
        return {
            "developer_confirmation": confirmation,
            "agent_guidance": _agent_guidance(confirmation),
            "what_happened": confirmation,
            "visibility": "The update is queued for normal review.",
            "next_step": "No developer action needed.",
            "branch": branch,
            "pr_url": pr_url,
            "pr_number": pr_number,
            "commit": commit,
        }

    if write_mode == "branch_only":
        confirmation = "Saved the update for review."
        return {
            "developer_confirmation": confirmation,
            "agent_guidance": _agent_guidance(confirmation),
            "what_happened": confirmation,
            "visibility": "The update is queued for normal review.",
            "next_step": "No developer action needed.",
            "branch": branch,
            "review_url": pr_url,
            "commit": commit,
        }

    confirmation = "Submitted the update for team review."
    return {
        "developer_confirmation": confirmation,
        "agent_guidance": _agent_guidance(confirmation),
        "what_happened": confirmation,
        "visibility": "The update is queued for team review.",
        "next_step": "No developer action needed.",
        "branch": branch,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "commit": commit,
    }


def _expire_receipt(
    *,
    entry_id: str,
    write_mode: str,
    commit: str | None = None,
    branch: str | None = None,
    active_ref: str | None = None,
    pr_url: str | None = None,
    pr_number: int | None = None,
) -> dict[str, Any]:
    if write_mode == "active_ref":
        confirmation = "Cleared the stale context."
        return {
            "developer_confirmation": confirmation,
            "agent_guidance": _agent_guidance(confirmation),
            "what_happened": confirmation,
            "visibility": "The stale context was removed from the current view.",
            "next_step": "No developer action needed.",
            "active_ref": active_ref,
            "commit": commit,
        }

    if write_mode == "branch_only":
        confirmation = "Submitted the cleanup for review."
        return {
            "developer_confirmation": confirmation,
            "agent_guidance": _agent_guidance(confirmation),
            "what_happened": confirmation,
            "visibility": "The cleanup is queued for normal review.",
            "next_step": "No developer action needed.",
            "branch": branch,
            "review_url": pr_url,
            "commit": commit,
        }

    confirmation = "Submitted the cleanup for review."
    return {
        "developer_confirmation": confirmation,
        "agent_guidance": _agent_guidance(confirmation),
        "what_happened": confirmation,
        "visibility": "The cleanup is queued for team review.",
        "next_step": "No developer action needed.",
        "branch": branch,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "commit": commit,
    }


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


@mcp.tool()
async def query(
    topic: str,
    ctx: Context[Any, Any],
    type: str | None = None,
    project: str | None = None,
    status: str | None = None,
    include_expired: bool = False,
) -> list[dict[str, Any]]:
    """Search knowledge entries by topic. Returns matching entries ranked by relevance."""
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
        return [_format_result(r) for r in results]

    fallback = _build_search_results(
        state.index,
        topic,
        now=now,
        entry_type=entry_type,
        project=project,
        include_expired=include_expired,
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


@mcp.tool()
async def context(
    ctx: Context[Any, Any],
    repo: str | None = None,
    goal: str | None = None,
    paths: list[str] | None = None,
    include_pr_signals: bool = True,
) -> dict[str, Any]:
    """Get session-start context: active entries, recent decisions, and repo-relevant items.

    Call this BEFORE starting any task. Summarize what you learn in 2-3 sentences
    for the developer — focus on what's relevant to their goal. Never surface entry
    IDs, ref paths, or expiry dates. You may cite authorship (who wrote an entry)
    since that's git provenance, but never predict or report who has or hasn't read
    something. If coordination signals indicate a blocker or dependency, state it
    plainly (e.g., "Alice's auth PR needs to land first")."""
    state = _state(ctx)
    now = datetime.now(UTC)

    coordination: dict[str, Any] | None = None
    if include_pr_signals and state.config.pr_signals.repos:
        coordination = await _build_coordination(state, repo=repo, goal=goal, paths=paths, now=now)

    return _build_context_payload(state.index, now=now, repo=repo, coordination=coordination)


@mcp.tool()
async def search(
    query: str,
    ctx: Context[Any, Any],
    type: str | None = None,
    project: str | None = None,
    tags: str | None = None,
    max_results: int = 10,
    include_expired: bool = False,
) -> list[dict[str, Any]]:
    """Search knowledge entries with BM25 relevance ranking."""
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
        include_expired=include_expired,
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

    if not include_expired:
        now = datetime.now(UTC)
        if entry.frontmatter.expires_at is not None and now >= entry.frontmatter.expires_at:
            return {"error": f"Entry {id!r} is expired"}

    graph = build_entry_graph(state.index)
    return _format_entry(entry, graph=graph)


@mcp.tool()
async def list_entries(
    ctx: Context[Any, Any],
    type: str | None = None,
    project: str | None = None,
    status: str | None = None,
    include_expired: bool = False,
) -> list[dict[str, Any]]:
    """List knowledge entries with optional filters."""
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
    return [_format_entry(e) for e in entries]


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
        state._cached_bm25_index = None
        state._index_generation += 1
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
            "health": _health_dict(state.sync_health),
        }


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
    """Record an L0/L1 knowledge entry. L0 pushes via active ref, L1 creates a lightweight PR.

    Use this when the developer asks for a handoff, current focus, breaking
    change note, or project update. If they ask to save something as a team
    decision or workflow, translate that request to propose() instead of asking
    them to choose the API.

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
            "error": ("Active context is disabled. Set JURATI_ACTIVE_REFS_ENABLED=true to opt in.")
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

    if intent.write_mode == "active_ref":
        sha = await _run_blocking(
            lambda: _do_active_record(state.write_lock, state.repo_path, intent, config.main_branch)
        )
        if intent.entry is not None:
            state.index.add(intent.entry)
        return {
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

    if intent.branch is None:
        return {"error": "branch must not be None for L1 record"}

    sha, pr_result, new_cached = await _run_blocking(
        lambda: _finish_pr_write(
            state.write_lock,
            state.repo_path,
            intent,
            title=f"feat(kb): add {eid}",
            body=f"Add {entry_type} entry: {title}",
            labels=["jurati", "low-ceremony"],
            base=config.main_branch,
            remote_url=config.remote_url,
            cached_candidate=state.cached_pr_candidate,
        )
    )
    if new_cached is not None:
        state.cached_pr_candidate = new_cached

    write_mode = "lightweight_pr" if pr_result.kind == "pr" else "branch_only"
    return {
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

    sha, pr_result, new_cached = await _run_blocking(
        lambda: _finish_pr_write(
            state.write_lock,
            state.repo_path,
            intent,
            title=f"feat(kb): propose {eid}",
            body=f"Propose {entry_type} entry: {title}",
            labels=["jurati", "review-required"],
            base=config.main_branch,
            remote_url=config.remote_url,
            cached_candidate=state.cached_pr_candidate,
        )
    )
    if new_cached is not None:
        state.cached_pr_candidate = new_cached

    write_mode = "review_pr" if pr_result.kind == "pr" else "branch_only"
    return {
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

    intent = plan_expire(entry)

    if intent.write_mode == "active_ref":
        ref_path = f"{config.active_ref_prefix}/{config.client_slug}/{id}"
        await _run_blocking(lambda: _do_active_expire(state.write_lock, state.repo_path, ref_path))
        state.index.remove(id)
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
