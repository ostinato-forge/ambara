"""Render startup packets as LLM-readable markdown for file-based context injection."""

from __future__ import annotations

from typing import Any


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
    lines.append('`jurati query "topic"` | `jurati read <entry-id>`')
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
