"""Full-context versus compiler-packet planning equivalence fixtures."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from jurati.core.context_compiler import (
    constraints_from_context_payload,
    derive_freshness,
    planning_signature,
    planning_signature_from_compiler_packet,
)
from jurati.core.index import Index
from jurati.core.schema import EntryStatus, EntryType, EscalationLevel
from jurati.server_read import _build_compiler_payload, _build_context_payload
from jurati.server_state import SyncHealth
from tests.core.conftest import BASE_NOW, make_entry

NOW = BASE_NOW
FRESHNESS_WARNING_SECONDS = 300
STALE_AFTER_SECONDS = 900


def _planning_index() -> Index:
    index = Index()
    for entry in (
        make_entry(
            entry_id="auth-handoff",
            title="Auth handoff",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            updated_at=NOW - timedelta(hours=2),
            expires_at=NOW + timedelta(days=2),
            projects=["org/api"],
            tags=["auth"],
            body="Auth token work is in progress. Coordinate before editing token code.",
            review_required=False,
        ),
        make_entry(
            entry_id="token-decision",
            title="Token rotation decision",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            status=EntryStatus.ACTIVE,
            updated_at=NOW - timedelta(days=1),
            projects=["org/api"],
            tags=["auth", "tokens"],
            body="Use rotation IDs for refresh tokens.",
            review_pr="https://github.com/org/api/pull/12",
        ),
    ):
        index.add(entry)
    return index


def _sync_health(age_seconds: int = 0) -> SyncHealth:
    return SyncHealth(last_success=NOW - timedelta(seconds=age_seconds))


def _unavailable_health() -> SyncHealth:
    return SyncHealth(
        last_success=None,
        last_failure=NOW,
        last_error="source repository unavailable",
        consecutive_failures=2,
    )


def _freshness_for(health: SyncHealth):
    return derive_freshness(
        now=NOW,
        last_success=health.last_success,
        warning_threshold_seconds=FRESHNESS_WARNING_SECONDS,
        stale_threshold_seconds=STALE_AFTER_SECONDS,
        last_failure=health.last_failure,
        last_error=health.last_error,
        consecutive_failures=health.consecutive_failures,
    )


def _coordination(effect: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "summary": "A jurati-labeled PR may affect auth token work.",
        "guidance": [
            {
                "effect": effect,
                "urgency": "warning" if effect == "pause" else "notice",
                "summary": "Auth API contract PR touches token code.",
                "instruction": "Account for the auth API contract before editing token code.",
                "confidence": 85,
                "evidence": [
                    {
                        "repo": "org/api",
                        "number": 42,
                        "url": "https://github.com/org/api/pull/42",
                        "title": "Auth API contract",
                        "author": "alice",
                        "state": "open",
                        "updated_at": NOW.isoformat(),
                        "matched_paths": ["src/auth/token.py"],
                        "changed_paths_status": "available",
                        "body_excerpt": "Long provider excerpt that compiler packets omit.",
                        "text_trust": "untrusted_external",
                        "reason": "path overlap with current work",
                    }
                ],
            }
        ],
        "privacy_boundary": ["test fixture"],
    }


def _curation_due() -> dict[str, Any]:
    return {
        "status": "ok",
        "summary": "1 knowledge advisory needs attention.",
        "total_advisories": 1,
        "shown_advisories": 1,
        "omitted_advisories": 0,
        "agent_instruction": "Verify affected entries when they matter to the task.",
        "expired_active": [],
        "revalidation_due": [
            {
                "id": "token-decision",
                "title": "Token rotation decision",
                "type": "decision",
                "status": "active",
                "path": "decisions/token-decision.md",
                "updated_at": (NOW - timedelta(days=1)).isoformat(),
                "review_after": (NOW - timedelta(hours=1)).isoformat(),
                "reason": "Past review_after.",
                "agent_instruction": "Revalidate before relying on this.",
            }
        ],
        "completed_artifact_revalidation": [],
        "privacy_boundary": ["test fixture"],
    }


def _without_read_handles(signature: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in signature.items() if key != "read_handles"}


def _assert_same_planning_decision(
    *,
    full_payload: dict[str, Any],
    compiler_packet: dict[str, Any],
    health: SyncHealth,
) -> None:
    freshness = _freshness_for(health)
    full_signature = planning_signature(
        freshness,
        constraints_from_context_payload(full_payload),
    )
    compiler_signature = planning_signature_from_compiler_packet(compiler_packet)

    assert _without_read_handles(compiler_signature) == _without_read_handles(full_signature)
    assert set(compiler_signature["read_handles"]).issuperset(full_signature["read_handles"])


@pytest.mark.parametrize(
    (
        "coordination",
        "curation",
        "health",
        "expected_verdict",
        "expected_action",
    ),
    [
        (None, None, _sync_health(), "clear", "proceed"),
        (None, _curation_due(), _sync_health(), "caution", "read_or_verify_before_acting"),
        (_coordination("revise"), None, _sync_health(), "caution", "revise_plan_before_acting"),
        (_coordination("pause"), None, _sync_health(), "blocked", "pause"),
        (
            _coordination("pause"),
            None,
            _sync_health(age_seconds=1200),
            "stale",
            "stop_or_request_refresh",
        ),
        (None, None, _unavailable_health(), "context_unavailable", "stop_context_unavailable"),
    ],
)
def test_compiler_packet_preserves_full_context_planning_decision(
    coordination: dict[str, Any] | None,
    curation: dict[str, Any] | None,
    health: SyncHealth,
    expected_verdict: str,
    expected_action: str,
) -> None:
    index = _planning_index()
    full_payload = _build_context_payload(
        index,
        now=NOW,
        mode="full",
        repo="org/api",
        goal="edit auth token code",
        coordination=coordination,
        curation=curation,
    )
    compiler_packet = _build_compiler_payload(
        index,
        now=NOW,
        sync_health=health,
        freshness_warning_seconds=FRESHNESS_WARNING_SECONDS,
        stale_after_seconds=STALE_AFTER_SECONDS,
        repo="org/api",
        goal="edit auth token code",
        coordination=coordination,
        curation=curation,
    )

    _assert_same_planning_decision(
        full_payload=full_payload,
        compiler_packet=compiler_packet,
        health=health,
    )
    assert compiler_packet["verdict"] == expected_verdict
    assert compiler_packet["planning_action"] == expected_action
    assert all("body" not in entry for entry in compiler_packet["relevant_entries"])
    assert all("body" in entry for entry in full_payload["active"] + full_payload["recent"])


def test_proceed_packet_still_exposes_entry_read_through_handles() -> None:
    index = _planning_index()
    compiler_packet = _build_compiler_payload(
        index,
        now=NOW,
        sync_health=_sync_health(),
        freshness_warning_seconds=FRESHNESS_WARNING_SECONDS,
        stale_after_seconds=STALE_AFTER_SECONDS,
        repo="org/api",
        goal="edit auth token code",
    )

    assert compiler_packet["planning_action"] == "proceed"
    assert {entry["id"]: entry["read_hint"] for entry in compiler_packet["relevant_entries"]} == {
        "auth-handoff": "read(id='auth-handoff') for full body",
        "token-decision": "read(id='token-decision') for full body",
    }
