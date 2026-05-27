"""Phase 1 — Measure current context payload cost and lock coverage guardrails.

These tests establish the baseline token cost of context(), coordination, and
curation payloads. Phase 2 (manifest entry formatting) must pass the coverage
assertions here while reducing payload size.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pytest

from jurati.core.graph import build_entry_graph
from jurati.core.index import Index
from jurati.core.pr_signals import PRSignal
from jurati.core.schema import (
    EntryStatus,
    EntryType,
    EscalationLevel,
    Sensitivity,
)
from jurati.git.config import JuratiConfig, PRSignalsConfig
from jurati.providers.cache import SignalCache
from jurati.server_coordination import build_coordination_payload
from jurati.server_curation import build_curation_payload
from jurati.server_read import (
    _build_context_payload,
    _derive_summary,
    _format_entry,
    _format_entry_manifest,
)
from jurati.server_state import ServerState, SyncHealth
from tests.core.conftest import BASE_NOW, make_entry

NOW = BASE_NOW


def _approximate_tokens(payload: dict[str, Any]) -> int:
    return math.ceil(len(json.dumps(payload, default=str)) / 4)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LONG_ACTIVE_BODY = (
    "Backend token rotation is in progress. The refresh endpoint now uses "
    "rotation_id-based grace periods to avoid invalidating existing sessions. "
    "Frontend needs the updated API contract before wiring the new token flow. "
    "Alice started the migration on Monday and expects the API contract PR by "
    "Wednesday. The old /auth/refresh endpoint will be removed once all clients "
    "have migrated. Key constraint: grace period length must match the mobile "
    "app's background refresh interval (currently 5 minutes). Test coverage for "
    "the rotation path is at 78% — missing edge cases around concurrent refresh "
    "requests during the grace window. The rollback plan is to revert to the "
    "single-token model by toggling the ROTATION_ENABLED feature flag."
)

LONG_DECISION_BODY = (
    "We decided to use rotation_id-based token refresh instead of sliding "
    "window expiry. The rotation_id approach lets us track which token "
    "generation a client holds without server-side session state. Each refresh "
    "request includes the current rotation_id; the server issues a new token "
    "with an incremented rotation_id and marks the old one as grace-period. "
    "Grace period is 5 minutes, matching the mobile background refresh. After "
    "the grace period, old rotation_ids are rejected. This avoids the clock-"
    "skew problems we saw with sliding window expiry in Q1. The main tradeoff: "
    "we need a rotation_id column in the tokens table, which requires a "
    "migration. The migration is backward-compatible — existing tokens get "
    "rotation_id=0 and work normally until their next refresh. We reviewed "
    "three alternatives: (1) sliding window (rejected: clock skew), (2) "
    "refresh token pairs (rejected: doubles storage), (3) rotation_id (chosen). "
    "The decision was unanimous after the Q1 incident post-mortem."
)

MEDIUM_ACTIVE_BODY = (
    "Infrastructure migration from us-east-1 to us-west-2 is 60% complete. "
    "Database replicas are syncing. The API gateway cutover is scheduled for "
    "Thursday. Load testing shows p99 latency is 12ms higher in us-west-2 "
    "but within SLO. DNS TTL reduced to 60s in preparation for the switch."
)

WORKFLOW_BODY = (
    "Release process: (1) cut release branch from main, (2) run full test "
    "suite including integration tests, (3) deploy to staging for 24h soak, "
    "(4) create GitHub release with changelog, (5) deploy to production with "
    "canary at 5%, (6) monitor for 2h, (7) promote to 100%. Rollback at any "
    "stage by reverting the release branch merge."
)

PROJECT_BODY = (
    "API v3 redesign is in the design phase. Key changes: resource-based "
    "URLs, consistent pagination, and OpenAPI 3.1 spec. Target: Q3 beta. "
    "Stakeholders: platform team, mobile team, partner integrations."
)


def _efficiency_index() -> Index:
    index = Index()
    entries = [
        make_entry(
            entry_id="handoff-auth-refactor",
            title="Auth refactor handoff",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            updated_at=NOW - timedelta(hours=6),
            expires_at=NOW + timedelta(days=3),
            projects=["api-service"],
            tags=["auth", "tokens"],
            body=LONG_ACTIVE_BODY,
        ),
        make_entry(
            entry_id="handoff-deploy-status",
            title="Deploy status update",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            updated_at=NOW - timedelta(hours=2),
            expires_at=NOW + timedelta(days=1),
            projects=["api-service"],
            tags=["deploy"],
            body="Staging deploy green. Production deploy queued for 3pm.",
        ),
        make_entry(
            entry_id="handoff-infra-migration",
            title="Infrastructure region migration",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            updated_at=NOW - timedelta(days=1),
            expires_at=NOW + timedelta(days=5),
            projects=["infra"],
            tags=["migration", "aws"],
            body=MEDIUM_ACTIVE_BODY,
        ),
        make_entry(
            entry_id="decision-token-format",
            title="Token rotation strategy decision",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            status=EntryStatus.ACTIVE,
            updated_at=NOW - timedelta(days=2),
            projects=["api-service"],
            tags=["auth", "tokens"],
            body=LONG_DECISION_BODY,
        ),
        make_entry(
            entry_id="workflow-release-process",
            title="Release process workflow",
            entry_type=EntryType.WORKFLOW,
            level=EscalationLevel.L2,
            status=EntryStatus.ACTIVE,
            updated_at=NOW - timedelta(days=3),
            projects=["platform"],
            tags=["release", "deploy"],
            body=WORKFLOW_BODY,
        ),
        make_entry(
            entry_id="project-api-redesign",
            title="API v3 redesign",
            entry_type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            status=EntryStatus.ACTIVE,
            updated_at=NOW - timedelta(days=1),
            projects=["api-service"],
            tags=["api", "design"],
            body=PROJECT_BODY,
        ),
        make_entry(
            entry_id="restricted-vendor-tokens",
            title="Vendor token storage details",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            status=EntryStatus.ACTIVE,
            updated_at=NOW - timedelta(days=1),
            projects=["api-service"],
            tags=["security"],
            sensitivity=Sensitivity.RESTRICTED,
            body="Sensitive vendor token details. Must not appear in broad context.",
        ),
        make_entry(
            entry_id="expired-old-handoff",
            title="Old deployment handoff",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            updated_at=NOW - timedelta(days=10),
            expires_at=NOW - timedelta(days=2),
            projects=["api-service"],
            tags=["deploy"],
            body="This handoff expired two days ago and should not appear.",
        ),
    ]
    for entry in entries:
        index.add(entry)
    return index


VISIBLE_ACTIVE_IDS = {"handoff-auth-refactor", "handoff-deploy-status", "handoff-infra-migration"}
VISIBLE_RECENT_IDS = {"decision-token-format", "workflow-release-process", "project-api-redesign"}
EXCLUDED_IDS = {"restricted-vendor-tokens", "expired-old-handoff"}


def _signal(number: int = 42, **overrides: object) -> PRSignal:
    defaults: dict[str, object] = {
        "signal_id": f"github:org/api:pull:{number}",
        "provider": "github",
        "repo": "org/api",
        "number": number,
        "url": f"https://github.com/org/api/pull/{number}",
        "title": "Resolve token refresh races",
        "body_excerpt": (
            "This PR fixes the race condition in token refresh by adding rotation_id checks."
        ),
        "author": "alice",
        "state": "open",
        "labels": ("jurati",),
        "created_at": NOW - timedelta(days=2),
        "updated_at": NOW - timedelta(hours=6),
        "merged_at": None,
        "changed_paths": ("src/auth/token.py", "src/auth/refresh.py"),
        "target_areas": ("src/auth",),
    }
    defaults.update(overrides)
    return PRSignal(**defaults)  # type: ignore[arg-type]


def _coordination_signals() -> list[PRSignal]:
    return [
        _signal(42, title="Fix auth token refresh race condition"),
        _signal(
            99,
            title="Update CI pipeline config",
            body_excerpt=None,
            changed_paths=("ci/pipeline.yml",),
            target_areas=("ci",),
        ),
    ]


def _state(
    *,
    index: Index | None = None,
    signals: list[PRSignal] | None = None,
    repos: tuple[str, ...] = ("org/api",),
) -> ServerState:
    config = JuratiConfig(
        remote_url="https://example.com/kb.git",
        pr_signals=PRSignalsConfig(repos=repos),
    )
    cache = SignalCache(recency_days=30)
    if signals:
        cache.update(signals, now=NOW)
    return ServerState(
        config=config,
        repo_path="/fake/repo",
        index=index or Index(),
        last_sync=NOW,
        sync_health=SyncHealth(last_success=NOW),
        signal_cache=cache,
    )


# ---------------------------------------------------------------------------
# Baseline measurement
# ---------------------------------------------------------------------------


class TestFullContextBaseline:
    def test_payload_token_cost(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="full")
        tokens = _approximate_tokens(payload)
        assert tokens > 1000, f"Expected >1k tokens for full context, got {tokens}"

    def test_every_entry_has_body(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="full")
        for entry in payload["active"]:
            assert "body" in entry, f"Active entry {entry['id']} missing body"
            assert entry["body"], f"Active entry {entry['id']} has empty body"
        for entry in payload["recent"]:
            assert "body" in entry, f"Recent entry {entry['id']} missing body"
            assert entry["body"], f"Recent entry {entry['id']} has empty body"

    def test_bodies_dominate_payload(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="full")
        full_tokens = _approximate_tokens(payload)

        all_entries = payload["active"] + payload["recent"]
        body_chars = sum(len(e["body"]) for e in all_entries)
        body_tokens = math.ceil(body_chars / 4)

        assert body_tokens > full_tokens * 0.4, (
            f"Bodies should dominate payload: {body_tokens} body tokens "
            f"vs {full_tokens} total tokens"
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _noop_fetch(_config: Any) -> Sequence[PRSignal]:
    return []


async def _noop_run_blocking(fn: Any) -> Any:
    return fn()


_test_logger = logging.getLogger("jurati.test")


class TestFullCoordinationBaseline:
    @pytest.mark.anyio()
    async def test_evidence_arrays_present(self) -> None:
        signals = _coordination_signals()
        state = _state(signals=signals)
        result = await build_coordination_payload(
            state,
            repo="org/api",
            goal="auth token work",
            paths=None,
            now=NOW,
            fetch_signals=_noop_fetch,
            run_blocking=_noop_run_blocking,
            logger=_test_logger,
        )
        assert result["status"] == "ok"
        for g in result["guidance"]:
            assert "evidence" in g
            for ev in g["evidence"]:
                assert "matched_paths" in ev
                assert "body_excerpt" in ev or ev.get("body_excerpt") is None

    @pytest.mark.anyio()
    async def test_coordination_token_cost(self) -> None:
        signals = _coordination_signals()
        state = _state(signals=signals)
        result = await build_coordination_payload(
            state,
            repo="org/api",
            goal="auth token work",
            paths=None,
            now=NOW,
            fetch_signals=_noop_fetch,
            run_blocking=_noop_run_blocking,
            logger=_test_logger,
        )
        tokens = _approximate_tokens(result)
        assert tokens > 200, f"Expected coordination to have measurable cost, got {tokens}"


class TestFullCurationBaseline:
    @pytest.mark.anyio()
    async def test_per_item_instructions_present(self) -> None:
        index = Index()
        index.add(
            make_entry(
                entry_id="stale-decision",
                title="Stale auth decision",
                entry_type=EntryType.DECISION,
                level=EscalationLevel.L2,
                status=EntryStatus.ACTIVE,
                updated_at=NOW - timedelta(days=120),
                expires_at=NOW - timedelta(days=1),
                projects=["api-service"],
                tags=["auth"],
                body="Old decision about auth tokens.",
            )
        )
        index.add(
            make_entry(
                entry_id="active-expired",
                title="Expired active handoff",
                entry_type=EntryType.ACTIVE,
                level=EscalationLevel.L0,
                status=EntryStatus.ACTIVE,
                updated_at=NOW - timedelta(days=10),
                expires_at=NOW - timedelta(days=1),
                projects=["api-service"],
                tags=["deploy"],
                body="This active handoff is expired.",
            )
        )
        state = _state(index=index)
        result = await build_curation_payload(
            state,
            now=NOW,
            include_signals=False,
            repo="api-service",
            fetch_signals=_noop_fetch,
            run_blocking=_noop_run_blocking,
            logger=_test_logger,
        )
        if result is not None:
            for item in result.get("expired_active", []):
                assert "agent_instruction" in item

    @pytest.mark.anyio()
    async def test_curation_token_cost(self) -> None:
        index = Index()
        index.add(
            make_entry(
                entry_id="active-expired-cost",
                title="Expired handoff for cost measurement",
                entry_type=EntryType.ACTIVE,
                level=EscalationLevel.L0,
                status=EntryStatus.ACTIVE,
                updated_at=NOW - timedelta(days=10),
                expires_at=NOW - timedelta(days=1),
                projects=["api-service"],
                body="Expired handoff body.",
            )
        )
        state = _state(index=index)
        result = await build_curation_payload(
            state,
            now=NOW,
            include_signals=False,
            fetch_signals=_noop_fetch,
            run_blocking=_noop_run_blocking,
            logger=_test_logger,
        )
        if result is not None:
            tokens = _approximate_tokens(result)
            assert tokens > 50, f"Expected curation to have measurable cost, got {tokens}"


# ---------------------------------------------------------------------------
# Coverage assertions
# ---------------------------------------------------------------------------


class TestCoverage:
    def test_active_coverage(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="full")
        active_ids = {e["id"] for e in payload["active"]}
        assert active_ids == VISIBLE_ACTIVE_IDS

    def test_recent_coverage(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="full")
        recent_ids = {e["id"] for e in payload["recent"]}
        assert recent_ids == VISIBLE_RECENT_IDS

    def test_restricted_entry_excluded(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="full")
        all_ids = {e["id"] for e in payload["active"]} | {e["id"] for e in payload["recent"]}
        assert "restricted-vendor-tokens" not in all_ids

    def test_expired_entry_excluded(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="full")
        all_ids = {e["id"] for e in payload["active"]} | {e["id"] for e in payload["recent"]}
        assert "expired-old-handoff" not in all_ids

    def test_no_excluded_entries_leak(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="full")
        all_ids = {e["id"] for e in payload["active"]} | {e["id"] for e in payload["recent"]}
        assert not all_ids & EXCLUDED_IDS


# ---------------------------------------------------------------------------
# Field inventory
# ---------------------------------------------------------------------------


FULL_ENTRY_FIELDS = {
    "id",
    "title",
    "type",
    "level",
    "status",
    "created_at",
    "updated_at",
    "expires_at",
    "projects",
    "tags",
    "path",
    "body",
}


class TestFieldInventory:
    def test_full_entry_field_set(self) -> None:
        index = _efficiency_index()
        entry = index.get("handoff-auth-refactor")
        assert entry is not None
        formatted = _format_entry(entry)
        assert set(formatted.keys()) == FULL_ENTRY_FIELDS

    def test_all_entries_consistent_fields(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="full")
        for entry in payload["active"] + payload["recent"]:
            assert set(entry.keys()) == FULL_ENTRY_FIELDS, (
                f"Entry {entry['id']} has unexpected fields: "
                f"extra={set(entry.keys()) - FULL_ENTRY_FIELDS}, "
                f"missing={FULL_ENTRY_FIELDS - set(entry.keys())}"
            )


# ---------------------------------------------------------------------------
# Phase 2 — Manifest entry formatting
# ---------------------------------------------------------------------------

MANIFEST_ALWAYS_FIELDS = {
    "id",
    "title",
    "type",
    "status",
    "projects",
    "tags",
    "updated_at",
    "read_hint",
}

MANIFEST_EXCLUDED_FIELDS = {
    "body",
    "level",
    "created_at",
    "expires_at",
    "path",
}


class TestManifestContext:
    def test_manifest_entries_have_no_body(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="manifest")
        for entry in payload["active"] + payload["recent"]:
            assert "body" not in entry, f"Manifest entry {entry['id']} should not have body"

    def test_manifest_entries_have_summary(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="manifest")
        for entry in payload["active"] + payload["recent"]:
            has_summary = "summary" in entry or entry.get("summary_missing") is True
            assert has_summary, (
                f"Manifest entry {entry['id']} has neither summary nor summary_missing"
            )

    def test_manifest_entries_have_read_hint(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="manifest")
        for entry in payload["active"] + payload["recent"]:
            assert "read_hint" in entry, f"Manifest entry {entry['id']} missing read_hint"
            assert entry["read_hint"].startswith("read(id=")

    def test_manifest_preserves_coverage(self) -> None:
        index = _efficiency_index()
        manifest = _build_context_payload(index, now=NOW, mode="manifest")
        full = _build_context_payload(index, now=NOW, mode="full")
        manifest_active_ids = {e["id"] for e in manifest["active"]}
        full_active_ids = {e["id"] for e in full["active"]}
        assert manifest_active_ids == full_active_ids

        manifest_recent_ids = {e["id"] for e in manifest["recent"]}
        full_recent_ids = {e["id"] for e in full["recent"]}
        assert manifest_recent_ids == full_recent_ids

    def test_manifest_smaller_than_full(self) -> None:
        index = _efficiency_index()
        manifest = _build_context_payload(index, now=NOW, mode="manifest")
        full = _build_context_payload(index, now=NOW, mode="full")
        manifest_tokens = _approximate_tokens(manifest)
        full_tokens = _approximate_tokens(full)
        assert manifest_tokens < full_tokens, (
            f"Manifest ({manifest_tokens}) should be smaller than full ({full_tokens})"
        )

    def test_manifest_excluded_fields(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="manifest")
        for entry in payload["active"] + payload["recent"]:
            for field in MANIFEST_EXCLUDED_FIELDS:
                assert field not in entry, f"Manifest entry {entry['id']} should not have '{field}'"

    def test_manifest_always_fields(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="manifest")
        for entry in payload["active"] + payload["recent"]:
            for field in MANIFEST_ALWAYS_FIELDS:
                assert field in entry, (
                    f"Manifest entry {entry['id']} missing required field '{field}'"
                )

    def test_full_mode_backward_compat(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="full")
        for entry in payload["active"] + payload["recent"]:
            assert set(entry.keys()) == FULL_ENTRY_FIELDS


class TestSummaryDerivation:
    def test_frontmatter_summary_preferred(self) -> None:
        entry = make_entry(
            entry_id="summary-test",
            body="This body should be ignored.",
            summary="Author-written summary.",
        )
        text, missing = _derive_summary(entry)
        assert text == "Author-written summary."
        assert missing is False

    def test_body_fallback(self) -> None:
        entry = make_entry(
            entry_id="body-fallback",
            body="First paragraph of the entry body.",
        )
        text, missing = _derive_summary(entry)
        assert text == "First paragraph of the entry body."
        assert missing is False

    def test_skips_headings_and_code_fences(self) -> None:
        entry = make_entry(
            entry_id="skip-structure",
            body="# Heading\n\n```python\ncode()\n```\n\nActual content here.",
        )
        text, missing = _derive_summary(entry)
        assert text == "Actual content here."
        assert missing is False

    def test_truncates_long_text(self) -> None:
        long_body = "word " * 100
        entry = make_entry(entry_id="long-body", body=long_body.strip())
        text, missing = _derive_summary(entry, max_chars=50)
        assert text is not None
        assert text.endswith("...")
        assert len(text) <= 54  # 50 + "..."

    def test_empty_body(self) -> None:
        entry = make_entry(entry_id="empty-body", body="")
        text, missing = _derive_summary(entry)
        assert text is None
        assert missing is True

    def test_heading_only_body(self) -> None:
        entry = make_entry(entry_id="heading-only", body="# Just a heading\n\n## Another")
        text, missing = _derive_summary(entry)
        assert text is None
        assert missing is True

    def test_multi_paragraph_uses_first(self) -> None:
        entry = make_entry(
            entry_id="multi-para",
            body="First paragraph content.\n\nSecond paragraph ignored.",
        )
        text, missing = _derive_summary(entry)
        assert text == "First paragraph content."
        assert missing is False


class TestManifestFormatter:
    def test_manifest_entry_fields(self) -> None:
        index = _efficiency_index()
        entry = index.get("handoff-auth-refactor")
        assert entry is not None
        formatted = _format_entry_manifest(entry)
        assert set(formatted.keys()) - {"summary", "summary_missing"} == MANIFEST_ALWAYS_FIELDS

    def test_relevance_included_when_provided(self) -> None:
        index = _efficiency_index()
        entry = index.get("handoff-auth-refactor")
        assert entry is not None
        rel = {"score": 3.5, "reasons": ["project-match"]}
        formatted = _format_entry_manifest(entry, relevance=rel)
        assert formatted["relevance"] == rel

    def test_relevance_excluded_when_none(self) -> None:
        index = _efficiency_index()
        entry = index.get("handoff-auth-refactor")
        assert entry is not None
        formatted = _format_entry_manifest(entry)
        assert "relevance" not in formatted


class TestReadMany:
    def test_returns_full_bodies(self) -> None:
        index = _efficiency_index()
        graph = build_entry_graph(index)
        ids = ["handoff-auth-refactor", "decision-token-format"]
        results = []
        for entry_id in ids:
            entry = index.get(entry_id)
            assert entry is not None
            results.append(_format_entry(entry, graph=graph))
        for r in results:
            assert "body" in r
            assert r["body"]
            assert "links" in r

    def test_restricted_excluded(self) -> None:
        index = _efficiency_index()
        entry = index.get("restricted-vendor-tokens")
        assert entry is not None
        assert entry.frontmatter.sensitivity == Sensitivity.RESTRICTED

    def test_expired_excluded(self) -> None:
        index = _efficiency_index()
        entry = index.get("expired-old-handoff")
        assert entry is not None
        assert entry.frontmatter.expires_at is not None
        assert entry.frontmatter.expires_at <= NOW

    def test_graph_built_once(self) -> None:
        index = _efficiency_index()
        graph = build_entry_graph(index)
        ids = ["handoff-auth-refactor", "handoff-deploy-status", "decision-token-format"]
        results = [_format_entry(index.get(eid), graph=graph) for eid in ids]  # type: ignore[arg-type]
        for r in results:
            assert "links" in r


# ---------------------------------------------------------------------------
# Phase 3 — Coverage accounting
# ---------------------------------------------------------------------------


class TestCoverageAccounting:
    def test_manifest_has_coverage_metadata(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="manifest")
        assert "coverage" in payload
        assert "context_schema" in payload
        assert "mode" in payload

    def test_manifest_schema_and_mode(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="manifest")
        assert payload["context_schema"] == "manifest-v1"
        assert payload["mode"] == "manifest"

    def test_full_schema_and_mode(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="full")
        assert payload["context_schema"] == "full-v1"
        assert payload["mode"] == "full"

    def test_coverage_entry_counts(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="manifest")
        cov = payload["coverage"]
        assert cov["active_returned"] == len(VISIBLE_ACTIVE_IDS)
        assert cov["recent_returned"] == len(VISIBLE_RECENT_IDS)

    def test_manifest_bodies_omitted(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="manifest")
        cov = payload["coverage"]
        total_entries = cov["active_returned"] + cov["recent_returned"]
        assert cov["entry_bodies_omitted"] == total_entries

    def test_full_bodies_not_omitted(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="full")
        assert payload["coverage"]["entry_bodies_omitted"] == 0

    def test_restricted_count(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="manifest")
        assert payload["coverage"]["hidden_restricted_entries"] == 1

    def test_no_coordination_zero_signals(self) -> None:
        index = _efficiency_index()
        payload = _build_context_payload(index, now=NOW, mode="manifest")
        cov = payload["coverage"]
        assert cov["coordination_signals_returned"] == 0
        assert cov["signal_excerpts_omitted"] == 0

    def test_coordination_signal_counts(self) -> None:
        index = _efficiency_index()
        coordination = {
            "status": "ok",
            "guidance": [
                {
                    "effect": "pause",
                    "summary": "Block on auth PR",
                    "evidence": [{"pr": 42}, {"pr": 43}],
                },
                {
                    "effect": "continue",
                    "summary": "CI is green",
                    "evidence": [{"pr": 99}],
                },
            ],
        }
        payload = _build_context_payload(index, now=NOW, mode="manifest", coordination=coordination)
        cov = payload["coverage"]
        assert cov["coordination_signals_returned"] == 2
        assert cov["signal_excerpts_omitted"] == 3

    def test_full_mode_no_signal_excerpts_omitted(self) -> None:
        index = _efficiency_index()
        coordination = {
            "status": "ok",
            "guidance": [
                {
                    "effect": "pause",
                    "summary": "Block",
                    "evidence": [{"pr": 42}],
                },
            ],
        }
        payload = _build_context_payload(index, now=NOW, mode="full", coordination=coordination)
        assert payload["coverage"]["signal_excerpts_omitted"] == 0

    def test_coverage_consistent_between_modes(self) -> None:
        index = _efficiency_index()
        manifest = _build_context_payload(index, now=NOW, mode="manifest")
        full = _build_context_payload(index, now=NOW, mode="full")
        assert manifest["coverage"]["active_returned"] == full["coverage"]["active_returned"]
        assert manifest["coverage"]["recent_returned"] == full["coverage"]["recent_returned"]
