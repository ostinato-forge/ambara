# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Privacy-preserving context value accounting.

The helpers in this module work only from already-selected payloads and
aggregate counts. They do not need raw queries, caller identity, entry titles in
ledger events, or response bodies in value summaries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from ambara import __version__

TOKEN_ESTIMATOR = "chars_div_4:v1"
LEDGER_SCHEMA_VERSION = 1
DEFAULT_LEDGER_RETENTION_DAYS = 90


class BudgetMode(StrEnum):
    QUIET = "quiet"
    BALANCED = "balanced"
    DEEP = "deep"


class SavingsConfidence(StrEnum):
    MEASURED = "measured"
    BOUNDED = "bounded"
    HEURISTIC = "heuristic"


class CounterfactualBaseline(StrEnum):
    NAIVE_FULL_ELIGIBLE_CONTEXT = "naive_full_eligible_context"
    MANIFEST_ONLY_CONTEXT = "manifest_only_context"
    COMPILER_SELECTED_CONTEXT = "compiler_selected_context"
    REPLAY_FIXTURE_BASELINE = "replay_fixture_baseline"


@dataclass(frozen=True)
class AccountingInputs:
    tool_name: str
    context_schema: str
    budget_mode: str = BudgetMode.BALANCED.value
    client_surface: str = "mcp"
    request_payload: dict[str, Any] | None = None
    response_payload: dict[str, Any] | list[Any] | None = None
    receipt_payload: dict[str, Any] | None = None
    eligible_candidate_count: int = 0
    selected_entry_count: int = 0
    read_body_count: int = 0
    entries_omitted_count: int = 0
    restricted_hidden_count: int = 0
    duplicates_suppressed_count: int = 0
    already_seen_suppressed_count: int = 0
    stale_suppressed_count: int = 0
    low_relevance_suppressed_count: int = 0
    user_muted_suppressed_count: int = 0
    notices_omitted_count: int = 0
    signal_excerpts_omitted_count: int = 0
    deferred_body_count: int = 0
    full_context_tokens_est: int | None = None
    manifest_tokens_est: int | None = None
    counterfactual_baseline: str = CounterfactualBaseline.NAIVE_FULL_ELIGIBLE_CONTEXT.value
    savings_confidence: str = SavingsConfidence.BOUNDED.value
    price_profile_id: str | None = None
    input_price_per_million: float | None = None


def estimate_tokens(value: Any) -> int:
    """Return a deterministic, conservative payload token estimate."""
    if value is None:
        return 0
    text = json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return estimate_text_tokens(text)


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def compact_value_receipt(
    *,
    packet_tokens_est: int,
    full_context_tokens_est: int | None,
    deferred_body_count: int = 0,
    skipped_count: int = 0,
    suppressed_count: int = 0,
    budget_mode: str = BudgetMode.BALANCED.value,
) -> dict[str, Any]:
    """Build the small in-band receipt used by startup packets."""
    value: dict[str, Any] = {
        "packet_tokens_est": max(0, packet_tokens_est),
        "mode": budget_mode,
    }
    if full_context_tokens_est is not None:
        saved = full_context_tokens_est - packet_tokens_est
        value["saved_tokens_est"] = max(0, saved)
        if saved < 0:
            value["net_savings_tokens_est"] = saved
    if deferred_body_count > 0:
        value["deferred"] = deferred_body_count
    if skipped_count > 0:
        value["skipped"] = skipped_count
    if suppressed_count > 0:
        value["suppressed"] = suppressed_count
    return value


def detailed_cost_accounting(inputs: AccountingInputs) -> dict[str, Any]:
    """Build additive, privacy-safe cost accounting for compiler/context packets."""
    request_tokens = estimate_tokens(inputs.request_payload)
    response_tokens = estimate_tokens(inputs.response_payload)
    receipt_tokens = estimate_tokens(inputs.receipt_payload)
    actual_tokens = request_tokens + response_tokens + receipt_tokens
    baseline_tokens = _baseline_tokens(inputs)
    net_savings = baseline_tokens - actual_tokens
    payload: dict[str, Any] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "token_estimator": TOKEN_ESTIMATOR,
        "app_payload_only": True,
        "tool_name": inputs.tool_name,
        "client_surface": inputs.client_surface,
        "budget_mode": inputs.budget_mode,
        "context_schema": inputs.context_schema,
        "request_tokens_est": request_tokens,
        "response_tokens_est": response_tokens,
        "receipt_tokens_est": receipt_tokens,
        "actual_ambara_tokens_est": actual_tokens,
        "counterfactual_baseline": inputs.counterfactual_baseline,
        "counterfactual_tokens_est": baseline_tokens,
        "net_savings_tokens_est": net_savings,
        "savings_confidence": inputs.savings_confidence,
        "eligible_candidate_count": max(0, inputs.eligible_candidate_count),
        "selected_entry_count": max(0, inputs.selected_entry_count),
        "read_body_count": max(0, inputs.read_body_count),
        "entries_omitted_count": max(0, inputs.entries_omitted_count),
        "restricted_hidden_count": max(0, inputs.restricted_hidden_count),
        "duplicates_suppressed_count": max(0, inputs.duplicates_suppressed_count),
        "already_seen_suppressed_count": max(0, inputs.already_seen_suppressed_count),
        "stale_suppressed_count": max(0, inputs.stale_suppressed_count),
        "low_relevance_suppressed_count": max(0, inputs.low_relevance_suppressed_count),
        "user_muted_suppressed_count": max(0, inputs.user_muted_suppressed_count),
        "notices_omitted_count": max(0, inputs.notices_omitted_count),
        "signal_excerpts_omitted_count": max(0, inputs.signal_excerpts_omitted_count),
        "full_bodies_deferred": max(0, inputs.deferred_body_count),
    }
    if inputs.full_context_tokens_est is not None:
        payload["full_context_tokens_est"] = max(0, inputs.full_context_tokens_est)
    if inputs.manifest_tokens_est is not None:
        payload["manifest_context_tokens_est"] = max(0, inputs.manifest_tokens_est)
    if inputs.price_profile_id and inputs.input_price_per_million is not None:
        payload["price_profile_id"] = inputs.price_profile_id
        payload["estimated_usd_saved"] = net_savings / 1_000_000 * inputs.input_price_per_million
    return payload


