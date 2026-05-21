#!/usr/bin/env python3
"""Simulate a multi-person team using Jurati and test whether agents get useful context.

Four team members contribute knowledge entries across a web platform project.
Five scenarios test whether an agent receives the right context at the right time.

Usage:
    .venv/bin/python scripts/team-simulation.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio

from jurati.core.index import Index
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
    Sensitivity,
)
from jurati.git.config import JuratiConfig
from jurati.server import (
    ServerState,
    SyncHealth,
    context,
    query,
    search,
)

NOW = datetime(2026, 5, 21, 14, 0, tzinfo=UTC)
RECENT = NOW - timedelta(days=2)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _entry(
    *,
    entry_id: str,
    title: str,
    entry_type: EntryType,
    level: EscalationLevel,
    body: str,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    status: EntryStatus = EntryStatus.ACTIVE,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    expires_at: datetime | None = None,
    pr: str | None = "https://github.com/acme/knowledge/pull/1",
) -> Entry:
    type_dir = {
        EntryType.PRINCIPLE: "principles",
        EntryType.DECISION: "decisions",
        EntryType.WORKFLOW: "workflows",
        EntryType.PROJECT: "projects",
        EntryType.ACTIVE: "active",
    }[entry_type]
    review_required = level not in (EscalationLevel.L0,)
    return Entry(
        path=f"{type_dir}/{entry_id}.md",
        frontmatter=Frontmatter(
            id=entry_id,
            title=title,
            type=entry_type,
            level=level,
            status=status,
            created_at=created_at or RECENT,
            updated_at=updated_at or RECENT,
            expires_at=expires_at,
            projects=projects or [],
            tags=tags or [],
            sensitivity=Sensitivity.NORMAL,
            review=ReviewMeta(required=review_required, pr=pr if review_required else None),
        ),
        body=body,
    )


class _FakeCtx:
    def __init__(self, state: ServerState) -> None:
        self.request_context = type("RC", (), {"lifespan_context": state})()


# ── Team Knowledge ────────────────────────────────────────────────────────────


def build_team_knowledge() -> list[Entry]:
    """Create realistic entries from a 4-person team building a web platform."""

    return [
        # ── Alice (Backend Lead) ──────────────────────────────────────────
        _entry(
            entry_id="no-raw-sql",
            title="All database access must use the ORM",
            entry_type=EntryType.PRINCIPLE,
            level=EscalationLevel.L3,
            tags=["database", "security", "orm"],
            body=(
                "All database access goes through the SQLAlchemy ORM. Raw SQL queries "
                "require explicit security review and a comment explaining why the ORM "
                "is insufficient. This prevents SQL injection and keeps migrations "
                "consistent. Exceptions: one-off analytics scripts in the data/ directory."
            ),
        ),
        _entry(
            entry_id="auth-jwt-rotation",
            title="Use short-lived JWTs with server-side rotation",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            projects=["auth-service", "api-server"],
            tags=["auth", "jwt", "security"],
            body=(
                "Access tokens are JWTs with 15-minute expiry. Refresh tokens are opaque, "
                "stored server-side in Redis, and rotated on each use. This balances "
                "stateless verification with revocation capability. The auth-service owns "
                "token issuance; other services validate via the shared JWKS endpoint."
            ),
        ),
        _entry(
            entry_id="api-review-gate",
            title="API changes require OpenAPI spec update before review",
            entry_type=EntryType.WORKFLOW,
            level=EscalationLevel.L2,
            projects=["api-server"],
            tags=["api", "review", "openapi"],
            body=(
                "Any PR that adds or modifies an API endpoint must include an updated "
                "OpenAPI spec (openapi.yaml). CI validates the spec against the "
                "implementation. Reviewers should check the spec diff first — if the "
                "contract looks wrong, the implementation doesn't matter yet."
            ),
        ),
        _entry(
            entry_id="auth-migration-status",
            title="Auth migration: session store move to Redis in progress",
            entry_type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            projects=["auth-service"],
            tags=["auth", "migration", "redis"],
            body=(
                "JWT rotation is implemented and deployed. Session store migration from "
                "Postgres to Redis is in progress. 3 of 6 services have been updated to "
                "use the new Redis session client. Remaining: user-service, billing-service, "
                "notification-service. Target completion: May 30."
            ),
        ),
        _entry(
            entry_id="alice-handoff-session-store",
            title="Session store migration handoff",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            projects=["auth-service"],
            tags=["handoff", "redis", "migration"],
            expires_at=NOW + timedelta(days=5),
            body=(
                "Redis cluster is provisioned and tested. The new session client is in "
                "src/auth/session_redis.py — it's a drop-in replacement for the Postgres "
                "session store. To migrate a service: update its config to point to Redis, "
                "swap the import, and run the integration tests. See PR #234 for the "
                "pattern used in the first 3 services. user-service is the next one to do."
            ),
        ),
        # ── Bob (Frontend Dev) ────────────────────────────────────────────
        _entry(
            entry_id="react-server-components",
            title="Adopt React Server Components for new pages",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            projects=["web-app"],
            tags=["frontend", "react", "rsc"],
            body=(
                "New pages should use React Server Components (RSC) by default. Client "
                "components are allowed for interactive elements but must be explicitly "
                "marked with 'use client'. This reduces bundle size and improves TTFB. "
                "Existing pages can be migrated incrementally — don't rewrite working "
                "client components unless there's a performance reason."
            ),
        ),
        _entry(
            entry_id="bob-handoff-checkout",
            title="Checkout page handoff: shipping address WIP",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            projects=["web-app"],
            tags=["handoff", "checkout", "frontend"],
            expires_at=NOW + timedelta(days=3),
            body=(
                "Payment form validation is complete and tested (src/pages/checkout/"
                "PaymentForm.tsx). Shipping address autocomplete is work-in-progress — "
                "the UI component exists but the geocoding integration is blocked waiting "
                "for the Google Maps API key from DevOps (asked in #infra-requests on "
                "Monday). The form layout follows the existing address pattern in "
                "src/components/AddressInput.tsx. Don't start the order summary section "
                "until the address form is working — they share validation state."
            ),
        ),
        # ── Charlie (SRE) ────────────────────────────────────────────────
        _entry(
            entry_id="deploy-canary-required",
            title="Production deploys require canary rollout",
            entry_type=EntryType.WORKFLOW,
            level=EscalationLevel.L2,
            projects=["platform"],
            tags=["deploy", "canary", "production", "sre"],
            body=(
                "All production deployments must use canary rollout: 5% traffic for 30 "
                "minutes minimum, with automated rollback on error rate > 1% or p99 "
                "latency > 500ms. The canary config is in deploy/canary.yaml. Hotfixes "
                "can use 10% for 15 minutes with SRE approval. Direct deploys (skipping "
                "canary) are blocked by CI — only the SRE team can override."
            ),
        ),
        _entry(
            entry_id="incident-db-latency",
            title="P2 incident: database latency spikes during peak hours",
            entry_type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            projects=["platform", "api-server"],
            tags=["incident", "database", "latency", "p2"],
            body=(
                "Since May 18, we see p99 query latency spike to 2s during 2-4pm UTC. "
                "Root cause suspected: connection pool exhaustion in the api-server. "
                "The pool is set to 20 connections but we're seeing 50+ concurrent "
                "queries during peak. Immediate mitigation: increased pool to 40. "
                "Long-term fix: implement connection pooling via PgBouncer. Do NOT "
                "add new heavy queries to the api-server until this is resolved."
            ),
        ),
        # ── Dana (PM) ────────────────────────────────────────────────────
        _entry(
            entry_id="feature-freeze-q3",
            title="Feature freeze starts June 1 for Q3 release",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            projects=["web-app", "api-server", "auth-service"],
            tags=["release", "freeze", "q3"],
            body=(
                "Feature freeze for Q3 release begins June 1. After that date, only "
                "bug fixes and the auth migration (already in progress) are allowed on "
                "main. New features must target the q4 branch. This was agreed in the "
                "May 15 planning meeting. The checkout page work must ship before freeze."
            ),
        ),
    ]


# ── Scenarios ─────────────────────────────────────────────────────────────────


SCENARIOS: list[dict[str, Any]] = [
    {
        "title": "New agent starting work on the checkout page",
        "tool": "context",
        "kwargs": {
            "repo": "web-app",
            "goal": "complete the checkout page shipping address feature",
        },
        "expected": ["bob-handoff-checkout", "react-server-components", "feature-freeze-q3"],
        "why": (
            "Agent needs Bob's handoff (WIP state + geocoding blocker), "
            "RSC decision, and freeze deadline"
        ),
    },
    {
        "title": "Agent asked to write a database query",
        "tool": "search",
        "kwargs": {"query": "database access SQL query patterns"},
        "expected": ["no-raw-sql", "incident-db-latency"],
        "why": "Agent should know to use ORM (not raw SQL) and about the active latency incident",
    },
    {
        "title": "Agent about to modify an API endpoint",
        "tool": "context",
        "kwargs": {"repo": "api-server", "goal": "add a new endpoint for user preferences"},
        "expected": ["api-review-gate", "auth-jwt-rotation", "incident-db-latency"],
        "why": (
            "Agent needs the OpenAPI workflow, JWT auth pattern, and the latency incident warning"
        ),
    },
    {
        "title": "Agent starting a production deploy",
        "tool": "search",
        "kwargs": {"query": "production deployment process canary"},
        "expected": ["deploy-canary-required"],
        "why": "Agent must know about canary requirements before deploying",
    },
    {
        "title": "Agent picking up session store migration",
        "tool": "context",
        "kwargs": {"repo": "auth-service", "goal": "continue session store migration to Redis"},
        "expected": ["alice-handoff-session-store", "auth-migration-status", "auth-jwt-rotation"],
        "why": (
            "Agent needs Alice's handoff (PR #234, next service), project status, and JWT context"
        ),
    },
]


# ── Runner ────────────────────────────────────────────────────────────────────


def _extract_ids(result: Any) -> list[str]:
    """Pull entry IDs from tool results regardless of shape."""
    ids: list[str] = []
    if isinstance(result, dict):
        for entry in result.get("active", []):
            if isinstance(entry, dict) and "id" in entry:
                ids.append(entry["id"])
        for entry in result.get("recent", []):
            if isinstance(entry, dict) and "id" in entry:
                ids.append(entry["id"])
    elif isinstance(result, list):
        for entry in result:
            if isinstance(entry, dict) and "id" in entry:
                ids.append(entry["id"])
    return ids


def _extract_entries(result: Any) -> list[dict[str, Any]]:
    """Pull formatted entries from tool results."""
    entries: list[dict[str, Any]] = []
    if isinstance(result, dict):
        entries.extend(result.get("active", []))
        entries.extend(result.get("recent", []))
    elif isinstance(result, list):
        entries.extend(e for e in result if isinstance(e, dict))
    return entries


async def run_simulation() -> int:
    entries = build_team_knowledge()
    index = Index()
    for entry in entries:
        index.add(entry)

    state = ServerState(
        config=JuratiConfig(remote_url="https://example.com/knowledge.git"),
        repo_path="/fake/repo",
        index=index,
        last_sync=NOW,
        sync_health=SyncHealth(last_success=NOW),
    )
    ctx = _FakeCtx(state)

    print()
    print("=" * 72)
    print("  JURATI TEAM SIMULATION")
    print("  4 team members, 10 knowledge entries, 5 agent scenarios")
    print("=" * 72)

    total = len(SCENARIOS)
    passed = 0
    partial = 0

    for i, scenario in enumerate(SCENARIOS, 1):
        tool_name = scenario["tool"]
        kwargs = scenario["kwargs"]

        if tool_name == "context":
            result = await context(ctx=ctx, **kwargs)
        elif tool_name == "query":
            result = await query(ctx=ctx, **kwargs)
        elif tool_name == "search":
            result = await search(ctx=ctx, **kwargs)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")

        received_ids = _extract_ids(result)
        expected_ids = scenario["expected"]
        found = [eid for eid in expected_ids if eid in received_ids]
        missing = [eid for eid in expected_ids if eid not in received_ids]
        extra = [eid for eid in received_ids if eid not in expected_ids]

        if not missing:
            verdict = "PASS"
            passed += 1
        elif found:
            verdict = "PARTIAL"
            partial += 1
        else:
            verdict = "FAIL"

        icon = {"PASS": "+", "PARTIAL": "~", "FAIL": "!"}[verdict]

        print()
        print(f"{'━' * 72}")
        print(f"  [{icon}] Scenario {i}: {scenario['title']}")
        print(f"{'━' * 72}")
        print(f"  Tool:     {tool_name}({', '.join(f'{k}={v!r}' for k, v in kwargs.items())})")
        print(f"  Why:      {scenario['why']}")
        print(f"  Expected: {expected_ids}")
        print(f"  Found:    {found}")
        if missing:
            print(f"  Missing:  {missing}")
        if extra:
            print(f"  Extra:    {extra}")
        print(f"  Verdict:  {verdict}")

        surfaced = _extract_entries(result)
        if surfaced:
            print()
            print("  Context surfaced to agent:")
            for entry in surfaced:
                eid = entry.get("id", "?")
                title = entry.get("title", "?")
                body = entry.get("body", "")[:100]
                marker = "*" if eid in expected_ids else " "
                print(f"    {marker} [{entry.get('type', '?')}] {title}")
                print(f"        {body}...")

    print()
    print("=" * 72)
    print(
        f"  RESULTS: {passed}/{total} passed, {partial} partial, {total - passed - partial} failed"
    )
    print("=" * 72)

    if passed == total:
        print()
        print("  Jurati surfaced the right context in every scenario.")
        print("  An agent using Jurati would know about:")
        print("    - WIP state and blockers before touching code")
        print("    - Team coding standards (ORM, RSC) before writing")
        print("    - Required workflows (OpenAPI, canary) before acting")
        print("    - Active incidents before deploying")
        print("    - Handoff details to continue someone else's work")
    elif passed + partial == total:
        print()
        print("  Jurati surfaced most context but missed some entries.")
        print("  Partial results may indicate ranking/relevance gaps.")
    else:
        print()
        print("  Jurati missed critical context in some scenarios.")
        print("  This suggests the retrieval model needs work.")

    print()
    return 0 if passed == total else 1


def main() -> None:
    sys.exit(anyio.run(run_simulation))


if __name__ == "__main__":
    main()
