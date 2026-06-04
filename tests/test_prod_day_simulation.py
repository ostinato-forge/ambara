# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Production-day simulation for cross-agent Ambara use."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ambara.cli_render import render_startup_markdown
from ambara.core.context_accounting import (
    AccountingInputs,
    append_ledger_event,
    estimate_text_tokens,
    estimate_tokens,
    ledger_event,
    summary_windows,
)
from ambara.core.index import Index
from ambara.core.pr_signals import CoordinationGuidance, classify_signals
from ambara.core.schema import EntryStatus, EntryType, EscalationLevel, RecordedBy, Sensitivity
from ambara.git.config import PRSignalsConfig
from ambara.providers.fixture_signals import fetch_fixture_signals
from ambara.server_read import build_startup_v2_payload
from ambara.server_state import SyncHealth
from tests.core.conftest import make_entry

NOW = datetime(2026, 6, 4, 10, 0, tzinfo=UTC)
CLIENTS = ("codex", "claude-code", "cursor", "gemini")
USER_COUNT = 100
AGENT_COUNT = 100
SERVICE_COUNT = 10


def test_prod_day_100_users_100_agents_cross_agent_context(
    tmp_path: Path,
) -> None:
    """Prove the cross-agent claim against a deterministic normal work day."""
    index = _prod_day_index()
    fixture = tmp_path / "signals.json"
    fixture.write_text(json.dumps({"signals": _prod_day_signals()}, indent=2) + "\n")
    signals = fetch_fixture_signals(
        PRSignalsConfig(
            repos=("org/monorepo",),
            fixture_path=str(fixture),
            jira_base_url="https://jira.example",
            jira_projects=("AMB",),
        )
    )
    assert {getattr(signal, "provider", "") for signal in signals} == {
        "github",
        "gitlab",
        "jira",
    }

    ledger = tmp_path / "value-ledger.jsonl"
    clients_seen: set[str] = set()
    actors_seen = {f"user-{i:03d}" for i in range(USER_COUNT)}
    selected_entries = 0
    actions: Counter[str] = Counter()
    max_markdown_tokens = 0

    for agent_id in range(AGENT_COUNT):
        client = CLIENTS[agent_id % len(CLIENTS)]
        service_id = agent_id % SERVICE_COUNT
        path = f"services/service-{service_id}/handler.py"
        guidance = classify_signals(
            signals,
            repo="org/monorepo",
            paths=[path],
            now=NOW,
        )
        packet = build_startup_v2_payload(
            index,
            now=NOW + timedelta(minutes=agent_id),
            sync_health=SyncHealth(last_success=NOW),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            repo="org/monorepo",
            goal=f"continue service {service_id} handoff",
            max_entries=5,
            coordination=_coordination_payload(guidance),
        )
        markdown = render_startup_markdown(packet)

        assert "# Team Context" in markdown
        assert "## Dig deeper" in markdown
        assert "Restricted payroll token" not in markdown
        assert '"body"' not in json.dumps(packet).lower()

        clients_seen.add(client)
        actions[str(packet["action"])] += 1
        selected_entries += len(packet.get("entries", []))
        max_markdown_tokens = max(max_markdown_tokens, estimate_text_tokens(markdown))
        append_ledger_event(
            ledger,
            ledger_event(
                AccountingInputs(
                    tool_name="startup",
                    context_schema="startup-s2",
                    client_surface=client,
                    response_payload=packet,
                    selected_entry_count=len(packet.get("entries", [])),
                    full_context_tokens_est=estimate_tokens(packet) + 800,
                ),
                now=NOW + timedelta(minutes=agent_id),
            ),
        )

    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    summary = summary_windows(ledger, now=NOW + timedelta(hours=8))

    assert clients_seen == set(CLIENTS)
    assert len(actors_seen) == USER_COUNT
    assert len(events) == AGENT_COUNT
    assert {event["client_surface"] for event in events} == set(CLIENTS)
    assert selected_entries >= AGENT_COUNT
    assert actions["pause"] > 0
    assert summary["last_7_days"]["event_count"] == AGENT_COUNT
    assert summary["last_7_days"]["net_savings_tokens_est"] > 0
    assert max_markdown_tokens < 2_500


