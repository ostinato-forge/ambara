# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Local value accounting and relevance feedback helpers for the MCP server."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ambara.core.context_accounting import (
    AccountingInputs,
    append_ledger_event,
    default_ledger_path,
    estimate_tokens,
    ledger_event,
    ledger_event_from_accounting,
    prune_ledger,
)
from ambara.server_state import ServerState

logger = logging.getLogger(__name__)

VALID_FEEDBACK_SIGNALS = {
    "not_useful",
    "duplicate",
    "stale",
    "useful",
    "pin",
    "mute_for_repo",
    "mute_for_session",
}


def _value_ledger_path_for_state(state: ServerState) -> Path:
    if state.config.value_ledger_path:
        return Path(state.config.value_ledger_path).expanduser()
    return default_ledger_path(state.config.cache_dir)


def _append_value_ledger_event(state: ServerState, event: dict[str, Any]) -> None:
    if not state.config.value_ledger_enabled:
        return
    path = _value_ledger_path_for_state(state)
    try:
        append_ledger_event(path, event)
        prune_ledger(path, retention_days=state.config.value_ledger_retention_days)
    except Exception:
        logger.exception("Could not append Ambara value ledger event")


def _record_packet_value_event(
    state: ServerState,
    *,
    tool_name: str,
    context_schema: str,
    payload: dict[str, Any],
    now: datetime,
) -> None:
    accounting = payload.get("cost_accounting")
    if isinstance(accounting, dict):
        _append_value_ledger_event(state, ledger_event_from_accounting(accounting, now=now))
        return

    more = payload.get("more") if isinstance(payload.get("more"), dict) else {}
    value = payload.get("value") if isinstance(payload.get("value"), dict) else {}
    full_context_tokens = None
    if isinstance(value, dict):
        packet_tokens = _int_from_mapping(value, "packet_tokens_est")
        saved_tokens = _int_from_mapping(value, "saved_tokens_est")
        if packet_tokens is not None and saved_tokens is not None:
            full_context_tokens = packet_tokens + saved_tokens
    selected_count = _packet_entry_count(payload)
    event = ledger_event(
        AccountingInputs(
            tool_name=tool_name,
            context_schema=context_schema,
            budget_mode=state.config.context_budget_mode,
            response_payload=payload,
            eligible_candidate_count=selected_count
            + (_int_from_mapping(more, "entries_omitted", default=0) or 0),
            selected_entry_count=selected_count,
            entries_omitted_count=_int_from_mapping(more, "entries_omitted", default=0) or 0,
            restricted_hidden_count=_int_from_mapping(more, "restricted_hidden", default=0) or 0,
            duplicates_suppressed_count=(
                _int_from_mapping(more, "duplicates_suppressed", default=0) or 0
            ),
            already_seen_suppressed_count=(
                _int_from_mapping(more, "already_seen_suppressed", default=0) or 0
            ),
            user_muted_suppressed_count=(
                _int_from_mapping(more, "user_muted_suppressed", default=0) or 0
            ),
            notices_omitted_count=_int_from_mapping(more, "notices_omitted", default=0) or 0,
            deferred_body_count=_int_from_mapping(value, "deferred", default=0) or 0,
            full_context_tokens_est=full_context_tokens,
        ),
        now=now,
    )
    _append_value_ledger_event(state, event)


def _record_read_many_value_event(
    state: ServerState, *, result: list[dict[str, Any]], now: datetime
) -> None:
    read_body_count = sum(1 for item in result if isinstance(item, dict) and "body" in item)
    event = ledger_event(
        AccountingInputs(
            tool_name="read_many",
            context_schema="read-many-v1",
            budget_mode=state.config.context_budget_mode,
            response_payload=result,
            selected_entry_count=len(result),
            read_body_count=read_body_count,
            full_context_tokens_est=estimate_tokens(result),
            counterfactual_baseline="compiler_selected_context",
        ),
        now=now,
    )
    _append_value_ledger_event(state, event)


def _recently_seen_ids(state: ServerState, *, now: datetime) -> set[str]:
    if state.config.context_budget_mode == "deep":
        return set()
    ttl = (
        timedelta(hours=24)
        if state.config.context_budget_mode == "quiet"
        else timedelta(minutes=30)
    )
    cutoff = now - ttl
    expired = [
        entry_id for entry_id, seen_at in state.seen_context_entries.items() if seen_at < cutoff
    ]
    for entry_id in expired:
        state.seen_context_entries.pop(entry_id, None)
    return set(state.seen_context_entries)


def _feedback_suppressed_ids(state: ServerState) -> set[str]:
    feedback_signals = {**state.config.entry_feedback, **state.feedback_signals}
    return {
        entry_id
        for entry_id, signal in feedback_signals.items()
        if signal in {"not_useful", "duplicate", "stale", "mute_for_repo", "mute_for_session"}
    }


def _pinned_ids(state: ServerState) -> set[str]:
    feedback_signals = {**state.config.entry_feedback, **state.feedback_signals}
    return {entry_id for entry_id, signal in feedback_signals.items() if signal == "pin"}


def _mark_payload_entries_seen(
    state: ServerState, payload: dict[str, Any], *, now: datetime
) -> None:
    for entry_id in _payload_entry_ids(payload):
        state.seen_context_entries[entry_id] = now


def _record_feedback_signal(
    state: ServerState, *, entry_id: str, signal: str, scope: str
) -> dict[str, Any]:
    normalized = signal.strip().lower().replace("-", "_")
    if normalized not in VALID_FEEDBACK_SIGNALS:
        return {
            "error": "invalid_feedback_signal",
            "valid_signals": sorted(VALID_FEEDBACK_SIGNALS),
        }
    if normalized == "useful":
        state.feedback_signals.pop(entry_id, None)
    else:
        state.feedback_signals[entry_id] = normalized
    return {
        "status": "ok",
        "entry_id": entry_id,
        "signal": normalized,
        "scope": scope,
        "storage": "process_local",
        "privacy_boundary": [
            "does not store query text",
            "does not store response bodies",
            "does not create durable read receipts",
        ],
    }


def _payload_entry_ids(payload: dict[str, Any]) -> tuple[str, ...]:
    ids: list[str] = []
    for key in ("entries", "active", "recent", "relevant_entries"):
        raw_items = payload.get(key)
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                ids.append(item["id"])
    return tuple(ids)


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


def _packet_entry_count(payload: dict[str, Any]) -> int:
    if isinstance(payload.get("entries"), list):
        return len(payload["entries"])
    count = 0
    for key in ("active", "recent", "relevant_entries"):
        if isinstance(payload.get(key), list):
            count += len(payload[key])
    return count
