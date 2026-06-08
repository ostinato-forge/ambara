# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Curation-advisory assembly helpers for the MCP server."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ambara.core.context_rendering import (
    safe_artifact_ref,
    sanitize_source_paths,
    sanitize_untrusted_source_text,
)
from ambara.core.curation import CurationAdvisory, suggest_revalidation_from_source_inputs
from ambara.core.hygiene import HygieneItem, summarize_lifecycle
from ambara.core.index import Index
from ambara.core.schema import EntryStatus, Sensitivity
from ambara.core.scope_policy import filter_entries
from ambara.core.scoring import tokenize
from ambara.server_scope import source_config_for_mute
from ambara.server_signals import refresh_source_inputs, source_inputs_configured
from ambara.server_source_inputs import source_inputs_for_state
from ambara.server_state import ServerState
from ambara.server_types import BlockingRunner


async def build_curation_payload(
    state: ServerState,
    *,
    now: datetime,
    include_source_inputs: bool | None = None,
    include_signals: bool | None = None,
    repo: str | None = None,
    goal: str | None = None,
    max_items: int = 5,
    run_blocking: BlockingRunner,
    logger: logging.Logger,
) -> dict[str, Any] | None:
    unmuted_entries = filter_entries(
        tuple(state.index.entries.values()),
        state.config.muted_scopes,
    )
    visible_entries = [
        entry
        for entry in unmuted_entries
        if entry.frontmatter.sensitivity != Sensitivity.RESTRICTED
        and entry.frontmatter.status not in (EntryStatus.EXPIRED, EntryStatus.SUPERSEDED)
    ]
    visible_index = Index({entry.frontmatter.id: entry for entry in visible_entries})
    report = summarize_lifecycle(visible_index, now=now, stale_after_days=90)
    visible_entry_ids = {entry.frontmatter.id for entry in visible_entries}
    visible_entry_by_id = {entry.frontmatter.id: entry for entry in visible_entries}
    goal_terms = set(tokenize(goal or ""))
    expired_active = [
        item
        for item in report.expired_active
        if item.id in visible_entry_ids
        and _entry_matches_context(visible_entry_by_id[item.id], repo=repo, goal_terms=goal_terms)
    ]
    revalidation_due = [
        item
        for item in report.revalidation
        if item.id in visible_entry_ids
        and _entry_matches_context(visible_entry_by_id[item.id], repo=repo, goal_terms=goal_terms)
    ]
    source_advisories: list[CurationAdvisory] = []
    source_inputs_enabled = _source_inputs_enabled(
        include_source_inputs=include_source_inputs,
        include_signals=include_signals,
    )

    source_config = source_config_for_mute(state.config.source_inputs, state.config.muted_scopes)
    if source_inputs_enabled and source_inputs_configured(source_config):
        await refresh_source_inputs(
            state,
            config=source_config,
            now=now,
            run_blocking=run_blocking,
            logger=logger,
            failure_log_message="Curation source input refresh failed; using cached data",
        )
        source_inputs = source_inputs_for_state(state)

        if (
            not source_inputs
            and state.source_health.last_failure is not None
            and state.source_health.last_success is None
        ):
            return {
                "status": "unavailable",
                "summary": "Configured source inputs are unavailable for curation checks.",
                "total_advisories": 0,
                "shown_advisories": 0,
                "omitted_advisories": 0,
                "agent_instruction": (
                    "Do not treat missing source-derived curation as a clean result."
                ),
                "expired_active": [],
                "revalidation_due": [],
                "completed_artifact_revalidation": [],
                "privacy_boundary": _curation_privacy_boundary(),
            }

        source_advisories = suggest_revalidation_from_source_inputs(
            visible_entries,
            source_inputs,
            now=now,
            recency_days=source_config.recency_days,
        )
        source_advisories = [
            advisory
            for advisory in source_advisories
            if _advisory_matches_context(
                advisory,
                visible_entry_by_id,
                repo=repo,
                goal_terms=goal_terms,
            )
        ]

    if not expired_active and not revalidation_due and not source_advisories:
        return None

    total = len(expired_active) + len(revalidation_due) + len(source_advisories)
    expired_slice = expired_active[:max_items]
    revalidation_slice = revalidation_due[: max(0, max_items - len(expired_slice))]
    advisory_slice = source_advisories[
        : max(0, max_items - len(expired_slice) - len(revalidation_slice))
    ]
    shown = len(expired_slice) + len(revalidation_slice) + len(advisory_slice)
    return {
        "status": "ok",
        "summary": _curation_summary(total),
        "total_advisories": total,
        "shown_advisories": shown,
        "omitted_advisories": max(0, total - shown),
        "agent_instruction": (
            "Use these advisories as quiet planning cautions. Verify affected entries "
            "when they matter to the task; do not ask the developer to manage Ambara "
            "lifecycle mechanics."
        ),
        "expired_active": [_format_expired_active_item(item) for item in expired_slice],
        "revalidation_due": [_format_revalidation_item(item) for item in revalidation_slice],
        "completed_artifact_revalidation": [
            _format_curation_advisory(advisory) for advisory in advisory_slice
        ],
        "privacy_boundary": _curation_privacy_boundary(),
    }


