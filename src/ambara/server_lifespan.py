"""MCP lifespan assembly for Ambara's server facade."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from ambara.core.content_policy import WritePolicy
from ambara.core.content_policy_config import default_config as default_policy
from ambara.core.index import Index
from ambara.git.config import AmbaraConfig
from ambara.server_index import _set_context_snapshot
from ambara.server_snapshot import refresh_context_snapshot
from ambara.server_state import ServerState, SyncHealth
from ambara.server_types import BlockingRunner, SignalFetcher


@asynccontextmanager
async def app_lifespan(
    _server: FastMCP,
    *,
    load_config: Callable[[], AmbaraConfig],
    ensure_repo_fn: Callable[[str, str], str],
    fetch_all_fn: Callable[..., Any],
    load_index_fn: Callable[..., Index],
    tree_hash_fn: Callable[[str, str], str],
    fetch_signals: SignalFetcher,
    run_blocking: BlockingRunner,
    logger: logging.Logger,
) -> AsyncIterator[ServerState]:
    config = load_config()
    if config.disabled:
        now = datetime.now(UTC)
        policy_config = default_policy()
        policy = WritePolicy(policy_config)
        yield ServerState(
            config=config,
            repo_path="",
            index=Index(),
            last_sync=now,
            sync_health=SyncHealth(last_error="Ambara disabled for this project."),
            content_policy=policy,
            content_policy_config=policy_config,
        )
        return

    repo_path = await run_blocking(lambda: ensure_repo_fn(config.remote_url, config.cache_dir))
    await run_blocking(
        lambda: fetch_all_fn(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
    )
    index = await run_blocking(
        lambda: load_index_fn(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
    )
    tree_hash = await run_blocking(lambda: tree_hash_fn(repo_path, config.main_branch))
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
        _index_tree_hash=tree_hash,
        _last_fetch_at=now,
    )
    snapshot = await refresh_context_snapshot(
        state,
        now=now,
        fetch_signals=fetch_signals,
        run_blocking=run_blocking,
        logger=logger,
    )
    _set_context_snapshot(state, snapshot)
    yield state
