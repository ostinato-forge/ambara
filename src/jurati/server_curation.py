"""Curation-advisory assembly helpers for the MCP server."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

from jurati.core.context_rendering import (
    sanitize_signal_paths,
    sanitize_untrusted_signal_text,
)
from jurati.core.curation import CurationAdvisory, suggest_revalidation_from_signals
from jurati.core.hygiene import HygieneItem, summarize_lifecycle
from jurati.core.pr_signals import CoordinationSignal, PRSignal
from jurati.core.schema import Sensitivity
from jurati.core.scoring import tokenize
from jurati.git.config import PRSignalsConfig
from jurati.server_state import ServerState

SignalFetcher = Callable[[PRSignalsConfig], Sequence[PRSignal | CoordinationSignal]]
BlockingRunner = Callable[
    [Callable[[], Sequence[PRSignal | CoordinationSignal]]],
    Awaitable[Sequence[PRSignal | CoordinationSignal]],
]


async def build_curation_payload(
    state: ServerState,
    *,
    now: datetime,
    include_signals: bool,
    repo: str | None = None,
    goal: str | None = None,
    max_items: int = 5,
    fetch_signals: SignalFetcher,
    run_blocking: BlockingRunner,
    logger: logging.Logger,
) -> dict[str, Any] | None:
    report = summarize_lifecycle(state.index, now=now, stale_after_days=90)
    visible_entries = [
        entry
        for entry in state.index.entries.values()
        if entry.frontmatter.sensitivity != Sensitivity.RESTRICTED
    ]
    visible_entry_ids = {entry.frontmatter.id for entry in visible_entries}
    visible_entry_by_id = {entry.frontmatter.id: entry for entry in visible_entries}
    goal_terms = set(tokenize(goal or ""))
    revalidation_due = [
        item
        for item in report.revalidation
        if item.id in visible_entry_ids
        and _entry_matches_context(visible_entry_by_id[item.id], repo=repo, goal_terms=goal_terms)
    ]
    signal_advisories: list[CurationAdvisory] = []

    if include_signals and _signals_configured(state.config.pr_signals):
        cache = state.signal_cache
        if cache.needs_refresh(now):
            try:
                signals = await run_blocking(lambda: fetch_signals(state.config.pr_signals))
                if signals or cache.size == 0:
                    cache.update(signals, now=now)
                else:
                    cache.evict_stale(now=now)
            except Exception:
                logger.warning(
                    "Curation signal refresh failed; using cached data",
                    exc_info=True,
                )

        signal_advisories = suggest_revalidation_from_signals(
            visible_entries,
            cache.get_signals(),
            now=now,
            recency_days=state.config.pr_signals.recency_days,
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

    if not revalidation_due and not signal_advisories:
        return None

    total = len(revalidation_due) + len(signal_advisories)
    revalidation_slice = revalidation_due[:max_items]
    advisory_slice = signal_advisories[: max(0, max_items - len(revalidation_slice))]
    shown = len(revalidation_slice) + len(advisory_slice)
    return {
        "status": "ok",
        "summary": (
            f"{total} knowledge entr{'y' if total == 1 else 'ies'} should be checked "
            "before agents keep treating them as current."
        ),
        "total_advisories": total,
        "shown_advisories": shown,
        "omitted_advisories": max(0, total - shown),
        "agent_instruction": (
            "Use these advisories as quiet planning cautions. Verify affected entries "
            "when they matter to the task; do not ask the developer to manage Jurati "
            "lifecycle mechanics."
        ),
        "revalidation_due": [_format_revalidation_item(item) for item in revalidation_slice],
        "completed_artifact_revalidation": [
            _format_curation_advisory(advisory) for advisory in advisory_slice
        ],
        "privacy_boundary": _curation_privacy_boundary(),
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
        "signal_source": sanitize_untrusted_signal_text(
            advisory.signal_source,
            field="title",
            max_chars=120,
        ),
        "artifact_ref": _safe_artifact_ref(advisory.artifact_ref),
        "artifact_title": sanitize_untrusted_signal_text(
            advisory.artifact_title,
            field="title",
            max_chars=160,
        ),
        "changed_paths": list(sanitize_signal_paths(advisory.changed_paths, max_paths=5)),
        "matched_terms": list(advisory.matched_terms),
        "merged_at": advisory.merged_at.isoformat(),
        "text_trust": "untrusted_external",
        "agent_instruction": (
            "Revalidate this entry before relying on it for the current task; do not "
            "surface Jurati lifecycle mechanics unless the curation itself is the task."
        ),
    }


def _curation_privacy_boundary() -> list[str]:
    return [
        "based only on repo-owned entry metadata and configured labeled PR/Jira signals",
        "does not use query logs, read receipts, editor activity, or participation data",
        "does not infer absence, installation status, or teammate activity",
    ]


def _signals_configured(config: PRSignalsConfig) -> bool:
    return bool(
        config.fixture_path or config.repos or (config.jira_base_url and config.jira_projects)
    )


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
    if repo is not None and advisory.signal_source == repo:
        return True

    entry = entries_by_id.get(advisory.entry_id)
    if entry is None:
        return False
    return _entry_matches_context(entry, repo=repo, goal_terms=goal_terms)


def _safe_artifact_ref(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username or parsed.password:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
