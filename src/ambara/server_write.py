# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Write-side response shaping and advisory helpers for the MCP server."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ambara.core.changes import WriteIntent
from ambara.core.dedup import ConflictEntry, WriteConflicts, check_write_conflicts
from ambara.core.index import Index
from ambara.core.schema import EntryType, EscalationLevel, Visibility
from ambara.server_guidance import _write_request_examples

_DEVELOPER_RESPONSE_INSTRUCTION = (
    "For developer-facing replies, use developer_confirmation or write one "
    "equivalent sentence about the work. Unless debugging was explicitly "
    "requested, do not mention entry IDs, ref paths, expiry mechanics, branch "
    "names, knowledge repo lifecycle, sync, or PR chores."
)

_DEBUG_ONLY_FIELDS = [
    "entry_id",
    "write_advisories",
    "active_ref",
    "branch",
    "pr_url",
    "pr_number",
    "review_url",
    "commit",
]

_WRITE_PATH_GUIDANCE = (
    "Translate the developer's normal request into the right write path. Do not "
    "ask them to choose between record() and propose() or to name entry levels."
)


def _agent_guidance(default_reply: str) -> dict[str, Any]:
    return {
        "default_reply": default_reply,
        "developer_reply": _DEVELOPER_RESPONSE_INSTRUCTION,
        "debug_only_fields": _DEBUG_ONLY_FIELDS,
        "follow_up": (
            "For follow-up questions about team state, call query() "
            "rather than exploring locally with git or grep."
        ),
    }


def _write_path_error(
    *,
    message: str,
    correction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": message,
        "agent_guidance": {
            "write_path": _WRITE_PATH_GUIDANCE,
            "request_mapping": _write_request_examples(),
        },
    }
    if correction is not None:
        payload["suggested_write_path"] = correction
    return payload


def _record_correction(
    *,
    entry_type: EntryType,
    level: EscalationLevel | None,
    title: str,
    content: str,
    entry_id: str,
    projects: list[str] | None,
    tags: list[str] | None,
    visibility: Visibility | None,
) -> dict[str, Any] | None:
    if entry_type in (EntryType.DECISION, EntryType.WORKFLOW, EntryType.PRINCIPLE) or level in (
        EscalationLevel.L2,
        EscalationLevel.L3,
    ):
        return {
            "tool": "propose",
            "arguments": {
                "type": str(entry_type),
                "title": title,
                "content": content,
                "entry_id": entry_id,
                "level": str(level) if level is not None else None,
                "projects": projects or [],
                "tags": tags or [],
                "visibility": str(visibility) if visibility is not None else None,
            },
            "why": "durable decisions, workflows, and principles go through the reviewed path",
        }
    return None


def _propose_correction(
    *,
    entry_type: EntryType,
    level: EscalationLevel | None,
    title: str,
    content: str,
    entry_id: str,
    projects: list[str] | None,
    tags: list[str] | None,
    visibility: Visibility | None,
) -> dict[str, Any] | None:
    if entry_type == EntryType.ACTIVE or level in (EscalationLevel.L0, EscalationLevel.L1):
        return {
            "tool": "record",
            "arguments": {
                "type": str(entry_type),
                "title": title,
                "content": content,
                "entry_id": entry_id,
                "level": str(level) if level is not None else None,
                "projects": projects or [],
                "tags": tags or [],
                "visibility": str(visibility) if visibility is not None else None,
            },
            "why": (
                "short-lived handoffs and lightweight project updates belong on the record path"
            ),
        }
    return None


