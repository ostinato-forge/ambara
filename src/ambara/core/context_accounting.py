# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Privacy-preserving context value accounting.

The helpers in this module work only from already-selected payloads and
aggregate counts. They do not need raw queries, caller identity, entry titles in
ledger events, or response bodies in value summaries.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from ambara import __version__

TOKEN_ESTIMATOR = "content_typed_bounds:v1"
LEGACY_TOKEN_ESTIMATOR = "chars_div_4:v1"
TOKEN_RANGE_KIND = "conservative_range"
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
class TokenEstimate:
    estimate: int
    low: int
    high: int


@dataclass(frozen=True)
class _TokenProfile:
    low_chars_per_token: int
    estimate_chars_per_token: int
    high_chars_per_token: int


_TOKEN_PROFILES = {
    "markdown": _TokenProfile(
        low_chars_per_token=8, estimate_chars_per_token=4, high_chars_per_token=1
    ),
    "yaml": _TokenProfile(
        low_chars_per_token=6, estimate_chars_per_token=3, high_chars_per_token=1
    ),
    "json": _TokenProfile(
        low_chars_per_token=8, estimate_chars_per_token=4, high_chars_per_token=1
    ),
    "code": _TokenProfile(
        low_chars_per_token=6, estimate_chars_per_token=3, high_chars_per_token=1
    ),
    "unknown": _TokenProfile(
        low_chars_per_token=8, estimate_chars_per_token=4, high_chars_per_token=1
    ),
}


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
    source_excerpts_omitted_count: int = 0
    signal_excerpts_omitted_count: int = 0
    deferred_body_count: int = 0
    full_context_tokens_est: int | None = None
    full_context_tokens_low_est: int | None = None
    full_context_tokens_high_est: int | None = None
    manifest_tokens_est: int | None = None
    manifest_tokens_low_est: int | None = None
    manifest_tokens_high_est: int | None = None
    counterfactual_baseline: str = CounterfactualBaseline.NAIVE_FULL_ELIGIBLE_CONTEXT.value
    savings_confidence: str = SavingsConfidence.BOUNDED.value
    price_profile_id: str | None = None
    input_price_per_million: float | None = None


def estimate_tokens(value: Any) -> int:
    """Return a deterministic central payload token estimate."""
    return estimate_tokens_with_bounds(value).estimate


def estimate_tokens_with_bounds(value: Any) -> TokenEstimate:
    """Return a deterministic conservative token range for structured payloads."""
    if value is None:
        return TokenEstimate(estimate=0, low=0, high=0)
    text = json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return estimate_text_tokens_with_bounds(text, content_type="json")


def estimate_text_tokens(text: str) -> int:
    return estimate_text_tokens_with_bounds(text).estimate


def estimate_text_tokens_with_bounds(
    text: str, *, content_type: str | None = None
) -> TokenEstimate:
    """Estimate text tokens with a containing low/high range.

    The range is deliberately conservative. It is not a statistical confidence
    interval; it is an app-payload accounting envelope that avoids presenting a
    single heuristic point as measured truth.
    """
    if not text:
        return TokenEstimate(estimate=0, low=0, high=0)
    kind = content_type if content_type in _TOKEN_PROFILES else None
    spans = [(text, kind)] if kind else _content_spans(text)
    return _sum_token_estimates(_estimate_span_tokens(span, span_kind) for span, span_kind in spans)


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
    request_tokens = estimate_tokens_with_bounds(inputs.request_payload)
    response_tokens = estimate_tokens_with_bounds(inputs.response_payload)
    receipt_tokens = estimate_tokens_with_bounds(inputs.receipt_payload)
    actual_tokens = _sum_token_estimates((request_tokens, response_tokens, receipt_tokens))
    baseline_tokens = _baseline_token_estimate(inputs, response_tokens=response_tokens)
    net_savings = baseline_tokens.estimate - actual_tokens.estimate
    net_savings_low = baseline_tokens.low - actual_tokens.high
    net_savings_high = baseline_tokens.high - actual_tokens.low
    payload: dict[str, Any] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "token_estimator": TOKEN_ESTIMATOR,
        "token_range_kind": TOKEN_RANGE_KIND,
        "app_payload_only": True,
        "tool_name": inputs.tool_name,
        "client_surface": inputs.client_surface,
        "budget_mode": inputs.budget_mode,
        "context_schema": inputs.context_schema,
        "request_tokens_est": request_tokens.estimate,
        "response_tokens_est": response_tokens.estimate,
        "receipt_tokens_est": receipt_tokens.estimate,
        "actual_ambara_tokens_est": actual_tokens.estimate,
        "counterfactual_baseline": inputs.counterfactual_baseline,
        "counterfactual_tokens_est": baseline_tokens.estimate,
        "net_savings_tokens_est": net_savings,
        "net_savings_tokens_low_est": net_savings_low,
        "net_savings_tokens_high_est": net_savings_high,
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
        "source_excerpts_omitted_count": _source_excerpts_omitted_count(inputs),
        "signal_excerpts_omitted_count": _source_excerpts_omitted_count(inputs),
        "full_bodies_deferred": max(0, inputs.deferred_body_count),
    }
    _add_token_estimate_fields(payload, "request", request_tokens)
    _add_token_estimate_fields(payload, "response", response_tokens)
    _add_token_estimate_fields(payload, "receipt", receipt_tokens)
    _add_token_estimate_fields(payload, "actual_ambara", actual_tokens)
    _add_token_estimate_fields(payload, "counterfactual", baseline_tokens)
    if inputs.full_context_tokens_est is not None:
        full_context_tokens = _input_token_estimate(
            inputs.full_context_tokens_est,
            low=inputs.full_context_tokens_low_est,
            high=inputs.full_context_tokens_high_est,
        )
        payload["full_context_tokens_est"] = full_context_tokens.estimate
        _add_token_estimate_fields(payload, "full_context", full_context_tokens)
    if inputs.manifest_tokens_est is not None:
        manifest_tokens = _input_token_estimate(
            inputs.manifest_tokens_est,
            low=inputs.manifest_tokens_low_est,
            high=inputs.manifest_tokens_high_est,
        )
        payload["manifest_context_tokens_est"] = manifest_tokens.estimate
        _add_token_estimate_fields(payload, "manifest_context", manifest_tokens)
    if inputs.price_profile_id and inputs.input_price_per_million is not None:
        payload["price_profile_id"] = inputs.price_profile_id
        payload["estimated_usd_saved"] = net_savings / 1_000_000 * inputs.input_price_per_million
    return payload


