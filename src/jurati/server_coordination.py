"""Coordination-signal assembly helpers for the MCP server."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any

from jurati.core.context_rendering import sanitize_untrusted_signal_text
from jurati.core.pr_signals import (
    CoordinationGuidance,
    CoordinationSignal,
    PRSignal,
    classify_signals,
)
from jurati.git.config import PRSignalsConfig
from jurati.server_state import ServerState

SignalFetcher = Callable[[PRSignalsConfig], Sequence[PRSignal | CoordinationSignal]]
BlockingRunner = Callable[
    [Callable[[], Sequence[PRSignal | CoordinationSignal]]],
    Awaitable[Sequence[PRSignal | CoordinationSignal]],
]


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
                "author": ev.author,
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

    if cache.needs_refresh(now):
        try:
            signals = await run_blocking(lambda: fetch_signals(config))
            cache.update(signals, now=now)
        except Exception:
            logger.warning("PR signal refresh failed; using cached data", exc_info=True)

    cached = cache.get_signals()
    if not cached:
        return {
            "status": "ok",
            "summary": "No jurati-labeled signals in configured sources.",
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
        f"{len(active_effects)} jurati-labeled PR(s) may affect this plan."
        if active_effects
        else f"{len(guidance)} jurati-labeled PR(s) noted; none affect current targets."
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
        "only PRs carrying the configured jurati label are used",
        "unlabeled PRs, comments, chats, editor activity, and read activity are not mined",
    ]
