"""Derived context snapshot assembly for compiler-mode context."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any

from jurati.core.curation import suggest_revalidation_from_signals
from jurati.core.hygiene import summarize_lifecycle
from jurati.core.index import Index
from jurati.core.pr_signals import CoordinationSignal, PRSignal, classify_signals
from jurati.core.schema import Sensitivity
from jurati.core.scoring import build_inverted_index, tokenize
from jurati.git.config import PRSignalsConfig
from jurati.server_coordination import _format_guidance, _privacy_boundary
from jurati.server_curation import (
    _advisory_matches_context,
    _curation_privacy_boundary,
    _curation_summary,
    _entry_matches_context,
    _format_curation_advisory,
    _format_expired_active_item,
    _format_revalidation_item,
    _signals_configured,
)
from jurati.server_state import ContextSnapshot, ServerState

SignalFetcher = Callable[[PRSignalsConfig], Sequence[PRSignal | CoordinationSignal]]
BlockingRunner = Callable[
    [Callable[[], Sequence[PRSignal | CoordinationSignal]]],
    Awaitable[Sequence[PRSignal | CoordinationSignal]],
]


def build_context_snapshot(state: ServerState, *, now: datetime) -> ContextSnapshot:
    total_entries = len(state.index.entries)
    visible_entries = tuple(
        entry
        for entry in state.index.entries.values()
        if entry.frontmatter.sensitivity != Sensitivity.RESTRICTED
    )
    visible_index = Index({entry.frontmatter.id: entry for entry in visible_entries})
    signals = tuple(state.signal_cache.get_signals())
    return ContextSnapshot(
        built_at=now,
        index_generation=state._index_generation,
        index=visible_index,
        total_entries=total_entries,
        hidden_restricted_entries=total_entries - len(visible_entries),
        bm25_index=build_inverted_index(list(visible_entries)),
        visible_entries=visible_entries,
        hygiene_report=summarize_lifecycle(visible_index, now=now, stale_after_days=90),
        signals=signals,
        signal_advisories=tuple(
            suggest_revalidation_from_signals(
                visible_entries,
                signals,
                now=now,
                recency_days=state.config.pr_signals.recency_days,
            )
        ),
    )


def snapshot_coverage(snapshot: ContextSnapshot) -> dict[str, Any]:
    return {
        "snapshot_built_at": snapshot.built_at.isoformat(),
        "snapshot_index_generation": snapshot.index_generation,
        "entries_considered": len(snapshot.visible_entries),
        "signals_considered": len(snapshot.signals),
        "curation_advisories_considered": (
            len(snapshot.hygiene_report.expired_active)
            + len(snapshot.hygiene_report.revalidation)
            + len(snapshot.signal_advisories)
        ),
        "hidden_restricted_entries": snapshot.hidden_restricted_entries,
    }


async def refresh_signal_cache(
    state: ServerState,
    *,
    now: datetime,
    fetch_signals: SignalFetcher,
    run_blocking: BlockingRunner,
    logger: logging.Logger,
) -> None:
    config = state.config.pr_signals
    cache = state.signal_cache
    if not _signals_configured(config) or not cache.needs_refresh(now):
        return

    try:
        signals = await run_blocking(lambda: fetch_signals(config))
        if signals or cache.size == 0:
            cache.update(signals, now=now)
        else:
            cache.evict_stale(now=now)
    except Exception:
        logger.warning("Context snapshot signal refresh failed; using cached data", exc_info=True)


def render_coordination_from_snapshot(
    snapshot: ContextSnapshot,
    state: ServerState,
    *,
    repo: str | None,
    goal: str | None,
    paths: list[str] | None,
    now: datetime,
) -> dict[str, Any]:
    if not snapshot.signals:
        return {
            "status": "ok",
            "summary": "No jurati-labeled signals in configured sources.",
            "guidance": [],
            "privacy_boundary": _privacy_boundary(),
        }

    guidance = classify_signals(
        snapshot.signals,
        repo=repo,
        _goal=goal,
        paths=paths,
        now=now,
        recency_days=state.config.pr_signals.recency_days,
    )
    active_effects = [item for item in guidance if item.effect != "continue"]
    summary = (
        f"{len(active_effects)} jurati-labeled PR(s) may affect this plan."
        if active_effects
        else f"{len(guidance)} jurati-labeled PR(s) noted; none affect current targets."
    )
    return {
        "status": "ok",
        "summary": summary,
        "guidance": [_format_guidance(item) for item in guidance],
        "privacy_boundary": _privacy_boundary(),
    }


def render_curation_from_snapshot(
    snapshot: ContextSnapshot,
    state: ServerState,
    *,
    include_signals: bool,
    repo: str | None = None,
    goal: str | None = None,
    max_items: int = 5,
) -> dict[str, Any] | None:
    visible_entry_by_id = {entry.frontmatter.id: entry for entry in snapshot.visible_entries}
    goal_terms = set(tokenize(goal or ""))
    expired_active = [
        item
        for item in snapshot.hygiene_report.expired_active
        if item.id in visible_entry_by_id
        and _entry_matches_context(visible_entry_by_id[item.id], repo=repo, goal_terms=goal_terms)
    ]
    revalidation_due = [
        item
        for item in snapshot.hygiene_report.revalidation
        if item.id in visible_entry_by_id
        and _entry_matches_context(visible_entry_by_id[item.id], repo=repo, goal_terms=goal_terms)
    ]
    signal_advisories = (
        list(snapshot.signal_advisories)
        if include_signals and _signals_configured(state.config.pr_signals)
        else []
    )
    signal_advisories = [
        advisory
        for advisory in signal_advisories
        if _advisory_matches_context(
            advisory,
            visible_entry_by_id,
            repo=repo,
            goal_terms=goal_terms,
        )
    ]

    if not expired_active and not revalidation_due and not signal_advisories:
        return None

    total = len(expired_active) + len(revalidation_due) + len(signal_advisories)
    expired_slice = expired_active[:max_items]
    revalidation_slice = revalidation_due[: max(0, max_items - len(expired_slice))]
    advisory_slice = signal_advisories[
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
            "when they matter to the task; do not ask the developer to manage Jurati "
            "lifecycle mechanics."
        ),
        "expired_active": [_format_expired_active_item(item) for item in expired_slice],
        "revalidation_due": [_format_revalidation_item(item) for item in revalidation_slice],
        "completed_artifact_revalidation": [
            _format_curation_advisory(advisory) for advisory in advisory_slice
        ],
        "privacy_boundary": _curation_privacy_boundary(),
    }
