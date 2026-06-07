# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Render startup packets as LLM-readable markdown for file-based context injection."""

from __future__ import annotations

from typing import Any

# Symbols for the most common currencies; anything else renders as "<amount> CODE"
# so the rollup stays correct for an international user base.
_CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",
    "CAD": "$",
    "AUD": "$",
    "NZD": "$",
    "INR": "₹",
    "BRL": "R$",
    "CHF": "CHF ",
    "KRW": "₩",
}


def format_cost(amount: float, currency: str) -> str:
    """Format a monetary estimate with a currency-appropriate symbol."""
    code = currency.upper()
    symbol = _CURRENCY_SYMBOLS.get(code)
    if symbol:
        return f"{symbol}{amount:,.2f}"
    return f"{amount:,.2f} {code}"


def _value_rollup_line(rollup: dict[str, Any]) -> str:
    parts: list[str] = []
    tokens = rollup.get("net_savings_tokens_est")
    if isinstance(tokens, int):
        parts.append(f"~{tokens:,} tokens")
    cost = rollup.get("net_savings_cost_est")
    currency = rollup.get("cost_currency")
    if isinstance(cost, int | float) and isinstance(currency, str):
        parts.append(f"~{format_cost(float(cost), currency)}")
    if not parts:
        return ""
    events = rollup.get("events")
    suffix = f" across {events} context loads" if isinstance(events, int) else ""
    return " / ".join(parts) + suffix


def render_startup_markdown(packet: dict[str, Any]) -> str:
    lines: list[str] = []
    availability = packet.get("availability", "unknown")
    action = packet.get("action", "proceed")

    lines.append("# Team Context")
    lines.append("")
    lines.append(f"**Status:** {availability} | **Action:** {action}")

    reason = packet.get("reason")
    if reason:
        lines.append(f"**Note:** {reason}")

    value = packet.get("value")
    if isinstance(value, dict):
        receipt = _value_receipt_line(value)
        if receipt:
            lines.append(f"**Value:** {receipt}")

    rollup = packet.get("value_rollup")
    if isinstance(rollup, dict):
        rollup_line = _value_rollup_line(rollup)
        if rollup_line:
            lines.append(f"**Saved (7d):** {rollup_line}")

    source_health = packet.get("source_health")
    if isinstance(source_health, dict):
        source_health_lines = _source_health_lines(source_health)
        if source_health_lines:
            lines.append("")
            lines.append("## Source Health")
            lines.extend(source_health_lines)

    source_omissions = packet.get("source_omissions")
    if isinstance(source_omissions, dict):
        omission_lines = _source_omission_lines(source_omissions)
        if omission_lines:
            lines.append("")
            lines.append("## Source Omissions")
            lines.extend(omission_lines)

    constraints = packet.get("constraints", [])
    if constraints:
        lines.append("")
        lines.append("## Coordination")
        for c in constraints:
            effect = c.get("effect", "")
            summary = c.get("summary", "")
            lines.append(f"- **{effect}:** {summary}")

    entries = packet.get("entries", [])
    if entries:
        lines.append("")
        lines.append("## Active Work")
        for e in entries:
            eid = e.get("id", "?")
            etype = e.get("type", "?")
            title = e.get("title", "?")
            why = e.get("why", "")
            line = f"- **{eid}** ({etype}) — {title}"
            if why:
                line += f" [{why}]"
            lines.append(line)

    more = packet.get("more", {})
    omitted = more.get("entries_omitted", 0)
    restricted = more.get("restricted_hidden", 0)
    if omitted or restricted:
        parts = []
        if omitted:
            parts.append(f"{omitted} more entries available")
        if restricted:
            parts.append(f"{restricted} restricted entries hidden")
        lines.append(f"*({'; '.join(parts)})*")

    lines.append("")
    lines.append("## Dig deeper")
    lines.append('`ambara query "topic"` | `ambara read <entry-id>`')
    lines.append("")
    return "\n".join(lines)


def _value_receipt_line(value: dict[str, Any]) -> str:
    parts: list[str] = []
    packet_tokens = value.get("packet_tokens_est")
    if isinstance(packet_tokens, int):
        parts.append(f"used ~{packet_tokens} context tokens")
    skipped = value.get("skipped")
    if isinstance(skipped, int) and skipped > 0:
        parts.append(f"skipped {skipped}")
    suppressed = value.get("suppressed")
    if isinstance(suppressed, int) and suppressed > 0:
        parts.append(f"suppressed {suppressed}")
    deferred = value.get("deferred")
    if isinstance(deferred, int) and deferred > 0:
        parts.append(f"deferred {deferred} full bodies")
    saved = value.get("saved_tokens_est")
    if isinstance(saved, int) and saved > 0:
        parts.append(f"avoided ~{saved} tokens")
    if not parts:
        return ""
    mode = value.get("mode")
    suffix = f" Mode: {mode}." if isinstance(mode, str) and mode else ""
    return ", ".join(parts) + f".{suffix}"


def _source_health_lines(source_health: dict[str, Any]) -> list[str]:
    summary = _source_health_summary(source_health)
    if not summary:
        return []

    lines = [f"- {summary}. Run `ambara sources doctor` for details."]
    sources = source_health.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            source_id = source.get("id")
            provider = source.get("provider")
            status = source.get("status")
            if not all(isinstance(value, str) for value in (source_id, provider, status)):
                continue
            baseline = (
                "cached baseline available"
                if source.get("baseline_available") is True
                else "no successful baseline"
            )
            lines.append(f"- **{source_id}** ({provider}) - {status}; {baseline}")
    omitted = source_health.get("omitted")
    if isinstance(omitted, int) and omitted > 0:
        lines.append(f"- {omitted} more degraded source(s) omitted from startup.")
    return lines


def _source_health_summary(source_health: dict[str, Any]) -> str:
    configured = source_health.get("configured")
    if not isinstance(configured, int) or configured <= 0:
        return ""

    parts: list[str] = []
    for key in ("unavailable", "error", "stale"):
        count = source_health.get(key)
        if isinstance(count, int) and count > 0:
            label = key.replace("_", " ")
            parts.append(f"{count} {label}")
    if not parts:
        return ""

    fresh = source_health.get("fresh")
    fresh_text = f"; {fresh} fresh" if isinstance(fresh, int) and fresh > 0 else ""
    return f"{', '.join(parts)} across {configured} configured source(s){fresh_text}"


def _source_omission_lines(source_omissions: dict[str, Any]) -> list[str]:
    total = source_omissions.get("total")
    if not isinstance(total, int) or total <= 0:
        return []

    parts: list[str] = []
    for key in ("privacy", "safety", "budget", "freshness", "source_error"):
        count = source_omissions.get(key)
        if isinstance(count, int) and count > 0:
            parts.append(f"{key.replace('_', ' ')}: {count}")
    detail = f" ({', '.join(parts)})" if parts else ""
    return [
        f"- {total} source input omission(s) applied before startup rendering{detail}."
    ]
