# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for the startup-v2 rendering layer in server_read.py."""

from __future__ import annotations

import json
import math
from datetime import timedelta
from typing import Any

from ambara.cli.render import render_startup_markdown
from ambara.core.index import Index
from ambara.core.schema import (
    EntryStatus,
    EntryType,
    EscalationLevel,
    Sensitivity,
)
from ambara.server_read import (
    _build_compiler_payload,
    _build_disabled_startup_v2_payload,
    _build_unavailable_startup_v2_payload,
    _entry_why,
    build_startup_v2_payload,
)
from ambara.server_state import SyncHealth
from tests.core.conftest import BASE_NOW, make_entry

NOW = BASE_NOW


def _approx_tokens(payload: dict[str, Any]) -> int:
    return math.ceil(len(json.dumps(payload, default=str)) / 4)


def _sync_health(age_seconds: int = 0, **kwargs) -> SyncHealth:
    return SyncHealth(
        last_success=NOW - timedelta(seconds=age_seconds),
        **kwargs,
    )


def _stale_sync_health() -> SyncHealth:
    return SyncHealth(
        last_success=NOW - timedelta(seconds=1200),
        last_failure=NOW - timedelta(seconds=60),
        last_error="git fetch: connection refused",
        consecutive_failures=2,
    )


def _failed_sync_health() -> SyncHealth:
    return SyncHealth(
        last_success=None,
        last_failure=NOW,
        last_error="git fetch: connection refused",
        consecutive_failures=1,
    )


def _index_with_entries(n: int = 5, *, restricted: int = 0) -> Index:
    index = Index()
    for i in range(n):
        index.add(
            make_entry(
                entry_id=f"entry-{i}",
                title=f"Entry {i} title",
                entry_type=EntryType.ACTIVE if i < 3 else EntryType.DECISION,
                level=EscalationLevel.L0 if i < 3 else EscalationLevel.L2,
                status=EntryStatus.ACTIVE,
                updated_at=NOW - timedelta(hours=i),
                expires_at=NOW + timedelta(days=3) if i < 3 else None,
                projects=["test-repo"],
                body=f"Body content for entry {i}.",
            )
        )
    for i in range(restricted):
        index.add(
            make_entry(
                entry_id=f"restricted-{i}",
                title=f"Restricted {i}",
                entry_type=EntryType.DECISION,
                level=EscalationLevel.L2,
                status=EntryStatus.ACTIVE,
                updated_at=NOW - timedelta(hours=1),
                sensitivity=Sensitivity.RESTRICTED,
                body="Secret.",
            )
        )
    return index


def _coordination_fixture() -> dict[str, Any]:
    return {
        "status": "ok",
        "summary": "2 signals found.",
        "guidance": [
            {
                "effect": "revise",
                "urgency": "notice",
                "confidence": 60,
                "summary": "CDEV may change constraints.",
                "evidence": [{"repo": "CDEV", "url": "https://jira/CDEV-100"}],
            },
            {
                "effect": "continue",
                "urgency": "quiet",
                "confidence": 40,
                "summary": "Informational signal.",
                "evidence": [{"repo": "CDEV", "url": "https://jira/CDEV-200"}],
            },
        ],
        "privacy_boundary": ["standard"],
    }


