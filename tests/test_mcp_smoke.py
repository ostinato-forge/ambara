"""End-to-end smoke over MCP tool handlers with a local git remote."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import anyio
import git
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ambara.git.config import AmbaraConfig, PRSignalsConfig
from ambara.git.pr import PRResult
from ambara.git.repo import ensure_repo, fetch_all, load_index_from_repo
from ambara.server import (
    ServerState,
    SyncHealth,
    context,
    expire,
    explain,
    propose,
    query,
    record,
    startup,
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
        writer.set_value("user", "name", "Ambara Smoke")
        writer.set_value("user", "email", "ambara-smoke@example.com")


def _build_local_remote(tmp_path: Path) -> git.Repo:
    bare = git.Repo.init(tmp_path / "remote.git", bare=True)
    work = git.Repo.init(tmp_path / "seed")
    _configure_identity(work)
    work.create_remote("origin", str(bare.common_dir))
    _commit_file(work, "decisions/use-ruff.md", SAMPLE_DECISION, "add decision")
    work.remotes.origin.push("HEAD:refs/heads/main")
    return bare


def _write_signal_fixture(tmp_path: Path) -> Path:
    fixture = tmp_path / "signals.json"
    fixture.write_text(
        json.dumps(
            {
                "signals": [
                    {
                        "repo": "org/api",
                        "number": 42,
                        "url": "https://github.com/org/api/pull/42",
                        "title": "Smoke handoff blocker",
                        "body_excerpt": "Provider excerpt must stay out of compiler packets.",
                        "author": "alice",
                        "state": "open",
                        "labels": ["ambara"],
                        "created_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                        "updated_at": datetime.now(UTC).isoformat(),
                        "changed_paths": ["active/smoke-handoff.md"],
                    }
                ]
            }
        )
        + "\n"
    )
    return fixture


def _build_state(
    remote: git.Repo,
    cache_dir: Path,
    *,
    signal_fixture: Path | None = None,
) -> ServerState:
    remote_url = str(remote.common_dir)
    repo_path = ensure_repo(remote_url, str(cache_dir))
    repo = git.Repo(repo_path)
    _configure_identity(repo)
    fetch_all(repo_path, active_refs_enabled=True)
    return ServerState(
        config=AmbaraConfig(
            remote_url=remote_url,
            cache_dir=str(cache_dir),
            client_slug="smoke-client",
            active_refs_enabled=True,
            pr_signals=PRSignalsConfig(
                repos=("org/api",),
                fixture_path=str(signal_fixture) if signal_fixture else None,
            ),
        ),
        repo_path=repo_path,
        index=load_index_from_repo(repo_path, active_refs_enabled=True),
        last_sync=datetime.now(UTC),
        sync_health=SyncHealth(last_success=datetime.now(UTC)),
    )


def test_local_mcp_tool_smoke(tmp_path: Path) -> None:
    remote = _build_local_remote(tmp_path)
    signal_fixture = _write_signal_fixture(tmp_path)
    state = _build_state(remote, tmp_path / "cache", signal_fixture=signal_fixture)
    ctx = _FakeCtx(state)

    async def run() -> None:
        explanation = await explain()
        assert "shared agent context" in explanation["summary"]

        status_payload = await status(ctx=ctx)
        assert status_payload["knowledge_remote"] == str(remote.common_dir)
        assert status_payload["entries_indexed"] == 1

        query_results = await query(topic="ruff", ctx=ctx)
        assert query_results[0]["id"] == "use-ruff"
        assert query_results[0]["match"]["reasons"]

        active = await record(
            type="active",
            title="Smoke handoff",
            content=(
                "Smoke handoff summary.\n\n"
                "Raw implementation detail from local smoke test must stay out of compiler packets."
            ),
            ctx=ctx,
            entry_id="smoke-handoff",
            tags=["handoff"],
            expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        )
        assert active["status"] == "ok"
        assert active["write_mode"] == "active_ref"
        assert active["active_ref"] == ("refs/heads/ambara/active/smoke-client/smoke-handoff")

        synced = await sync(ctx=ctx)
        assert synced["status"] == "ok"
        assert state.index.get("smoke-handoff") is not None
        assert state.cache.snapshot is not None

        compiler_packet = await context(
            ctx=ctx,
            repo="org/api",
            goal="smoke handoff",
            paths=["active/smoke-handoff.md"],
            mode="compiler",
        )
        assert compiler_packet["context_schema"] == "compiler-v1"
        assert compiler_packet["verdict"] == "blocked"
        assert compiler_packet["planning_action"] == "pause"
        assert compiler_packet["coverage"]["signals_considered"] == 1
        assert compiler_packet["coverage"]["snapshot_index_generation"] == state.cache.generation
        assert all("body" not in entry for entry in compiler_packet["relevant_entries"])
        assert "Raw implementation detail from local smoke test" not in str(compiler_packet)
        assert "Provider excerpt must stay out" not in str(compiler_packet)

        correction = await record(
            type="decision",
            title="Token rotation approach",
            content="Promote the active auth handoff into a reviewed decision.",
            ctx=ctx,
            entry_id="token-rotation-approach",
        )
        assert "suggested_write_path" in correction
        assert correction["suggested_write_path"]["tool"] == "propose"
        assert correction["suggested_write_path"]["arguments"]["type"] == "decision"

        with patch(
            "ambara.server.create_pr",
            return_value=(
                PRResult(
                    url="https://example.com/pull/42",
                    number=42,
                    branch="ambara/smoke-decision",
                    kind="pr",
                ),
                None,
            ),
        ):
            proposed = await propose(
                type="decision",
                title="Token rotation approach",
                content="Promote the active auth handoff into a reviewed decision.",
                ctx=ctx,
                entry_id="token-rotation-approach",
            )
        assert proposed["status"] == "ok"
        assert proposed["write_mode"] == "review_pr"
        assert proposed["pr_number"] == 42
        assert proposed["developer_confirmation"] == "Submitted the update for team review."
        assert "branch" not in proposed["developer_confirmation"].lower()
        assert "ambara" not in proposed["developer_confirmation"].lower()

        expired = await expire(id="smoke-handoff", ctx=ctx)
        assert expired["status"] == "ok"
        assert expired["write_mode"] == "active_ref"
        assert state.index.get("smoke-handoff") is None

    anyio.run(run)


def test_startup_returns_s2_packet(tmp_path: Path) -> None:
    remote = _build_local_remote(tmp_path)
    signal_fixture = _write_signal_fixture(tmp_path)
    state = _build_state(remote, tmp_path / "cache", signal_fixture=signal_fixture)
    ctx = _FakeCtx(state)

    async def run() -> None:
        packet = await startup(ctx=ctx, goal="ruff linting")
        assert packet["v"] == "s2"
        assert packet["availability"] in ("fresh", "acceptable")
        assert packet["action"] in (
            "proceed",
            "revise_plan_before_acting",
            "pause",
            "read_or_verify_before_acting",
        )
        assert "coordination" in packet
        entries = packet.get("entries", [])
        assert all("why" in e for e in entries)
        assert all("body" not in e for e in entries)
        assert '"body"' not in json.dumps(packet)

    anyio.run(run)


def test_startup_sync_failure_returns_unavailable(tmp_path: Path) -> None:
    remote = _build_local_remote(tmp_path)
    state = _build_state(remote, tmp_path / "cache")
    ctx = _FakeCtx(state)

    async def run() -> None:
        with patch(
            "ambara.server.fetch_all",
            side_effect=RuntimeError("connection refused"),
        ):
            packet = await startup(ctx=ctx, repo="org/api", goal="smoke test")
        assert packet["v"] == "s2"
        assert packet["availability"] == "unavailable"
        assert packet["action"] == "stop_context_unavailable"
        assert "reason" in packet

    anyio.run(run)


def test_startup_then_read_works(tmp_path: Path) -> None:
    from ambara.server import read_many

    remote = _build_local_remote(tmp_path)
    state = _build_state(remote, tmp_path / "cache")
    ctx = _FakeCtx(state)

    async def run() -> None:
        packet = await startup(ctx=ctx, goal="ruff linting")
        assert packet["v"] == "s2"
        entry_ids = [e["id"] for e in packet.get("entries", [])]
        if entry_ids:
            result = await read_many(ids=entry_ids[:1], ctx=ctx)
            assert result["entries"]
            assert result["entries"][0]["id"] == entry_ids[0]
            assert "body" in result["entries"][0]

    anyio.run(run)


def test_stdio_mcp_server_initializes_and_lists_tools(tmp_path: Path) -> None:
    remote = _build_local_remote(tmp_path)
    cache_dir = tmp_path / "stdio-cache"

    async def run() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from ambara.cli import main; main()", "serve"],
            env={
                "AMBARA_KNOWLEDGE_REMOTE": str(remote.common_dir),
                "AMBARA_CACHE_DIR": str(cache_dir),
                "AMBARA_CLIENT_SLUG": "stdio-smoke",
            },
        )
        with anyio.fail_after(10):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()

        tool_names = {tool.name for tool in tools.tools}
        assert {"sync", "context", "query", "record", "propose", "expire", "startup"} <= tool_names

    anyio.run(run)
