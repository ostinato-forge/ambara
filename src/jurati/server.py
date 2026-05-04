"""MCP tool handlers — orchestration glue between core and git layers."""

from __future__ import annotations

import contextlib
import threading
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
from mcp.server.fastmcp import Context, FastMCP

from jurati.core.changes import ExpireIntent, WriteIntent, plan_expire, plan_propose, plan_record
from jurati.core.hygiene import HygieneItem, HygieneReport, summarize_lifecycle
from jurati.core.index import Index
from jurati.core.schema import Entry, EntryStatus, EntryType, EscalationLevel
from jurati.core.scoring import rank_entries
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
from jurati.git.pr import PRResult, create_pr
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo


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


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[ServerState]:
    config = load_config_from_env()
    repo_path = await anyio.to_thread.run_sync(
        lambda: ensure_repo(config.remote_url, config.cache_dir)
    )
    await anyio.to_thread.run_sync(
        lambda: fetch_all(repo_path, config.main_branch, config.active_ref_prefix)
    )
    index = await anyio.to_thread.run_sync(
        lambda: load_index_from_repo(repo_path, config.main_branch, config.active_ref_prefix)
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


mcp = FastMCP("jurati", lifespan=app_lifespan)


def _state(ctx: Context[Any, Any]) -> ServerState:
    return ctx.request_context.lifespan_context  # type: ignore[no-any-return]


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


def _format_entry(entry: Entry) -> dict[str, Any]:
    fm = entry.frontmatter
    return {
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


def _build_context_payload(
    index: Index,
    *,
    now: datetime,
    repo: str | None = None,
    days_recent: int = 7,
) -> dict[str, Any]:
    recent_cutoff = now - timedelta(days=days_recent)

    active = [
        _format_entry(e)
        for e in index.entries.values()
        if e.frontmatter.type == EntryType.ACTIVE and not is_expired(e, now)
    ]

    recent = [
        _format_entry(e)
        for e in index.entries.values()
        if e.frontmatter.type != EntryType.ACTIVE
        and e.frontmatter.updated_at >= recent_cutoff
        and e.frontmatter.status in (EntryStatus.ACTIVE, EntryStatus.PROPOSED)
    ]

    recent.sort(key=lambda r: r.get("updated_at", ""), reverse=True)

    return {"active": active, "recent": recent[:15]}


def _build_search_results(
    index: Index,
    query: str,
    *,
    now: datetime,
    repo: str | None = None,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    entries = list(index.entries.values())
    ranked = rank_entries(entries, query, now=now, repo=repo, max_results=max_results)
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
        "summary": "Jurati is shared team memory backed by a git knowledge repo.",
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
        return {
            "what_happened": "Recorded short-lived active context on a non-main active ref.",
            "visibility": (
                "Visible to Jurati after the active ref is fetched; not durable "
                "source-of-truth content on main."
            ),
            "next_step": f"Use expire(id={entry_id!r}) when the context is no longer useful.",
            "active_ref": active_ref,
            "commit": commit,
        }

    if write_mode == "lightweight_pr":
        return {
            "what_happened": "Created a lightweight project-context pull request.",
            "visibility": "Visible as a PR now; source-of-truth after merge to main.",
            "next_step": "Review or merge the PR, then run sync so agents see it from main.",
            "branch": branch,
            "pr_url": pr_url,
            "pr_number": pr_number,
            "commit": commit,
        }

    if write_mode == "branch_only":
        return {
            "what_happened": f"Pushed proposed knowledge branch {branch}.",
            "visibility": (
                "The branch is reviewable; source-of-truth content changes "
                "only after a PR is opened and merged into main."
            ),
            "next_step": "Open or review the branch and merge accepted content.",
            "branch": branch,
            "review_url": pr_url,
            "commit": commit,
        }

    return {
        "what_happened": "Created a reviewed knowledge pull request.",
        "visibility": "Visible as a PR now; source-of-truth only after review and merge.",
        "next_step": "Review the PR, merge it when accepted, then run sync.",
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
        return {
            "what_happened": "Expired active context by deleting its active ref.",
            "visibility": (
                "Removed from this server's current index; other clients stop seeing it "
                "after they sync."
            ),
            "next_step": "No review is needed for L0 active context.",
            "active_ref": active_ref,
            "commit": commit,
        }

    if write_mode == "branch_only":
        return {
            "what_happened": f"Pushed expiry branch {branch}.",
            "visibility": ("The branch is reviewable; source-of-truth changes only after merge."),
            "next_step": "Open or review the expiry branch and merge if accepted.",
            "branch": branch,
            "review_url": pr_url,
            "commit": commit,
        }

    return {
        "what_happened": "Created a pull request to expire durable knowledge.",
        "visibility": "Visible as a PR now; source-of-truth changes only after merge.",
        "next_step": "Review and merge the expiry PR, then run sync.",
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
    return _format_hygiene_report(report)


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
    entry_type = EntryType(type) if type else None
    entry_status = EntryStatus(status) if status else None

    results = core_query(
        state.index,
        topic,
        now=datetime.now(UTC),
        entry_type=entry_type,
        project=project,
        status=entry_status,
        include_expired=include_expired,
    )
    return [_format_result(r) for r in results]


@mcp.tool()
async def context(
    ctx: Context[Any, Any],
    repo: str | None = None,
) -> dict[str, Any]:
    """Get session-start context: active entries, recent decisions, and repo-relevant items."""
    state = _state(ctx)
    now = datetime.now(UTC)
    return _build_context_payload(state.index, now=now, repo=repo)


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
    return _build_search_results(state.index, query, now=now, max_results=max_results)


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

    return _format_entry(entry)


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
    entry_type = EntryType(type) if type else None
    entry_status = EntryStatus(status) if status else None

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
        return {"id": id, "valid": len(errors) == 0, "errors": errors}

    all_results = []
    for entry_id, entry in state.index.entries.items():
        errors = validate_entry(entry)
        all_results.append({"id": entry_id, "valid": len(errors) == 0, "errors": errors})
    return {"results": all_results}


@mcp.tool()
async def sync(ctx: Context[Any, Any]) -> dict[str, Any]:
    """Fetch latest changes from the knowledge repo and rebuild the index."""
    state = _state(ctx)
    config = state.config

    try:
        await anyio.to_thread.run_sync(
            lambda: fetch_all(state.repo_path, config.main_branch, config.active_ref_prefix)
        )
        new_index = await anyio.to_thread.run_sync(
            lambda: load_index_from_repo(
                state.repo_path, config.main_branch, config.active_ref_prefix
            )
        )
        state.index = new_index
        state.last_sync = datetime.now(UTC)
        state.sync_health.last_success = state.last_sync
        state.sync_health.consecutive_failures = 0
        state.sync_health.last_error = None
        return {
            "status": "ok",
            "what_happened": (
                "Fetched the source-of-truth branch and active refs, then rebuilt "
                "the in-memory index."
            ),
            "visibility": "No knowledge entries were written; this server's local index changed.",
            "entries": len(new_index.entries),
            "last_sync": state.last_sync.isoformat(),
            "health": _health_dict(state.sync_health),
        }
    except Exception as exc:
        now = datetime.now(UTC)
        state.sync_health.last_failure = now
        state.sync_health.last_error = str(exc)
        state.sync_health.consecutive_failures += 1
        return {
            "status": "error",
            "what_happened": "Sync failed; Jurati kept the last known readable index.",
            "error": str(exc),
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
) -> dict[str, Any]:
    """Record an L0/L1 knowledge entry. L0 pushes via active ref, L1 creates a lightweight PR."""
    state = _state(ctx)
    config = state.config
    now = datetime.now(UTC)
    eid = entry_id or _gen_entry_id()
    entry_type = EntryType(type)
    esc_level = EscalationLevel(level) if level else None
    exp = datetime.fromisoformat(expires_at) if expires_at else None

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
    )

    if intent.write_mode == "active_ref":
        sha = await anyio.to_thread.run_sync(
            lambda: _do_active_record(state.write_lock, state.repo_path, intent, config.main_branch)
        )
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
        raise ValueError("branch must not be None for L1 record")

    sha, pr_result, new_cached = await anyio.to_thread.run_sync(
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


def _do_active_record(lock: threading.Lock, repo_path: str, intent: Any, main_branch: str) -> str:
    with lock:
        create_branch(repo_path, intent.branch, f"origin/{main_branch}")
        sha = materialize_write(repo_path, intent)
        push_active_ref(repo_path, intent.branch, sha)
        cleanup_branch(repo_path, intent.branch, main_branch)
    return sha


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
            if isinstance(intent, ExpireIntent) and now is not None:
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
) -> dict[str, Any]:
    """Propose an L2/L3 knowledge entry. Creates a branch and review PR."""
    state = _state(ctx)
    config = state.config
    now = datetime.now(UTC)
    eid = entry_id or _gen_entry_id()
    entry_type = EntryType(type)
    esc_level = EscalationLevel(level) if level else None

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
    )

    if intent.branch is None:
        raise ValueError("branch must not be None for propose")

    sha, pr_result, new_cached = await anyio.to_thread.run_sync(
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
    """Expire an active knowledge entry. L0 deletes ref, L1+ creates a PR."""
    state = _state(ctx)
    config = state.config
    now = datetime.now(UTC)

    entry = state.index.get(id)
    if entry is None:
        return {"error": f"Entry {id!r} not found"}

    intent = plan_expire(entry)

    if intent.write_mode == "active_ref":
        ref_path = f"{config.active_ref_prefix}/{config.client_slug}/{id}"
        await anyio.to_thread.run_sync(lambda: delete_active_ref(state.repo_path, ref_path))
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
        raise ValueError("branch must not be None for non-L0 expire")

    sha, pr_result, new_cached = await anyio.to_thread.run_sync(
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
