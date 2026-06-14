# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for the MCP promote tool (labeled source artifact -> durable knowledge)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from ambara.core.content_policy import WritePolicy
from ambara.core.content_policy_config import default_config
from ambara.core.index import Index
from ambara.core.pr_signals import PRSignal
from ambara.git.config import AmbaraConfig
from ambara.git.remember import RememberOutcome
from ambara.server import promote
from ambara.server_state import ServerState, SyncHealth
from tests._source_report import source_report_for_signals

NOW = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
ARTIFACT_ID = "github:org/api:pull:42"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _signal(number: int = 42, **overrides: object) -> PRSignal:
    defaults: dict[str, object] = {
        "signal_id": f"github:org/api:pull:{number}",
        "provider": "github",
        "repo": "org/api",
        "number": number,
        "url": f"https://github.com/org/api/pull/{number}",
        "title": "Adopt gRPC for service calls",
        "body_excerpt": "The team agreed to standardize service-to-service calls on gRPC.",
        "author": "tony",
        "state": "open",
        "labels": ("ambara",),
        "created_at": NOW - timedelta(days=2),
        "updated_at": NOW - timedelta(hours=6),
        "merged_at": None,
        "changed_paths": ("src/api/grpc.py",),
        "target_areas": ("src/api",),
    }
    defaults.update(overrides)
    return PRSignal(**defaults)  # type: ignore[arg-type]


def _state(*signals: PRSignal) -> ServerState:
    state = ServerState(
        config=AmbaraConfig(remote_url="https://example.com/repo.git"),
        repo_path="/fake/repo",
        index=Index(),
        last_sync=NOW,
        sync_health=SyncHealth(last_success=NOW),
        content_policy=WritePolicy(default_config()),
    )
    if signals:
        state.source_report = source_report_for_signals(*signals, now=NOW)
    return state


class _FakeCtx:
    def __init__(self, state: ServerState) -> None:
        self.request_context = type("RC", (), {"lifespan_context": state})()


@pytest.mark.anyio()
async def test_promote_dry_run_returns_plan_without_writing() -> None:
    ctx = _FakeCtx(_state(_signal()))

    with patch("ambara.server_promote.materialize_remember") as m_materialize:
        result = await promote(artifact_id=ARTIFACT_ID, ctx=ctx)

    assert result["status"] == "dry_run"
    assert result["artifact_id"] == ARTIFACT_ID
    assert result["entry_id"]
    assert result["branch"] == f"ambara/promote/{result['entry_id']}"
    assert result["receipt"]["action"] == "create"
    m_materialize.assert_not_called()


@pytest.mark.anyio()
async def test_promote_apply_materializes_review_branch() -> None:
    ctx = _FakeCtx(_state(_signal()))
    outcome = RememberOutcome(
        entry_id="github-42",
        branch="ambara/promote/github-42",
        sha="deadbeef",
        reused_existing=False,
        receipt={"action": "create", "branch": "ambara/promote/github-42", "sha": "deadbeef"},
    )

    with (
        patch("ambara.server_promote.fetch_main"),
        patch("ambara.server_promote.materialize_remember", return_value=outcome) as m_materialize,
    ):
        result = await promote(artifact_id=ARTIFACT_ID, ctx=ctx, dry_run=False)

    assert result["status"] == "ok"
    assert result["branch"] == "ambara/promote/github-42"
    assert result["sha"] == "deadbeef"
    assert result["reused_existing"] is False
    m_materialize.assert_called_once()
    # Materialized against the configured repo + main branch.
    args, kwargs = m_materialize.call_args
    assert args[0] == "/fake/repo"
    assert kwargs["main_branch"] == "main"


@pytest.mark.anyio()
async def test_promote_unknown_artifact_returns_error() -> None:
    ctx = _FakeCtx(_state(_signal()))

    with patch("ambara.server_promote.materialize_remember") as m_materialize:
        result = await promote(artifact_id="github:org/api:pull:999", ctx=ctx, dry_run=False)

    assert result["error"] == "artifact_not_found"
    assert result["artifact_id"] == "github:org/api:pull:999"
    m_materialize.assert_not_called()


@pytest.mark.anyio()
async def test_promote_rejects_blocked_content_and_never_writes() -> None:
    leaky = _signal(body_excerpt="-----BEGIN PRIVATE KEY-----")  # gitleaks:allow
    ctx = _FakeCtx(_state(leaky))

    with patch("ambara.server_promote.materialize_remember") as m_materialize:
        result = await promote(artifact_id=ARTIFACT_ID, ctx=ctx, dry_run=False)

    assert result["status"] == "rejected"
    assert result["reason"]
    m_materialize.assert_not_called()


@pytest.mark.anyio()
async def test_promote_defaults_type_to_project() -> None:
    ctx = _FakeCtx(_state(_signal()))

    with (
        patch("ambara.server_promote.fetch_main"),
        patch("ambara.server_promote.materialize_remember"),
    ):
        result = await promote(artifact_id=ARTIFACT_ID, ctx=ctx)

    assert result["entry_type"] == "project"


@pytest.mark.anyio()
async def test_promote_apply_fetches_main_before_materialize() -> None:
    """fetch_main must be called before materialize_remember on the apply path."""
    ctx = _FakeCtx(_state(_signal()))
    outcome = RememberOutcome(
        entry_id="github-42",
        branch="ambara/promote/github-42",
        sha="deadbeef",
        reused_existing=False,
        receipt={"action": "create", "branch": "ambara/promote/github-42", "sha": "deadbeef"},
    )

    calls: list[str] = []

    def _fake_fetch(repo_path: str, main_branch: str) -> None:
        calls.append("fetch")

    def _fake_materialize(*args: object, **kwargs: object) -> RememberOutcome:
        calls.append("materialize")
        return outcome

    with (
        patch("ambara.server_promote.fetch_main", side_effect=_fake_fetch),
        patch("ambara.server_promote.materialize_remember", side_effect=_fake_materialize),
    ):
        result = await promote(artifact_id=ARTIFACT_ID, ctx=ctx, dry_run=False)

    assert result["status"] == "ok"
    assert calls == ["fetch", "materialize"]