def _curation_summary(total: int) -> str:
    if total == 1:
        return (
            "1 knowledge advisory needs attention before agents keep treating entries as current."
        )
    return (
        f"{total} knowledge advisories need attention before agents keep treating "
        "entries as current."
    )


def _format_expired_active_item(item: HygieneItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "type": str(item.type),
        "status": str(item.status),
        "path": item.path,
        "updated_at": item.updated_at.isoformat(),
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "reason": item.reason,
        "agent_instruction": (
            "Treat this active context as expired and do not rely on it unless current "
            "repo state independently confirms it; do not ask the developer to manage "
            "Ambara lifecycle mechanics."
        ),
    }


def _format_revalidation_item(item: HygieneItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "type": str(item.type),
        "status": str(item.status),
        "path": item.path,
        "updated_at": item.updated_at.isoformat(),
        "review_after": item.review_after.isoformat() if item.review_after else None,
        "reason": item.reason,
        "agent_instruction": item.next_step,
    }


def _format_curation_advisory(advisory: CurationAdvisory) -> dict[str, Any]:
    return {
        "entry_id": advisory.entry_id,
        "entry_title": advisory.entry_title,
        "entry_type": str(advisory.entry_type),
        "suggested_action": advisory.suggested_action,
        "reason": advisory.reason,
        "signal_source": sanitize_untrusted_source_text(
            advisory.source_input_source,
            field="title",
            max_chars=120,
        ),
        "artifact_ref": safe_artifact_ref(advisory.artifact_ref),
        "artifact_title": sanitize_untrusted_source_text(
            advisory.artifact_title,
            field="title",
            max_chars=160,
        ),
        "changed_paths": list(sanitize_source_paths(advisory.changed_paths, max_paths=5)),
        "matched_terms": list(advisory.matched_terms),
        "merged_at": advisory.merged_at.isoformat(),
        "text_trust": "untrusted_external",
        "agent_instruction": (
            "Revalidate this entry before relying on it for the current task; do not "
            "surface Ambara lifecycle mechanics unless the curation itself is the task."
        ),
    }


def _curation_privacy_boundary() -> list[str]:
    return [
        "based only on repo-owned entry metadata and configured labeled source inputs",
        "does not use query logs, read receipts, editor activity, or participation data",
        "does not infer absence, installation status, or teammate activity",
    ]


def _source_inputs_enabled(
    *,
    include_source_inputs: bool | None,
    include_signals: bool | None,
) -> bool:
    if include_source_inputs is not None:
        return include_source_inputs
    return bool(include_signals)


def _entry_matches_context(
    entry: Any,
    *,
    repo: str | None,
    goal_terms: set[str],
) -> bool:
    if repo is None and not goal_terms:
        return True

    fm = entry.frontmatter
    if repo is not None and repo in fm.projects:
        return True

    entry_terms: set[str] = set(tokenize(fm.title))
    for value in (*fm.projects, *fm.tags):
        entry_terms.update(tokenize(value))
    return bool(goal_terms and entry_terms.intersection(goal_terms))


def _advisory_matches_context(
    advisory: CurationAdvisory,
    entries_by_id: dict[str, Any],
    *,
    repo: str | None,
    goal_terms: set[str],
) -> bool:
    if repo is not None and advisory.source_input_source == repo:
        return True

    entry = entries_by_id.get(advisory.entry_id)
    if entry is None:
        return False
    return _entry_matches_context(entry, repo=repo, goal_terms=goal_terms)