def _write_receipt(
    *,
    entry_id: str,
    write_mode: str,
    commit: str | None = None,
    branch: str | None = None,
    active_ref: str | None = None,
    pr_url: str | None = None,
    pr_number: int | None = None,
) -> dict[str, Any]:
    if write_mode == "active_ref":
        confirmation = "Recorded the current work update."
        return {
            "developer_confirmation": confirmation,
            "agent_guidance": _agent_guidance(confirmation),
            "what_happened": confirmation,
            "visibility": "Current work context was captured.",
            "next_step": "No developer action needed.",
            "active_ref": active_ref,
            "commit": commit,
        }

    if write_mode == "lightweight_pr":
        confirmation = "Recorded the project update."
        return {
            "developer_confirmation": confirmation,
            "agent_guidance": _agent_guidance(confirmation),
            "what_happened": confirmation,
            "visibility": "The update is queued for normal review.",
            "next_step": "No developer action needed.",
            "branch": branch,
            "pr_url": pr_url,
            "pr_number": pr_number,
            "commit": commit,
        }

    if write_mode == "branch_only":
        confirmation = "Saved the update on a review branch. No pull request was created."
        return {
            "developer_confirmation": confirmation,
            "agent_guidance": _agent_guidance(confirmation),
            "what_happened": confirmation,
            "visibility": "A review branch is ready, but no pull request was opened.",
            "next_step": "No developer action needed.",
            "branch": branch,
            "review_url": pr_url,
            "commit": commit,
        }

    confirmation = "Submitted the update for team review."
    return {
        "developer_confirmation": confirmation,
        "agent_guidance": _agent_guidance(confirmation),
        "what_happened": confirmation,
        "visibility": "The update is queued for team review.",
        "next_step": "No developer action needed.",
        "branch": branch,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "commit": commit,
    }


def _format_conflict_entry(item: ConflictEntry) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "type": str(item.type),
        "status": str(item.status),
        "path": item.path,
        "reason": item.reason,
    }


def _format_write_advisories(conflicts: WriteConflicts) -> dict[str, Any] | None:
    if not conflicts.has_conflicts:
        return None
    return {
        "agent_instruction": (
            "Review these advisories before creating more knowledge. If a duplicate "
            "already captures the point, avoid repeating it; if stale active context "
            "no longer applies, expire it silently."
        ),
        "duplicates": [_format_conflict_entry(item) for item in conflicts.duplicates],
        "expired_active": [_format_conflict_entry(item) for item in conflicts.expired_active],
        "stale_proposed": [_format_conflict_entry(item) for item in conflicts.stale_proposed],
    }


def _write_advisories_for_intent(
    index: Index,
    intent: WriteIntent,
    *,
    now: datetime,
) -> dict[str, Any] | None:
    if intent.entry is None:
        return None
    conflicts = check_write_conflicts(
        index,
        title=intent.entry.frontmatter.title,
        entry_type=intent.entry.frontmatter.type,
        projects=intent.entry.frontmatter.projects,
        now=now,
    )
    return _format_write_advisories(conflicts)


def _expire_receipt(
    *,
    entry_id: str,
    write_mode: str,
    commit: str | None = None,
    branch: str | None = None,
    active_ref: str | None = None,
    pr_url: str | None = None,
    pr_number: int | None = None,
) -> dict[str, Any]:
    if write_mode == "active_ref":
        confirmation = "Cleared the stale context."
        return {
            "developer_confirmation": confirmation,
            "agent_guidance": _agent_guidance(confirmation),
            "what_happened": confirmation,
            "visibility": "The stale context was removed from the current view.",
            "next_step": "No developer action needed.",
            "active_ref": active_ref,
            "commit": commit,
        }

    if write_mode == "branch_only":
        confirmation = "Saved the cleanup on a review branch. No pull request was created."
        return {
            "developer_confirmation": confirmation,
            "agent_guidance": _agent_guidance(confirmation),
            "what_happened": confirmation,
            "visibility": "A cleanup review branch is ready, but no pull request was opened.",
            "next_step": "No developer action needed.",
            "branch": branch,
            "review_url": pr_url,
            "commit": commit,
        }

    confirmation = "Submitted the cleanup for review."
    return {
        "developer_confirmation": confirmation,
        "agent_guidance": _agent_guidance(confirmation),
        "what_happened": confirmation,
        "visibility": "The cleanup is queued for team review.",
        "next_step": "No developer action needed.",
        "branch": branch,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "commit": commit,
    }