def ledger_event(inputs: AccountingInputs, *, now: datetime | None = None) -> dict[str, Any]:
    """Build a local ledger event with aggregate metrics only."""
    event = detailed_cost_accounting(inputs)
    return ledger_event_from_accounting(event, now=now)


def ledger_event_from_accounting(
    accounting: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    event = dict(accounting)
    event["event_id"] = uuid4().hex
    event["timestamp"] = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    event["ambara_version"] = __version__
    return event


def default_ledger_path(cache_dir: str | Path) -> Path:
    return Path(cache_dir).expanduser() / "value-ledger.jsonl"


def append_ledger_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")))
        handle.write("\n")


def read_ledger_events(
    path: Path, *, now: datetime | None = None, days: int | None = None
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    cutoff = None
    if days is not None:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_time = _event_time(event)
        if cutoff is not None and event_time is not None and event_time < cutoff:
            continue
        events.append(event)
    return events


def prune_ledger(
    path: Path,
    *,
    now: datetime | None = None,
    retention_days: int = DEFAULT_LEDGER_RETENTION_DAYS,
) -> None:
    if not path.exists():
        return
    events = read_ledger_events(path, now=now, days=retention_days)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events
        ),
        encoding="utf-8",
    )


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "event_count": len(events),
        "actual_ambara_tokens_est": 0,
        "counterfactual_tokens_est": 0,
        "net_savings_tokens_est": 0,
        "entries_omitted_count": 0,
        "restricted_hidden_count": 0,
        "duplicates_suppressed_count": 0,
        "already_seen_suppressed_count": 0,
        "stale_suppressed_count": 0,
        "low_relevance_suppressed_count": 0,
        "user_muted_suppressed_count": 0,
    }
    budget_modes: dict[str, int] = {}
    baselines: dict[str, int] = {}
    last_event: dict[str, Any] | None = None
    for event in events:
        for key in totals:
            if key == "event_count":
                continue
            totals[key] += _int_value(event.get(key))
        mode = str(event.get("budget_mode") or "unknown")
        budget_modes[mode] = budget_modes.get(mode, 0) + 1
        baseline = str(event.get("counterfactual_baseline") or "unknown")
        baselines[baseline] = baselines.get(baseline, 0) + 1
        if last_event is None or str(event.get("timestamp", "")) >= str(
            last_event.get("timestamp", "")
        ):
            last_event = event
    return {
        **totals,
        "budget_modes": budget_modes,
        "counterfactual_baselines": baselines,
        "last_event": last_event,
        "token_estimator": TOKEN_ESTIMATOR,
        "app_payload_only": True,
    }


def summary_windows(path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current_now = now or datetime.now(UTC)
    return {
        "ledger_path": str(path),
        "current_repo_or_session": summarize_events(
            read_ledger_events(path, now=current_now, days=1)
        ),
        "last_7_days": summarize_events(read_ledger_events(path, now=current_now, days=7)),
        "last_30_days": summarize_events(read_ledger_events(path, now=current_now, days=30)),
    }


def _baseline_tokens(inputs: AccountingInputs) -> int:
    if inputs.counterfactual_baseline == CounterfactualBaseline.MANIFEST_ONLY_CONTEXT:
        return max(0, inputs.manifest_tokens_est or 0)
    if inputs.counterfactual_baseline == CounterfactualBaseline.COMPILER_SELECTED_CONTEXT:
        return estimate_tokens(inputs.response_payload)
    return max(0, inputs.full_context_tokens_est or inputs.manifest_tokens_est or 0)


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _event_time(event: dict[str, Any]) -> datetime | None:
    raw = event.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
