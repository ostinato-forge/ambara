# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ambara.core.context_accounting import (
    AccountingInputs,
    CounterfactualBaseline,
    append_ledger_event,
    compact_value_receipt,
    detailed_cost_accounting,
    estimate_tokens,
    ledger_event,
    read_ledger_events,
    summarize_events,
    summary_windows,
)

NOW = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)


def test_estimate_tokens_is_deterministic() -> None:
    payload = {"b": ["second", "third"], "a": "first"}
    assert estimate_tokens(payload) == estimate_tokens({"a": "first", "b": ["second", "third"]})


def test_compact_value_receipt_reports_positive_savings_without_details() -> None:
    receipt = compact_value_receipt(
        packet_tokens_est=120,
        full_context_tokens_est=1120,
        deferred_body_count=4,
        skipped_count=8,
        suppressed_count=2,
        budget_mode="quiet",
    )

    assert receipt["saved_tokens_est"] == 1000
    assert "net_savings_tokens_est" not in receipt
    assert receipt["deferred"] == 4
    assert receipt["skipped"] == 8
    assert receipt["suppressed"] == 2
    assert receipt["mode"] == "quiet"
    assert "entry_id" not in receipt
    assert "query" not in receipt


def test_detailed_cost_accounting_allows_negative_savings() -> None:
    payload = {"large": "x" * 4000}
    accounting = detailed_cost_accounting(
        AccountingInputs(
            tool_name="context",
            context_schema="compiler-v1",
            response_payload=payload,
            full_context_tokens_est=20,
        )
    )

    assert accounting["actual_ambara_tokens_est"] > accounting["counterfactual_tokens_est"]
    assert accounting["net_savings_tokens_est"] < 0


def test_source_excerpt_omissions_preserve_signal_compatibility_alias() -> None:
    accounting = detailed_cost_accounting(
        AccountingInputs(
            tool_name="context",
            context_schema="compiler-v1",
            source_excerpts_omitted_count=3,
        )
    )

    assert accounting["source_excerpts_omitted_count"] == 3
    assert accounting["signal_excerpts_omitted_count"] == 3


def test_legacy_signal_excerpt_omissions_feed_source_count() -> None:
    accounting = detailed_cost_accounting(
        AccountingInputs(
            tool_name="context",
            context_schema="compiler-v1",
            signal_excerpts_omitted_count=2,
        )
    )

    assert accounting["source_excerpts_omitted_count"] == 2
    assert accounting["signal_excerpts_omitted_count"] == 2


def test_ledger_event_stores_aggregate_metrics_only() -> None:
    event = ledger_event(
        AccountingInputs(
            tool_name="read_many",
            context_schema="read-many-v1",
            read_body_count=2,
            selected_entry_count=2,
            response_payload=[{"id": "secret-id", "body": "secret body"}],
            full_context_tokens_est=500,
        ),
        now=NOW,
    )

    event_text = str(event)
    assert event["tool_name"] == "read_many"
    assert event["read_body_count"] == 2
    assert "ambara_version" in event
    assert "event_id" in event
    assert "secret-id" not in event_text
    assert "secret body" not in event_text
    assert "raw_query" not in event
    assert "caller" not in event


def test_ledger_summary_windows(tmp_path) -> None:
    path = tmp_path / "value-ledger.jsonl"
    old = ledger_event(
        AccountingInputs(
            tool_name="context",
            context_schema="compiler-v1",
            full_context_tokens_est=1000,
            response_payload={"ok": True},
            entries_omitted_count=4,
        ),
        now=NOW - timedelta(days=10),
    )
    recent = ledger_event(
        AccountingInputs(
            tool_name="startup",
            context_schema="startup-s2",
            full_context_tokens_est=1200,
            response_payload={"ok": True},
            already_seen_suppressed_count=3,
        ),
        now=NOW - timedelta(days=2),
    )
    append_ledger_event(path, old)
    append_ledger_event(path, recent)

    assert len(read_ledger_events(path, now=NOW, days=7)) == 1
    assert summarize_events([old, recent])["event_count"] == 2
    windows = summary_windows(path, now=NOW)
    assert windows["last_7_days"]["event_count"] == 1
    assert windows["last_30_days"]["event_count"] == 2


def test_summarize_events_adds_currency_aware_cost() -> None:
    events = [
        {"net_savings_tokens_est": 1_000_000, "budget_mode": "balanced"},
        {"net_savings_tokens_est": 500_000, "budget_mode": "balanced"},
    ]
    summary = summarize_events(events, price_per_million=3.0, currency="EUR")
    assert summary["net_savings_tokens_est"] == 1_500_000
    assert summary["net_savings_cost_est"] == 4.5
    assert summary["cost_currency"] == "EUR"
    assert summary["price_per_million"] == 3.0


def test_summarize_events_omits_cost_without_price() -> None:
    summary = summarize_events([{"net_savings_tokens_est": 1_000_000, "budget_mode": "balanced"}])
    assert "net_savings_cost_est" not in summary
    assert "cost_currency" not in summary


def test_summary_windows_threads_currency_through(tmp_path) -> None:
    path = tmp_path / "value-ledger.jsonl"
    append_ledger_event(
        path,
        ledger_event(
            AccountingInputs(
                tool_name="startup",
                context_schema="startup-s2",
                full_context_tokens_est=1200,
                response_payload={"ok": True},
            ),
            now=NOW - timedelta(days=1),
        ),
    )
    windows = summary_windows(path, now=NOW, price_per_million=2.5, currency="GBP")
    assert windows["last_7_days"]["cost_currency"] == "GBP"
    assert "net_savings_cost_est" in windows["last_7_days"]


def test_manifest_baseline_uses_manifest_tokens() -> None:
    accounting = detailed_cost_accounting(
        AccountingInputs(
            tool_name="context",
            context_schema="compiler-v1",
            response_payload={"ok": True},
            manifest_tokens_est=800,
            full_context_tokens_est=4000,
            counterfactual_baseline=CounterfactualBaseline.MANIFEST_ONLY_CONTEXT.value,
        )
    )

    assert accounting["counterfactual_baseline"] == "manifest_only_context"
    assert accounting["counterfactual_tokens_est"] == 800
