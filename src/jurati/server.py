"""MCP tool handlers — orchestration glue between core and git layers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import anyio
from mcp.server.fastmcp import Context, FastMCP

from jurati.core.changes import plan_expire, plan_propose, plan_record
from jurati.core.index import Index
from jurati.core.schema import Entry, EntryStatus, EntryType, EscalationLevel
from jurati.core.search import SearchResult
from jurati.core.search import query as core_query
from jurati.core.validate import validate_entry
from jurati.git.branch import (
    cleanup_branch,
    create_branch,
    delete_active_ref,
    push_active_ref,
    push_branch,
)
from jurati.git.commit import materialize_expire, materialize_write
from jurati.git.config import JuratiConfig, load_config_from_env
from jurati.git.pr import create_lightweight_pr, create_review_pr
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo


@dataclass
class ServerState:
    config: JuratiConfig
    repo_path: str
    index: Index
    last_sync: datetime


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
        lambda: load_index_from_repo(
            repo_path, config.main_branch, config.active_ref_prefix
        )
    )
    now = datetime.now(UTC)
    yield ServerState(config=config, repo_path=repo_path, index=index, last_sync=now)


mcp = FastMCP("jurati", lifespan=app_lifespan)


def _state(ctx: Context[Any, Any]) -> ServerState:
    return ctx.request_context.lifespan_context  # type: ignore[no-any-return]


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


def _format_result(result: SearchResult) -> dict[str, Any]:
    out = _format_entry(result.entry)
    out["relevance"] = result.relevance
    return out


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
        entry_type=entry_type,
        project=project,
        status=entry_status,
        include_expired=include_expired,
    )
    return [_format_result(r) for r in results]


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
        if (
            entry.frontmatter.expires_at is not None
            and now >= entry.frontmatter.expires_at
        ):
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
        all_results.append(
            {"id": entry_id, "valid": len(errors) == 0, "errors": errors}
        )
    return {"results": all_results}


@mcp.tool()
async def sync(ctx: Context[Any, Any]) -> dict[str, Any]:
    """Fetch latest changes from the knowledge repo and rebuild the index."""
    state = _state(ctx)
    config = state.config

    try:
        await anyio.to_thread.run_sync(
            lambda: fetch_all(
                state.repo_path, config.main_branch, config.active_ref_prefix
            )
        )
        new_index = await anyio.to_thread.run_sync(
            lambda: load_index_from_repo(
                state.repo_path, config.main_branch, config.active_ref_prefix
            )
        )
        state.index = new_index
        state.last_sync = datetime.now(UTC)
        return {
            "status": "ok",
            "entries": len(new_index.entries),
            "last_sync": state.last_sync.isoformat(),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _gen_entry_id() -> str:
    import uuid

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
            lambda: _do_active_record(state.repo_path, intent, config.main_branch)
        )
        return {
            "status": "ok",
            "entry_id": eid,
            "write_mode": "active_ref",
            "commit": sha,
        }

    assert intent.branch is not None
    branch = intent.branch
    sha = await anyio.to_thread.run_sync(
        lambda: _do_branch_record(state.repo_path, intent, config.main_branch)
    )
    pr = await anyio.to_thread.run_sync(
        lambda: create_lightweight_pr(
            state.repo_path,
            branch,
            f"feat(kb): add {eid}",
            f"Add {entry_type} entry: {title}",
            base=config.main_branch,
        )
    )
    await anyio.to_thread.run_sync(
        lambda: cleanup_branch(state.repo_path, branch, config.main_branch)
    )
    return {
        "status": "ok",
        "entry_id": eid,
        "write_mode": "lightweight_pr",
        "commit": sha,
        "pr_url": pr.url,
        "pr_number": pr.number,
    }


def _do_active_record(repo_path: str, intent: Any, main_branch: str) -> str:
    create_branch(repo_path, intent.branch, f"origin/{main_branch}")
    sha = materialize_write(repo_path, intent)
    push_active_ref(repo_path, intent.branch, sha)
    cleanup_branch(repo_path, intent.branch, main_branch)
    return sha


def _do_branch_record(repo_path: str, intent: Any, main_branch: str) -> str:
    create_branch(repo_path, intent.branch, f"origin/{main_branch}")
    sha = materialize_write(repo_path, intent)
    push_branch(repo_path, intent.branch)
    return sha


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

    assert intent.branch is not None
    branch = intent.branch
    sha = await anyio.to_thread.run_sync(
        lambda: _do_branch_record(state.repo_path, intent, config.main_branch)
    )
    pr = await anyio.to_thread.run_sync(
        lambda: create_review_pr(
            state.repo_path,
            branch,
            f"feat(kb): propose {eid}",
            f"Propose {entry_type} entry: {title}",
            base=config.main_branch,
        )
    )
    await anyio.to_thread.run_sync(
        lambda: cleanup_branch(state.repo_path, branch, config.main_branch)
    )
    return {
        "status": "ok",
        "entry_id": eid,
        "write_mode": "review_pr",
        "commit": sha,
        "pr_url": pr.url,
        "pr_number": pr.number,
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

    intent = plan_expire(entry, now=now)

    if intent.write_mode == "active_ref":
        ref_path = f"{config.active_ref_prefix}/{config.client_slug}/{id}"
        await anyio.to_thread.run_sync(
            lambda: delete_active_ref(state.repo_path, ref_path)
        )
        state.index.remove(id)
        return {"status": "ok", "entry_id": id, "write_mode": "active_ref"}

    branch = intent.branch
    assert branch is not None

    sha = await anyio.to_thread.run_sync(
        lambda: _do_expire_branch(
            state.repo_path, intent, entry, now, config.main_branch
        )
    )
    pr = await anyio.to_thread.run_sync(
        lambda: create_review_pr(
            state.repo_path,
            branch,
            f"chore(kb): expire {id}",
            reason or f"Expire entry: {entry.frontmatter.title}",
            base=config.main_branch,
        )
    )
    await anyio.to_thread.run_sync(
        lambda: cleanup_branch(state.repo_path, branch, config.main_branch)
    )
    return {
        "status": "ok",
        "entry_id": id,
        "write_mode": intent.write_mode,
        "commit": sha,
        "pr_url": pr.url,
        "pr_number": pr.number,
    }


def _do_expire_branch(
    repo_path: str,
    intent: Any,
    entry: Entry,
    now: datetime,
    main_branch: str,
) -> str:
    assert intent.branch is not None
    create_branch(repo_path, intent.branch, f"origin/{main_branch}")
    sha = materialize_expire(repo_path, intent, entry, now)
    push_branch(repo_path, intent.branch)
    return sha
