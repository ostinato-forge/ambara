"""Shared guidance text used by read and write server helpers."""

from __future__ import annotations


def _write_request_examples() -> list[dict[str, str]]:
    return [
        {
            "developer_request": "Record this as a project decision.",
            "tool": "propose",
            "type": "decision",
            "why": (
                "durable project decisions require review before they become "
                "shared source-of-truth context"
            ),
        },
        {
            "developer_request": "Save this handoff for the next agent.",
            "tool": "record",
            "type": "active",
            "why": "short-lived handoffs belong on the active context path",
        },
        {
            "developer_request": "Capture this project update.",
            "tool": "record",
            "type": "project",
            "why": (
                "project updates are lightweight shared context, not reviewed decisions by default"
            ),
        },
    ]
