"""Content policy evaluation and response helpers for the MCP server."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from jurati.core.content_policy import (
    CallerScope,
    PolicyAction,
    PolicySubject,
    PolicyVerdict,
)
from jurati.core.schema import EntryType, EscalationLevel, Sensitivity, Visibility
from jurati.server_state import ServerState


def evaluate_content_policy(
    state: ServerState,
    *,
    source: str,
    title: str,
    content: str,
    entry_type: EntryType | None = None,
    level: EscalationLevel | None = None,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    visibility: Visibility | None = None,
    sensitivity: Sensitivity | None = None,
) -> PolicyVerdict | None:
    if state.content_policy is None:
        return None

    subject = PolicySubject(
        source=source,  # type: ignore[arg-type]
        title=title,
        body=content,
        entry_type=entry_type,
        level=level,
        projects=tuple(projects or []),
        tags=tuple(tags or []),
        visibility=visibility,
        sensitivity=sensitivity,
    )
    verdict = state.content_policy.evaluate(subject, CallerScope(), now=datetime.now(UTC))

    if verdict.action == PolicyAction.ALLOW and not verdict.rule_ids:
        return None

    return verdict


def content_policy_block_response(verdict: PolicyVerdict) -> dict[str, Any]:
    return {
        "status": "error",
        "error": "content_policy_block",
        "what_happened": verdict.message,
        "agent_instruction": (
            "Do not retry with the same content. Do not obfuscate the content. "
            "Ask the developer for a safe summary without the sensitive material."
        ),
        "policy_rules": list(verdict.rule_ids),
    }


def content_policy_review_required_response(verdict: PolicyVerdict) -> dict[str, Any]:
    return {
        "status": "error",
        "error": "content_policy_requires_review",
        "what_happened": verdict.message,
        "agent_instruction": (
            "This content requires human review, so it cannot be written as instant "
            "active context. Propose durable reviewed knowledge, or ask for a safe "
            "handoff summary without the review-triggering material."
        ),
        "policy_rules": list(verdict.rule_ids),
    }


def content_policy_metadata(verdict: PolicyVerdict | None) -> dict[str, Any] | None:
    if verdict is None or not verdict.rule_ids:
        return None
    return {
        "action": str(verdict.action),
        "policy_rules": list(verdict.rule_ids),
        "labels": list(verdict.review_labels),
        "warning": verdict.warning,
    }


def content_policy_labels(verdict: PolicyVerdict | None) -> list[str]:
    if verdict is None:
        return []
    return list(verdict.review_labels)