def ledger_event(inputs: AccountingInputs, *, now: datetime | None = None) -> dict[str, Any]:
    """Build a local ledger event with aggregate metrics only."""
    event = detailed_cost_accounting(inputs)
    return ledger_event_from_accounting(event, now=now)


def _source_excerpts_omitted_count(inputs: AccountingInputs) -> int:
    return max(
        0,
        inputs.source_excerpts_omitted_count or inputs.signal_excerpts_omitted_count,
    )


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


DEFAULT_COST_CURRENCY = "USD"


def estimate_cost(tokens: int, price_per_million: float) -> float:
    """Convert a token count to a monetary estimate at the given unit price.

    ``price_per_million`` is expressed in the caller's own currency, so this
    stays currency-neutral for an international user base.
    """
    return tokens / 1_000_000 * price_per_million


def summarize_events(
    events: list[dict[str, Any]],
    *,
    price_per_million: float | None = None,
    currency: str = DEFAULT_COST_CURRENCY,
) -> dict[str, Any]:
    totals = {
        "event_count": len(events),
        "actual_ambara_tokens_est": 0,
        "actual_ambara_tokens_low_est": 0,
        "actual_ambara_tokens_high_est": 0,
        "counterfactual_tokens_est": 0,
        "counterfactual_tokens_low_est": 0,
        "counterfactual_tokens_high_est": 0,
        "net_savings_tokens_est": 0,
        "net_savings_tokens_low_est": 0,
        "net_savings_tokens_high_est": 0,
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
            totals[key] += _summary_int(event, key)
        mode = str(event.get("budget_mode") or "unknown")
        budget_modes[mode] = budget_modes.get(mode, 0) + 1
        baseline = str(event.get("counterfactual_baseline") or "unknown")
        baselines[baseline] = baselines.get(baseline, 0) + 1
        if last_event is None or str(event.get("timestamp", "")) >= str(
            last_event.get("timestamp", "")
        ):
            last_event = event
    summary: dict[str, Any] = {
        **totals,
        "budget_modes": budget_modes,
        "counterfactual_baselines": baselines,
        "last_event": last_event,
        "token_estimator": TOKEN_ESTIMATOR,
        "app_payload_only": True,
    }
    if price_per_million is not None:
        summary["net_savings_cost_est"] = round(
            estimate_cost(totals["net_savings_tokens_est"], price_per_million), 4
        )
        summary["cost_currency"] = currency
        summary["price_per_million"] = price_per_million
    return summary


def summary_windows(
    path: Path,
    *,
    now: datetime | None = None,
    price_per_million: float | None = None,
    currency: str = DEFAULT_COST_CURRENCY,
) -> dict[str, Any]:
    current_now = now or datetime.now(UTC)

    def _window(days: int) -> dict[str, Any]:
        return summarize_events(
            read_ledger_events(path, now=current_now, days=days),
            price_per_million=price_per_million,
            currency=currency,
        )

    return {
        "ledger_path": str(path),
        "current_repo_or_session": _window(1),
        "last_7_days": _window(7),
        "last_30_days": _window(30),
    }


def _content_spans(text: str) -> tuple[tuple[str, str], ...]:
    lines = text.splitlines(keepends=True)
    if not lines:
        return ((text, "unknown"),)

    spans: list[tuple[str, str]] = []
    index = 0
    if lines[0].strip() == "---":
        for close_index in range(1, len(lines)):
            if lines[close_index].strip() in {"---", "..."}:
                spans.append(("".join(lines[: close_index + 1]), "yaml"))
                index = close_index + 1
                break

    markdown: list[str] = []
    code: list[str] = []
    fence: str | None = None
    for line in lines[index:]:
        marker = _fence_marker(line)
        if fence is None:
            if marker is None:
                markdown.append(line)
                continue
            if markdown:
                spans.append(("".join(markdown), "markdown"))
                markdown = []
            code = [line]
            fence = marker
            continue

        code.append(line)
        if marker == fence:
            spans.append(("".join(code), "code"))
            code = []
            fence = None

    if code:
        spans.append(("".join(code), "code"))
    if markdown:
        spans.append(("".join(markdown), "markdown"))
    return tuple(spans) or ((text, "unknown"),)


def _fence_marker(line: str) -> str | None:
    stripped = line.lstrip()
    if stripped.startswith("```"):
        return "```"
    if stripped.startswith("~~~"):
        return "~~~"
    return None


def _estimate_span_tokens(text: str, kind: str | None) -> TokenEstimate:
    profile = _TOKEN_PROFILES.get(kind or "unknown", _TOKEN_PROFILES["unknown"])
    char_count = len(text)
    if char_count == 0:
        return TokenEstimate(estimate=0, low=0, high=0)
    return _token_estimate(
        estimate=_ceil_div(char_count, profile.estimate_chars_per_token),
        low=_ceil_div(char_count, profile.low_chars_per_token),
        high=_ceil_div(char_count, profile.high_chars_per_token),
    )


def _ceil_div(value: int, divisor: int) -> int:
    return max(1, (value + divisor - 1) // divisor)


def _sum_token_estimates(estimates: Iterable[TokenEstimate]) -> TokenEstimate:
    total_estimate = 0
    total_low = 0
    total_high = 0
    for estimate in estimates:
        total_estimate += estimate.estimate
        total_low += estimate.low
        total_high += estimate.high
    return _token_estimate(estimate=total_estimate, low=total_low, high=total_high)


def _token_estimate(*, estimate: int, low: int, high: int) -> TokenEstimate:
    central = max(0, estimate)
    lower = max(0, min(low, central, high))
    upper = max(0, max(low, central, high))
    return TokenEstimate(estimate=central, low=lower, high=upper)


def _input_token_estimate(
    estimate: int | None, *, low: int | None = None, high: int | None = None
) -> TokenEstimate:
    central = _nonnegative_int(estimate)
    lower = _nonnegative_int(low, default=central)
    upper = _nonnegative_int(high, default=central)
    return _token_estimate(estimate=central, low=lower, high=upper)


def _nonnegative_int(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return default


def _add_token_estimate_fields(
    payload: dict[str, Any], prefix: str, estimate: TokenEstimate
) -> None:
    payload[f"{prefix}_tokens_low_est"] = estimate.low
    payload[f"{prefix}_tokens_high_est"] = estimate.high


def _baseline_token_estimate(
    inputs: AccountingInputs, *, response_tokens: TokenEstimate
) -> TokenEstimate:
    if inputs.counterfactual_baseline == CounterfactualBaseline.MANIFEST_ONLY_CONTEXT:
        return _input_token_estimate(
            inputs.manifest_tokens_est,
            low=inputs.manifest_tokens_low_est,
            high=inputs.manifest_tokens_high_est,
        )
    if inputs.counterfactual_baseline == CounterfactualBaseline.COMPILER_SELECTED_CONTEXT:
        return response_tokens
    if inputs.full_context_tokens_est is not None:
        return _input_token_estimate(
            inputs.full_context_tokens_est,
            low=inputs.full_context_tokens_low_est,
            high=inputs.full_context_tokens_high_est,
        )
    return _input_token_estimate(
        inputs.manifest_tokens_est,
        low=inputs.manifest_tokens_low_est,
        high=inputs.manifest_tokens_high_est,
    )


def _baseline_tokens(inputs: AccountingInputs) -> int:
    return _baseline_token_estimate(
        inputs,
        response_tokens=estimate_tokens_with_bounds(inputs.response_payload),
    ).estimate


_SUMMARY_RANGE_FALLBACKS = {
    "actual_ambara_tokens_low_est": "actual_ambara_tokens_est",
    "actual_ambara_tokens_high_est": "actual_ambara_tokens_est",
    "counterfactual_tokens_low_est": "counterfactual_tokens_est",
    "counterfactual_tokens_high_est": "counterfactual_tokens_est",
    "net_savings_tokens_low_est": "net_savings_tokens_est",
    "net_savings_tokens_high_est": "net_savings_tokens_est",
}


def _summary_int(event: dict[str, Any], key: str) -> int:
    if key in event:
        return _int_value(event.get(key))
    fallback = _SUMMARY_RANGE_FALLBACKS.get(key)
    if fallback is not None:
        return _int_value(event.get(fallback))
    return 0


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