def _prod_day_index() -> Index:
    index = Index()
    for user_id in range(USER_COUNT):
        service_id = user_id % SERVICE_COUNT
        client = CLIENTS[user_id % len(CLIENTS)]
        index.add(
            make_entry(
                entry_id=f"handoff-user-{user_id:03d}",
                title=f"Service {service_id} handoff from user-{user_id:03d}",
                entry_type=EntryType.ACTIVE,
                level=EscalationLevel.L0,
                status=EntryStatus.ACTIVE,
                created_at=NOW - timedelta(hours=4, minutes=user_id),
                updated_at=NOW - timedelta(minutes=user_id),
                projects=[f"service-{service_id}"],
                tags=["handoff", "normal-day"],
                body=(
                    f"user-{user_id:03d} left service {service_id} ready for the "
                    "next agent after tests and review."
                ),
                review_required=False,
                recorded_by=RecordedBy(client=client),
            )
        )

    for service_id in range(SERVICE_COUNT):
        index.add(
            make_entry(
                entry_id=f"service-{service_id}-api-contract",
                title=f"Service {service_id} API contract decision",
                entry_type=EntryType.DECISION,
                level=EscalationLevel.L2,
                status=EntryStatus.ACTIVE,
                updated_at=NOW - timedelta(days=1),
                projects=[f"service-{service_id}"],
                tags=["api", "decision"],
                body=f"Service {service_id} uses the reviewed response envelope.",
            )
        )

    index.add(
        make_entry(
            entry_id="restricted-payroll-token",
            title="Restricted payroll token handling",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            status=EntryStatus.ACTIVE,
            sensitivity=Sensitivity.RESTRICTED,
            body="Restricted payroll token must never appear in broad context.",
        )
    )
    return index


def _prod_day_signals() -> list[dict[str, object]]:
    signals: list[dict[str, object]] = []
    for user_id in range(USER_COUNT):
        provider = ("github", "gitlab", "jira")[user_id % 3]
        service_id = user_id % SERVICE_COUNT
        path = f"services/service-{service_id}/handler.py"
        state = "open" if user_id % 5 == 0 else "merged"
        if provider == "jira":
            signals.append(
                {
                    "provider": "jira",
                    "signal_id": f"jira:AMB-{user_id}",
                    "source": "AMB",
                    "artifact_ref": f"https://jira.example/browse/AMB-{user_id}",
                    "title": f"Service {service_id} handoff for user-{user_id:03d}",
                    "excerpt": "Ownership handoff and blocker context for the next agent.",
                    "actor": f"user-{user_id:03d}",
                    "state": state,
                    "labels": ["ambara"],
                    "created_at": (NOW - timedelta(hours=6)).isoformat(),
                    "updated_at": (NOW - timedelta(minutes=user_id)).isoformat(),
                    "subject_refs": [path],
                    "subject_areas": [f"services/service-{service_id}"],
                }
            )
        else:
            number = 1000 + user_id
            signals.append(
                {
                    "provider": provider,
                    "repo": "org/monorepo",
                    "number": number,
                    "url": _review_url(provider, number),
                    "title": f"Service {service_id} review handoff for user-{user_id:03d}",
                    "body_excerpt": (
                        "Review handoff touches the service handler for today's agents."
                    ),
                    "author": f"user-{user_id:03d}",
                    "state": state,
                    "labels": ["ambara"],
                    "created_at": (NOW - timedelta(hours=6)).isoformat(),
                    "updated_at": (NOW - timedelta(minutes=user_id)).isoformat(),
                    "changed_paths": [path],
                }
            )
    return signals


def _review_url(provider: str, number: int) -> str:
    if provider == "gitlab":
        return f"https://gitlab.com/org/monorepo/-/merge_requests/{number}"
    return f"https://github.com/org/monorepo/pull/{number}"


def _coordination_payload(guidance: list[CoordinationGuidance]) -> dict[str, object]:
    return {
        "status": "ok",
        "summary": f"{len(guidance)} coordination signals found.",
        "guidance": [
            {
                "effect": item.effect,
                "urgency": item.urgency,
                "confidence": item.confidence,
                "summary": item.summary,
                "evidence": [
                    {"repo": evidence.repo, "url": evidence.url} for evidence in item.evidence
                ],
            }
            for item in guidance
        ],
        "privacy_boundary": ["fixture signal excerpts are already sanitized"],
    }
