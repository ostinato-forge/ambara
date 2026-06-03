# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Coordination-signal assembly helpers for the MCP server."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ambara.core.context_rendering import sanitize_untrusted_signal_text
from ambara.core.pr_signals import (
    CoordinationGuidance,
    classify_signals,
)
from ambara.core.scope_policy import filter_signals
from ambara.server_scope import signal_config_for_mute
from ambara.server_signals import refresh_signal_cache
from ambara.server_state import ServerState
from ambara.server_types import BlockingRunner, SignalFetcher


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
                "title": sanitize_untrusted_signal_text(ev.title, field="title", max_chars=160),
                "state": ev.state,
                "updated_at": ev.updated_at.isoformat(),
                "merged_at": ev.merged_at.isoformat() if ev.merged_at else None,
                "matched_paths": list(ev.matched_paths),
                "changed_paths_status": ev.changed_paths_status,
                "body_excerpt": sanitize_untrusted_signal_text(
                    ev.body_excerpt, field="excerpt", max_chars=360
                ),
                "text_trust": "untrusted_external",
                "reason": ev.reason,
            }
            for ev in g.evidence
        ],
    }


async def build_coordination_payload(
    state: ServerState,
    *,
    repo: str | None,
    goal: str | None,
    paths: list[str] | None,
    now: datetime,
    fetch_signals: SignalFetcher,
    run_blocking: BlockingRunner,
    logger: logging.Logger,
) -> dict[str, Any]:
    cache = state.signal_cache
    config = state.config.pr_signals
    fetch_config = signal_config_for_mute(config, state.config.muted_scopes)

    if fetch_config != config and not fetch_config.repos and not fetch_config.jira_projects:
        cache.evict_stale(now=now)
    else:
        await refresh_signal_cache(
            state,
            config=fetch_config,
            now=now,
            fetch_signals=fetch_signals,
            run_blocking=run_blocking,
            logger=logger,
            failure_log_message="PR signal refresh failed; using cached data",
        )

    cached = filter_signals(cache.get_signals(), state.config.muted_scopes)
    if not cached:
        if (
            state.signal_health.last_failure is not None
            and state.signal_health.last_success is None
        ):
            return {
                "status": "unavailable",
                "summary": "Configured signal sources are unavailable.",
                "guidance": [],
                "agent_instruction": (
                    "Do not treat the absence of coordination signals as a green light."
                ),
                "privacy_boundary": _privacy_boundary(),
            }
        return {
            "status": "ok",
            "summary": "No ambara-labeled signals in configured sources.",
            "guidance": [],
            "privacy_boundary": _privacy_boundary(),
        }

    guidance = classify_signals(
        cached,
        repo=repo,
        _goal=goal,
        paths=paths,
        now=now,
        recency_days=config.recency_days,
    )

    active_effects = [g for g in guidance if g.effect != "continue"]
    summary = (
        f"{len(active_effects)} ambara-labeled PR(s) may affect this plan."
        if active_effects
        else f"{len(guidance)} ambara-labeled PR(s) noted; none affect current targets."
    )

    return {
        "status": "ok",
        "summary": summary,
        "guidance": [_format_guidance(g) for g in guidance],
        "privacy_boundary": _privacy_boundary(),
    }


def _privacy_boundary() -> list[str]:
    return [
        "only configured repos are checked",
        "only PRs carrying the configured ambara label are used",
        "unlabeled PRs, comments, chats, editor activity, and read activity are not mined",
        "PR author identities are not included in coordination signals",
    ]