class TestStartupV2Payload:
    def test_returns_s2_schema(self) -> None:
        index = _index_with_entries(3)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            repo="test-repo",
            goal="plan auth changes",
        )
        assert packet["v"] == "s2"
        assert packet["availability"] == "fresh"
        assert "action" in packet

    def test_entries_capped_at_max(self) -> None:
        index = _index_with_entries(8)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            repo="test-repo",
            goal="test",
            max_entries=3,
        )
        assert len(packet.get("entries", [])) <= 3
        assert packet["more"]["entries_omitted"] >= 5

    def test_quiet_budget_caps_more_aggressively(self) -> None:
        index = _index_with_entries(4)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            repo="test-repo",
            goal="test",
            max_entries=4,
            budget_mode="quiet",
        )

        assert len(packet.get("entries", [])) == 1
        assert packet["more"]["entries_omitted"] >= 3
        assert packet["value"]["mode"] == "quiet"

    def test_entries_have_why_not_summary(self) -> None:
        index = _index_with_entries(2)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            goal="test",
        )
        for entry in packet.get("entries", []):
            assert "why" in entry
            assert "summary" not in entry
            assert "read_hint" not in entry

    def test_coordination_constraints_extracted(self) -> None:
        index = _index_with_entries(2)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            goal="test",
            coordination=_coordination_fixture(),
        )
        assert packet["coordination"] == "caution"
        assert any(c["effect"] == "revise" for c in packet.get("constraints", []))

    def test_notice_signals_counted_not_shown(self) -> None:
        index = _index_with_entries(2)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            goal="test",
            coordination=_coordination_fixture(),
        )
        for c in packet.get("constraints", []):
            assert c["effect"] != "notice"
        assert packet.get("more", {}).get("notices_omitted", 0) >= 1

    def test_restricted_entries_counted(self) -> None:
        index = _index_with_entries(3, restricted=2)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            goal="test",
        )
        assert packet["more"]["restricted_hidden"] == 2

    def test_stale_includes_reason_and_freshness(self) -> None:
        index = _index_with_entries(2)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_stale_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            goal="test",
        )
        assert packet["availability"] == "stale"
        assert "reason" in packet
        assert "freshness" in packet

    def test_fresh_omits_reason_and_freshness(self) -> None:
        index = _index_with_entries(2)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            goal="test",
        )
        assert "reason" not in packet
        assert "freshness" not in packet

    def test_no_body_keys_in_packet(self) -> None:
        index = _index_with_entries(3)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            goal="test",
        )
        raw = json.dumps(packet)
        assert '"body"' not in raw

    def test_value_receipt_is_compact_and_body_free(self) -> None:
        index = _index_with_entries(4)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            goal="test",
            max_entries=2,
        )

        value = packet["value"]
        assert value["packet_tokens_est"] > 0
        assert value["saved_tokens_est"] >= 0
        assert value["deferred"] >= 2
        assert "counterfactual_baseline" not in value
        assert "Body content" not in str(value)

        markdown = render_startup_markdown(packet)
        assert "**Value:** used ~" in markdown
        assert "avoided ~" in markdown
        assert "Body content" not in markdown

    def test_value_rollup_renders_tokens_and_optional_cost(self) -> None:
        packet = {
            "availability": "available",
            "action": "proceed",
            "value_rollup": {
                "window": "last_7_days",
                "events": 3,
                "net_savings_tokens_est": 1_500_000,
                "net_savings_cost_est": 4.5,
                "cost_currency": "EUR",
            },
            "entries": [],
            "more": {},
        }

        markdown = render_startup_markdown(packet)

        assert "**Saved (7d):** ~1,500,000 tokens / ~€4.50 across 3 context loads" in markdown

    def test_source_health_renders_without_raw_error_details(self) -> None:
        index = _index_with_entries(1)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_failed_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            goal="test",
            source_health={
                "configured": 2,
                "fresh": 1,
                "stale": 0,
                "unavailable": 1,
                "error": 0,
                "sources": [
                    {
                        "id": "legacy-fixture-signals",
                        "provider": "fixture",
                        "status": "unavailable",
                        "baseline_available": False,
                    }
                ],
            },
        )

        markdown = render_startup_markdown(packet)
        raw = json.dumps(packet)

        assert packet["source_health"]["unavailable"] == 1
        assert "## Source Health" in markdown
        assert "legacy-fixture-signals" in markdown
        assert "Could not read signal fixture" not in raw
        assert "Source fixture unavailable" not in raw
        assert "/tmp/private/signals.json" not in raw
        assert "Could not read signal fixture" not in markdown
        assert "Source fixture unavailable" not in markdown
        assert "/tmp/private/signals.json" not in markdown

    def test_source_omissions_render_as_counts_only(self) -> None:
        index = _index_with_entries(1)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            goal="test",
            source_omissions={
                "privacy": 1,
                "safety": 2,
                "budget": 4,
                "freshness": 0,
                "source_error": 0,
                "total": 7,
            },
        )

        markdown = render_startup_markdown(packet)

        assert packet["source_omissions"]["budget"] == 4
        assert "## Source Omissions" in markdown
        assert "7 source input omission(s)" in markdown
        assert "budget: 4" in markdown
        assert "private-source-details" not in markdown

    def test_constraint_first_extraction(self) -> None:
        """Constraints must be extracted from ALL entries before Top-N capping."""
        index = _index_with_entries(10)
        coordination = {
            "status": "ok",
            "summary": "Blocking signal.",
            "guidance": [
                {
                    "effect": "pause",
                    "urgency": "blocking",
                    "confidence": 90,
                    "summary": "PR blocks this work.",
                    "evidence": [{"repo": "org/api", "url": "https://github.com/org/api/pull/42"}],
                },
            ],
        }
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            goal="test",
            max_entries=2,
            coordination=coordination,
        )
        assert packet["action"] == "pause"
        assert any(c["effect"] == "pause" for c in packet["constraints"])
        assert len(packet["entries"]) <= 2


