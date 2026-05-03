"""End-to-end smoke over MCP tool handlers with a local git remote."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import anyio
import git

from jurati.git.config import JuratiConfig
from jurati.git.pr import PRResult
from jurati.git.repo import ensure_repo, fetch_all, load_index_from_repo
from jurati.server import (
    ServerState,
    SyncHealth,
    expire,
    explain,
    propose,
    query,
    record,
    status,
    sync,
)

SAMPLE_DECISION = """\
---
schema_version: 1
id: use-ruff
title: Use Ruff for linting
type: decision
level: L2
status: active
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
expires_at: null
projects: []
tags: [tooling]
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: "https://github.com/example/repo/pull/1"
---

We use Ruff for all Python linting and formatting.
"""


class _FakeCtx:
    def __init__(self, state: ServerState) -> None:
        self.request_context = type("RC", (), {"lifespan_context": state})()


def _commit_file(repo: git.Repo, path: str, content: str, message: str) -> None:
    full_path = Path(repo.working_dir) / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    repo.index.add([path])
    repo.index.commit(message)


def _configure_identity(repo: git.Repo) -> None:
    with repo.config_writer() as writer:
        writer.set_value("user", "name", "Jurati Smoke")
        writer.set_value("user", "email", "jurati-smoke@example.com")


def _build_local_remote(tmp_path: Path) -> git.Repo:
    bare = git.Repo.init(tmp_path / "remote.git", bare=True)
    work = git.Repo.init(tmp_path / "seed")
    _configure_identity(work)
    work.create_remote("origin", str(bare.common_dir))
    _commit_file(work, "decisions/use-ruff.md", SAMPLE_DECISION, "add decision")
    work.remotes.origin.push("HEAD:refs/heads/main")
    return bare


def _build_state(remote: git.Repo, cache_dir: Path) -> ServerState:
    remote_url = str(remote.common_dir)
    repo_path = ensure_repo(remote_url, str(cache_dir))
    repo = git.Repo(repo_path)
    _configure_identity(repo)
    fetch_all(repo_path)
    return ServerState(
        config=JuratiConfig(
            remote_url=remote_url,
            cache_dir=str(cache_dir),
            client_slug="smoke-client",
        ),
        repo_path=repo_path,
        index=load_index_from_repo(repo_path),
        last_sync=datetime.now(UTC),
        sync_health=SyncHealth(last_success=datetime.now(UTC)),
    )


def test_local_mcp_tool_smoke(tmp_path: Path) -> None:
    remote = _build_local_remote(tmp_path)
    state = _build_state(remote, tmp_path / "cache")
    ctx = _FakeCtx(state)

    async def run() -> None:
        explanation = await explain()
        assert "shared team memory" in explanation["summary"]

        status_payload = await status(ctx=ctx)
        assert status_payload["knowledge_remote"] == str(remote.common_dir)
        assert status_payload["entries_indexed"] == 1

        query_results = await query(topic="ruff", ctx=ctx)
        assert query_results[0]["id"] == "use-ruff"
        assert query_results[0]["match"]["reasons"]

        active = await record(
            type="active",
            title="Smoke handoff",
            content="handoff context from local smoke test",
            ctx=ctx,
            entry_id="smoke-handoff",
            tags=["handoff"],
            expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        )
        assert active["status"] == "ok"
        assert active["write_mode"] == "active_ref"
        assert active["active_ref"] == (
            "refs/heads/jurati/active/smoke-client/smoke-handoff"
        )

        synced = await sync(ctx=ctx)
        assert synced["status"] == "ok"
        assert state.index.get("smoke-handoff") is not None

        with patch(
            "jurati.server.create_review_pr",
            return_value=PRResult(
                url="https://example.com/pull/42",
                number=42,
                branch="jurati/smoke-decision",
            ),
        ):
            proposed = await propose(
                type="decision",
                title="Smoke decision",
                content="Durable smoke decision.",
                ctx=ctx,
                entry_id="smoke-decision",
            )
        assert proposed["status"] == "ok"
        assert proposed["write_mode"] == "review_pr"
        assert proposed["pr_number"] == 42

        expired = await expire(id="smoke-handoff", ctx=ctx)
        assert expired["status"] == "ok"
        assert expired["write_mode"] == "active_ref"
        assert state.index.get("smoke-handoff") is None

    anyio.run(run)
