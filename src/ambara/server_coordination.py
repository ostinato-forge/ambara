# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Coordination-signal assembly helpers for the MCP server."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from ambara.core.context_rendering import sanitize_untrusted_source_text
from ambara.core.pr_signals import (
    CoordinationGuidance,
    SourceInputLike,
    classify_source_inputs,
)
from ambara.server_scope import source_config_for_mute
from ambara.server_signals import refresh_source_inputs
from ambara.server_source_inputs import source_inputs_for_state
from ambara.server_state import ServerState
from ambara.server_types import BlockingRunner, LegacySignalFetcher


def _format_guidance(g: CoordinationGuidance) -> dict[str, Any]:
    return {
        "effect": g.effect,
        "urgency": g.urgency,
        "summary": g.summary,
        "instruction": g.instruction,
        "confidence": g.confidence,
        "evidence": [
            {
                "repo": ev.repo,
                "number": ev.number,
                "url": ev.url,
                "title": sanitize_untrusted_source_text(ev.title, field="title", max_chars=160),
                "state": ev.state,
                "updated_at": ev.updated_at.isoformat(),
                "merged_at": ev.merged_at.isoformat() if ev.merged_at else None,
                "matched_paths": list(ev.matched_paths),
                "changed_paths_status": ev.changed_paths_status,
                "body_excerpt": sanitize_untrusted_source_text(
                    ev.body_excerpt, field="excerpt", max_chars=360
                ),
                "text_trust": "untrusted_external",
                "reason": ev.reason,
            }
            for ev in g.evidence
        ],
    }


def build_coordination_payload_from_source_inputs(
    source_inputs: Sequence[SourceInputLike],
    *,
    repo: str | None,
    goal: str | None,
    paths: list[str] | None,
    now: datetime,
    recency_days: int,
) -> dict[str, Any]:
    """Build compact coordination guidance from already-fetched source inputs."""

    if not source_inputs:
        return {
            "status": "ok",
            "summary": "No ambara-labeled source inputs in configured sources.",
            "guidance": [],
            "privacy_boundary": _privacy_boundary(),
        }

    guidance = classify_source_inputs(
        source_inputs,
        repo=repo,
        _goal=goal,
        paths=paths,
        now=now,
        recency_days=recency_days,
    )

    active_effects = [g for g in guidance if g.effect != "continue"]
    summary = (
        f"{len(active_effects)} ambara-labeled source input(s) may affect this plan."
        if active_effects
        else f"{len(guidance)} ambara-labeled source input(s) noted; none affect current targets."
    )

    return {
        "status": "ok",
        "summary": summary,
        "guidance": [_format_guidance(g) for g in guidance],
        "privacy_boundary": _privacy_boundary(),
    }


async def build_coordination_payload(
    state: ServerState,
    *,
    repo: str | None,
    goal: str | None,
    paths: list[str] | None,
    now: datetime,
    run_blocking: BlockingRunner,
    logger: logging.Logger,
    fetch_signals: LegacySignalFetcher | None = None,
) -> dict[str, Any]:
    cache = state.legacy_signal_cache
    config = state.config.source_inputs
    fetch_config = source_config_for_mute(config, state.config.muted_scopes)

    if fetch_config != config and not fetch_config.repos and not fetch_config.jira_projects:
        cache.evict_stale(now=now)
    else:
        await refresh_source_inputs(
            state,
            config=fetch_config,
            now=now,
            fetch_signals=fetch_signals,
            run_blocking=run_blocking,
            logger=logger,
            failure_log_message="Source input refresh failed; using cached data",
        )

    source_inputs = source_inputs_for_state(state)
    if not source_inputs:
        if (
            state.source_health.last_failure is not None
            and state.source_health.last_success is None
        ):
            return {
                "status": "unavailable",
                "summary": "Configured source inputs are unavailable.",
                "guidance": [],
                "agent_instruction": (
                    "Do not treat the absence of coordination source inputs as a green light."
                ),
                "privacy_boundary": _privacy_boundary(),
            }
        return {
            "status": "ok",
            "summary": "No ambara-labeled source inputs in configured sources.",
            "guidance": [],
            "privacy_boundary": _privacy_boundary(),
        }

    return build_coordination_payload_from_source_inputs(
        source_inputs,
        repo=repo,
        goal=goal,
        paths=paths,
        now=now,
        recency_days=config.recency_days,
    )


def _privacy_boundary() -> list[str]:
    return [
        "only configured repos are checked",
        "only source inputs carrying the configured ambara label are used",
        "unlabeled reviews, comments, chats, editor activity, and read activity are not mined",
        "source actor identities are not included in coordination source inputs",
    ]
