# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Local value-ledger helpers for the Ambara CLI.

Reads the local JSONL value ledger and renders savings receipts plus the
startup value event. Depends only on the core accounting and git config layers
(and a lazy ``cli_render`` import for cost formatting), never back on ``cli/__init__.py``.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import click

from ambara.core.context_accounting import (
    AccountingInputs,
    append_ledger_event,
    default_ledger_path,
    ledger_event,
    summary_windows,
)
from ambara.git.config import AmbaraConfig, load_value_cost_config_from_env


def _int_from_mapping(value: object, key: str, *, default: int | None = None) -> int | None:
    if not isinstance(value, dict):
        return default
    raw = value.get(key)
    if isinstance(raw, bool):
        return default
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    return default


def _value_ledger_path_from_env() -> Path:
    explicit = os.environ.get("AMBARA_VALUE_LEDGER_PATH")
    if explicit:
        return Path(explicit).expanduser()
    return default_ledger_path(
        os.environ.get("AMBARA_CACHE_DIR", os.path.expanduser("~/.cache/ambara"))
    )


def _value_ledger_path(cache_dir: str, configured_path: str | None) -> Path:
    if configured_path:
        return Path(configured_path).expanduser()
    return default_ledger_path(cache_dir)


def _resolve_value_price_from_env() -> tuple[float | None, str]:
    """Read the optional unit price + currency for monetary value estimates.

    Tokens are universal; money is not. Cost is only shown when a managed
    deployment supplies a price in its own currency, keeping the estimate honest
    and locale-appropriate for an international user base.
    """
    return load_value_cost_config_from_env()


def _write_startup_value_event(
    packet: dict[str, object],
    *,
    ledger_path: Path,
    budget_mode: str,
    now: datetime,
) -> None:
    more = packet.get("more") if isinstance(packet.get("more"), dict) else {}
    value = packet.get("value") if isinstance(packet.get("value"), dict) else {}
    full_context_tokens = None
    if isinstance(value, dict):
        packet_tokens = _int_from_mapping(value, "packet_tokens_est")
        saved_tokens = _int_from_mapping(value, "saved_tokens_est")
        if packet_tokens is not None and saved_tokens is not None:
            full_context_tokens = packet_tokens + saved_tokens
    entries = packet.get("entries")
    selected_entry_count = len(entries) if isinstance(entries, list) else 0
    entries_omitted = _int_from_mapping(more, "entries_omitted", default=0) or 0
    restricted_hidden = _int_from_mapping(more, "restricted_hidden", default=0) or 0
    duplicates_suppressed = _int_from_mapping(more, "duplicates_suppressed", default=0) or 0
    already_seen_suppressed = _int_from_mapping(more, "already_seen_suppressed", default=0) or 0
    user_muted_suppressed = _int_from_mapping(more, "user_muted_suppressed", default=0) or 0
    notices_omitted = _int_from_mapping(more, "notices_omitted", default=0) or 0
    deferred_body_count = _int_from_mapping(value, "deferred", default=0) or 0
    event = ledger_event(
        AccountingInputs(
            tool_name="startup",
            context_schema="startup-s2",
            client_surface="startup_file",
            budget_mode=budget_mode,
            response_payload=packet,
            eligible_candidate_count=selected_entry_count + entries_omitted,
            selected_entry_count=selected_entry_count,
            entries_omitted_count=entries_omitted,
            restricted_hidden_count=restricted_hidden,
            duplicates_suppressed_count=duplicates_suppressed,
            already_seen_suppressed_count=already_seen_suppressed,
            user_muted_suppressed_count=user_muted_suppressed,
            notices_omitted_count=notices_omitted,
            deferred_body_count=deferred_body_count,
            full_context_tokens_est=full_context_tokens,
        ),
        now=now,
    )
    append_ledger_event(ledger_path, event)


def _build_value_rollup(
    ledger_path: Path, config: AmbaraConfig, *, now: datetime
) -> dict[str, object] | None:
    """Compact 7-day savings rollup surfaced in the startup packet itself."""
    windows = summary_windows(
        ledger_path,
        now=now,
        price_per_million=config.value_price_per_million,
        currency=config.value_cost_currency,
    )
    week = windows.get("last_7_days", {})
    events = _int_from_mapping(week, "event_count", default=0) or 0
    if events <= 0:
        return None
    rollup: dict[str, object] = {
        "window": "last_7_days",
        "events": events,
        "net_savings_tokens_est": _int_from_mapping(week, "net_savings_tokens_est", default=0) or 0,
    }
    cost = week.get("net_savings_cost_est")
    currency = week.get("cost_currency")
    if isinstance(cost, int | float) and isinstance(currency, str):
        rollup["net_savings_cost_est"] = cost
        rollup["cost_currency"] = currency
    return rollup


def _print_value_window(label: str, window: dict[str, object]) -> None:
    events = _int_from_mapping(window, "event_count", default=0) or 0
    used = _int_from_mapping(window, "actual_ambara_tokens_est", default=0) or 0
    saved = _int_from_mapping(window, "net_savings_tokens_est", default=0) or 0
    skipped = _int_from_mapping(window, "entries_omitted_count", default=0) or 0
    repeats = _int_from_mapping(window, "already_seen_suppressed_count", default=0) or 0
    cost = window.get("net_savings_cost_est")
    currency = window.get("cost_currency")
    cost_str = ""
    if isinstance(cost, int | float) and isinstance(currency, str):
        from ambara.cli.render import format_cost

        cost_str = f" (~{format_cost(float(cost), currency)} saved)"
    click.echo(
        f"  {label}: {events} events, ~{used} Ambara tokens used, "
        f"~{saved} net tokens saved{cost_str}, {skipped} skipped, {repeats} repeats suppressed"
    )


def _print_value_explain(path: Path) -> None:
    click.echo("Ambara value accounting")
    click.echo(f"  ledger: {path}")
    click.echo("  storage: local JSONL; not written to the shared context repo by default")
    click.echo("  estimator: chars_div_4:v1")
    click.echo("  primary baseline: naive_full_eligible_context")
    click.echo("  secondary baseline: manifest_only_context")
    click.echo("  confidence: measured or bounded estimates from Ambara payload structure")
    click.echo("  scope: Ambara app payload only, not total client/session/cache billing")
    click.echo(
        "  privacy: no query text, response text, body snippets, caller identity, or read feed"
    )