class TestUnavailableStartupV2:
    def test_unavailable_packet(self) -> None:
        packet = _build_unavailable_startup_v2_payload(
            now=NOW,
            reason="Snapshot not available; run sync() first.",
            freshness_warning_seconds=300,
            stale_after_seconds=900,
        )
        assert packet["v"] == "s2"
        assert packet["action"] == "stop_context_unavailable"
        assert packet["availability"] == "unavailable"
        assert "reason" in packet


class TestDisabledStartupV2:
    def test_disabled_packet_is_not_unavailable(self) -> None:
        packet = _build_disabled_startup_v2_payload()
        assert packet["v"] == "s2"
        assert packet["availability"] == "disabled"
        assert packet["action"] == "proceed_local_only"
        assert packet["coordination"] == "clear"
        assert "reason" in packet


class TestEntryWhy:
    def test_project_match(self) -> None:
        assert "project" in _entry_why("active", ["bm25", "project-match"]).lower()

    def test_exact_match(self) -> None:
        assert "matching" in _entry_why("decision", ["exact-match"]).lower()

    def test_generic_fallback(self) -> None:
        assert "relevant" in _entry_why("workflow", ["bm25"]).lower()

    def test_no_reasons(self) -> None:
        assert "relevant" in _entry_why("active", None).lower()

    def test_type_labels(self) -> None:
        assert _entry_why("active", None).startswith("Active work")
        assert _entry_why("decision", None).startswith("Decision")
        assert _entry_why("workflow", None).startswith("Required workflow")
        assert _entry_why("principle", None).startswith("Guiding principle")


class TestTokenSizeRegression:
    def test_s2_smaller_than_compiler_v1(self) -> None:
        index = _index_with_entries(6, restricted=1)
        shared_kwargs = dict(
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            repo="test-repo",
            goal="plan auth changes",
            coordination=_coordination_fixture(),
        )
        v1 = _build_compiler_payload(index, **shared_kwargs)
        s2 = build_startup_v2_payload(index, **shared_kwargs, max_entries=3)
        v1_tokens = _approx_tokens(v1)
        s2_tokens = _approx_tokens(s2)
        assert s2_tokens < v1_tokens, f"s2={s2_tokens} should be < v1={v1_tokens}"

    def test_clear_packet_compact(self) -> None:
        index = _index_with_entries(2)
        packet = build_startup_v2_payload(
            index,
            now=NOW,
            sync_health=_sync_health(),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            goal="test",
            max_entries=2,
        )
        tokens = _approx_tokens(packet)
        assert tokens < 120, f"Clear s2 packet was {tokens} tokens, expected < 120"
