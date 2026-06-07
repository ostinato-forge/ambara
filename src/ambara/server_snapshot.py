# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Derived context snapshot assembly for compiler-mode context."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ambara.core.context_compiler import derive_freshness
from ambara.core.curation import suggest_revalidation_from_source_inputs
from ambara.core.hygiene import summarize_lifecycle
from ambara.core.index import Index
from ambara.core.pr_signals import classify_source_inputs
from ambara.core.schema import EntryStatus, Sensitivity
from ambara.core.scope_policy import filter_index, filter_source_inputs
from ambara.core.scoring import build_inverted_index, tokenize
from ambara.server_coordination import _format_guidance, _privacy_boundary
from ambara.server_curation import (
    _advisory_matches_context,
    _curation_privacy_boundary,
    _curation_summary,
    _entry_matches_context,
    _format_curation_advisory,
    _format_expired_active_item,
    _format_revalidation_item,
)
from ambara.server_scope import source_config_for_mute
from ambara.server_signals import (
    refresh_source_inputs,
    source_inputs_configured,
    source_report_needs_refresh,
)
from ambara.server_source_inputs import (
    muted_source_input_count,
    source_artifacts_are_authoritative,
    source_artifacts_from_report,
    source_inputs_for_snapshot,
)
from ambara.server_state import ContextSnapshot, ServerState, SyncHealth
from ambara.server_types import BlockingRunner, LegacySignalFetcher
from ambara.sources.health import SourceHealthStatus
from ambara.sources.inspect import SourceInspection, SourceInspectionReport

_SOURCE_UNAVAILABLE_STARTUP_REASON = (
    "configured source unavailable; run ambara sources doctor for details"
)
_SOURCE_INPUT_UNAVAILABLE_STARTUP_REASON = (
    "configured source inputs have not refreshed successfully; "
    "run ambara sources doctor for details"
)
_SIGNAL_UNAVAILABLE_STARTUP_REASON = _SOURCE_INPUT_UNAVAILABLE_STARTUP_REASON
_STARTUP_SOURCE_HEALTH_LIMIT = 4


def build_context_snapshot(state: ServerState, *, now: datetime) -> ContextSnapshot:
    total_entries = len(state.index.entries)
    unmuted_index = filter_index(state.index, state.config.muted_scopes)
    unmuted_entries = tuple(unmuted_index.entries.values())
    current_entries = tuple(
        entry
        for entry in unmuted_entries
        if entry.frontmatter.status not in (EntryStatus.EXPIRED, EntryStatus.SUPERSEDED)
    )
    visible_entries = tuple(
        entry
        for entry in current_entries
        if entry.frontmatter.sensitivity != Sensitivity.RESTRICTED
    )
    visible_index = Index({entry.frontmatter.id: entry for entry in visible_entries})
    source_artifacts = filter_source_inputs(
        source_artifacts_from_report(state),
        state.config.muted_scopes,
    )
    artifacts_authoritative = source_artifacts_are_authoritative(state)
    legacy_signals = (
        ()
        if artifacts_authoritative
        else filter_source_inputs(
            state.legacy_signal_cache.get_signals(),
            state.config.muted_scopes,
        )
    )
    source_inputs = (
        source_artifacts if artifacts_authoritative or source_artifacts else legacy_signals
    )
    source_advisories = tuple(
        suggest_revalidation_from_source_inputs(
            visible_entries,
            source_inputs,
            now=now,
            recency_days=state.config.source_inputs.recency_days,
        )
    )
    muted_source_inputs_hidden = muted_source_input_count(
        state,
        legacy_signals=legacy_signals,
        source_artifacts=source_artifacts,
    )
    return ContextSnapshot(
        built_at=now,
        index_generation=state.cache.generation,
        index=visible_index,
        total_entries=total_entries,
        hidden_restricted_entries=len(current_entries) - len(visible_entries),
        bm25_index=build_inverted_index(list(visible_entries)),
        visible_entries=visible_entries,
        hygiene_report=summarize_lifecycle(visible_index, now=now, stale_after_days=90),
        legacy_signals=legacy_signals,
        source_artifacts=source_artifacts,
        source_artifacts_authoritative=artifacts_authoritative,
        source_advisories=source_advisories,
        muted_entries_hidden=total_entries - len(unmuted_entries),
        retired_entries_hidden=len(unmuted_entries) - len(current_entries),
        muted_source_inputs_hidden=muted_source_inputs_hidden,
    )


def snapshot_coverage(snapshot: ContextSnapshot) -> dict[str, Any]:
    source_inputs = snapshot_source_inputs(snapshot)
    return {
        "snapshot_built_at": snapshot.built_at.isoformat(),
        "snapshot_index_generation": snapshot.index_generation,
        "entries_considered": len(snapshot.visible_entries),
        "signals_considered": len(source_inputs),
        "source_artifacts_considered": len(snapshot.source_artifacts),
        "legacy_signals_considered": len(snapshot.legacy_signals),
        "curation_advisories_considered": (
            len(snapshot.hygiene_report.expired_active)
            + len(snapshot.hygiene_report.revalidation)
            + len(snapshot.source_advisories)
        ),
        "hidden_restricted_entries": snapshot.hidden_restricted_entries,
        "muted_entries_hidden": snapshot.muted_entries_hidden,
        "retired_entries_hidden": snapshot.retired_entries_hidden,
        "muted_signals_hidden": snapshot.muted_source_inputs_hidden,
    }


def snapshot_status_payload(state: ServerState, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    snapshot = state.cache.snapshot
    source_cache_last_success = state.source_cache.last_success
    source_cache_last_refresh = state.source_report_last_refresh
    source_cache_needs_refresh = source_report_needs_refresh(state, now=now)
    legacy_signal_cache = state.legacy_signal_cache
    legacy_signal_cache_last_refresh = legacy_signal_cache.last_refresh
    signal_cache_uses_source_status = source_cache_last_refresh is not None
    signal_cache_size = (
        state.source_cache.artifact_count
        if signal_cache_uses_source_status
        else legacy_signal_cache.size
    )
    signal_cache_last_refresh = (
        source_cache_last_refresh
        if signal_cache_uses_source_status
        else legacy_signal_cache_last_refresh
    )
    signal_cache_needs_refresh = (
        source_cache_needs_refresh
        if signal_cache_uses_source_status
        else legacy_signal_cache.needs_refresh(now)
    )
    health = compiler_health_for_context(state, include_source_inputs=True)
    freshness = derive_freshness(
        now=now,
        last_success=health.last_success,
        warning_threshold_seconds=state.config.context_freshness_warning_seconds,
        stale_threshold_seconds=state.config.context_stale_after_seconds,
        last_failure=health.last_failure,
        last_error=health.last_error,
        consecutive_failures=health.consecutive_failures,
    )
    source_refresh = source_refresh_status_payload(state, now=now)
    payload: dict[str, Any] = {
        "available": snapshot is not None,
        "current": snapshot is not None and snapshot.index_generation == state.cache.generation,
        "availability": str(freshness.status),
        "freshness": freshness.to_dict(),
        "index_generation": state.cache.generation,
        "source_cache_size": state.source_cache.artifact_count,
        "source_cache_source_count": state.source_cache.source_count,
        "source_cache_last_success": (
            source_cache_last_success.isoformat() if source_cache_last_success else None
        ),
        "source_cache_last_refresh": (
            source_cache_last_refresh.isoformat() if source_cache_last_refresh else None
        ),
        "source_cache_needs_refresh": source_cache_needs_refresh,
        "legacy_signal_cache_size": legacy_signal_cache.size,
        "legacy_signal_cache_last_refresh": (
            legacy_signal_cache_last_refresh.isoformat()
            if legacy_signal_cache_last_refresh
            else None
        ),
        "legacy_signal_cache_needs_refresh": legacy_signal_cache.needs_refresh(now),
        "signal_cache_size": signal_cache_size,
        "signal_cache_last_refresh": (
            signal_cache_last_refresh.isoformat() if signal_cache_last_refresh else None
        ),
        "signal_cache_needs_refresh": signal_cache_needs_refresh,
        "source_refresh": source_refresh,
        "signal_refresh": source_refresh,
    }
    if snapshot is None:
        return payload

    source_inputs = snapshot_source_inputs(snapshot)
    return {
        **payload,
        "built_at": snapshot.built_at.isoformat(),
        "snapshot_index_generation": snapshot.index_generation,
        "total_entries": snapshot.total_entries,
        "entries_considered": len(snapshot.visible_entries),
        "hidden_restricted_entries": snapshot.hidden_restricted_entries,
        "muted_entries_hidden": snapshot.muted_entries_hidden,
        "retired_entries_hidden": snapshot.retired_entries_hidden,
        "signals_considered": len(source_inputs),
        "source_artifacts_considered": len(snapshot.source_artifacts),
        "legacy_signals_considered": len(snapshot.legacy_signals),
        "muted_signals_hidden": snapshot.muted_source_inputs_hidden,
        "curation_advisories_considered": (
            len(snapshot.hygiene_report.expired_active)
            + len(snapshot.hygiene_report.revalidation)
            + len(snapshot.source_advisories)
        ),
    }


def compiler_health_for_context(
    state: ServerState,
    *,
    include_source_inputs: bool | None = None,
    include_signals: bool | None = None,
) -> SyncHealth:
    source_inputs_enabled = _source_inputs_enabled(
        include_source_inputs=include_source_inputs,
        include_signals=include_signals,
    )
    if source_inputs_enabled and _source_input_baseline_unavailable(state):
        return SyncHealth(
            last_success=None,
            last_failure=state.source_health.last_failure,
            last_error=_startup_source_input_unavailable_reason(state),
            consecutive_failures=state.source_health.consecutive_failures,
        )
    return state.sync_health


def compiler_health_for_source_report(
    report: SourceInspectionReport | None,
    *,
    fallback: SyncHealth,
) -> SyncHealth:
    """Keep startup freshness honest when configured sources have no baseline."""

    if report is not None and source_report_baseline_unavailable(report):
        aggregate = report.aggregate_health
        return SyncHealth(
            last_success=None,
            last_failure=aggregate.last_failure,
            last_error=_SOURCE_UNAVAILABLE_STARTUP_REASON,
            consecutive_failures=aggregate.consecutive_failures,
        )
    return fallback


def startup_source_health_payload(
    state: ServerState, *, now: datetime | None = None
) -> dict[str, Any] | None:
    """Return a compact, privacy-safe source health summary for startup context."""

    now = now or datetime.now(UTC)
    report = state.source_report
    if report is None or not report.sources:
        return None
    return startup_source_health_payload_from_report(report, now=now)


def startup_source_health_payload_from_report(
    report: SourceInspectionReport,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return compact startup health from a source report without raw diagnostics."""

    now = now or datetime.now(UTC)
    counts = {status.value: 0 for status in SourceHealthStatus}
    degraded: list[SourceInspection] = []
    for inspection in report.sources:
        status = _source_health_status_for_now(inspection, now=now)
        counts[status.value] += 1
        if status is not SourceHealthStatus.FRESH:
            degraded.append(inspection)

    if not degraded:
        return None

    shown = degraded[:_STARTUP_SOURCE_HEALTH_LIMIT]
    payload: dict[str, Any] = {
        "configured": len(report.sources),
        "fresh": counts[SourceHealthStatus.FRESH.value],
        "stale": counts[SourceHealthStatus.STALE.value],
        "unavailable": counts[SourceHealthStatus.UNAVAILABLE.value],
        "error": counts[SourceHealthStatus.ERROR.value],
        "sources": [
            {
                "id": inspection.config.id,
                "provider": inspection.config.provider,
                "status": _source_health_status_for_now(inspection, now=now).value,
                "baseline_available": inspection.health.has_successful_baseline,
                "rate_limited": inspection.rate_limited,
            }
            for inspection in shown
        ],
    }
    omitted = len(degraded) - len(shown)
    if omitted > 0:
        payload["omitted"] = omitted
    return payload


def startup_source_omissions_payload(
    state: ServerState,
) -> dict[str, int] | None:
    report = state.source_report
    if report is None or not report.sources:
        return None
    return startup_source_omissions_payload_from_report(report)


def startup_source_omissions_payload_from_report(
    report: SourceInspectionReport,
) -> dict[str, int] | None:
    """Return aggregate source omission counts for compact startup packets."""

    omissions = report.omissions
    if omissions.total <= 0:
        return None
    return {
        "privacy": omissions.privacy,
        "safety": omissions.safety,
        "budget": omissions.budget,
        "freshness": omissions.freshness,
        "source_error": omissions.source_error,
        "total": omissions.total,
    }


def source_refresh_status_payload(
    state: ServerState, *, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    configured = source_inputs_configured(state.config.source_inputs)
    health = state.source_health
    return {
        "configured": configured,
        "baseline_available": not _source_input_baseline_unavailable(state),
        "last_refresh": (
            state.source_report_last_refresh.isoformat()
            if state.source_report_last_refresh
            else None
        ),
        "needs_refresh": source_report_needs_refresh(state, now=now),
        "last_success": health.last_success.isoformat() if health.last_success else None,
        "last_failure": health.last_failure.isoformat() if health.last_failure else None,
        "last_error": health.last_error,
        "consecutive_failures": health.consecutive_failures,
        "source_count": len(state.source_report.sources) if state.source_report else 0,
        "sources": [
            _source_refresh_payload(inspection, now=now)
            for inspection in (state.source_report.sources if state.source_report else ())
        ],
    }


def signal_refresh_status_payload(state: ServerState) -> dict[str, Any]:
    return source_refresh_status_payload(state)


def snapshot_source_inputs(snapshot: ContextSnapshot) -> tuple[Any, ...]:
    return source_inputs_for_snapshot(snapshot)


def snapshot_signal_inputs(snapshot: ContextSnapshot) -> tuple[Any, ...]:
    return snapshot_source_inputs(snapshot)


def _source_input_baseline_unavailable(state: ServerState) -> bool:
    if _source_baseline_unavailable(state):
        return True
    return (
        source_inputs_configured(state.config.source_inputs)
        and state.legacy_signal_cache.size == 0
        and state.source_health.last_success is None
    )


def _signal_baseline_unavailable(state: ServerState) -> bool:
    return _source_input_baseline_unavailable(state)


def _source_baseline_unavailable(state: ServerState) -> bool:
    if state.source_report is None:
        return False
    return source_report_baseline_unavailable(state.source_report)


def source_report_baseline_unavailable(report: SourceInspectionReport) -> bool:
    return any(
        inspection.health.status is SourceHealthStatus.UNAVAILABLE
        and not inspection.health.has_successful_baseline
        for inspection in report.sources
    )


def _startup_source_input_unavailable_reason(state: ServerState) -> str:
    if _source_baseline_unavailable(state):
        return _SOURCE_UNAVAILABLE_STARTUP_REASON
    return _SOURCE_INPUT_UNAVAILABLE_STARTUP_REASON


def _startup_signal_unavailable_reason(state: ServerState) -> str:
    return _startup_source_input_unavailable_reason(state)


def _source_refresh_payload(
    inspection: SourceInspection, *, now: datetime
) -> dict[str, Any]:
    health = inspection.health
    return {
        "id": inspection.config.id,
        "provider": inspection.config.provider,
        "category": inspection.config.category.value,
        "status": _source_health_status_for_now(inspection, now=now).value,
        "artifact_count": len(inspection.artifacts),
        "baseline_available": health.has_successful_baseline,
        "rate_limited": inspection.rate_limited,
        "last_success": health.last_success.isoformat() if health.last_success else None,
        "last_failure": health.last_failure.isoformat() if health.last_failure else None,
        "last_error": health.message,
        "omissions": {
            "privacy": inspection.omissions.privacy,
            "safety": inspection.omissions.safety,
            "budget": inspection.omissions.budget,
            "freshness": inspection.omissions.freshness,
            "source_error": inspection.omissions.source_error,
            "total": inspection.omissions.total,
        },
    }


def _source_health_status_for_now(
    inspection: SourceInspection, *, now: datetime
) -> SourceHealthStatus:
    health = inspection.health
    if (
        health.status is SourceHealthStatus.FRESH
        and health.stale_after is not None
        and health.stale_after <= now
    ):
        return SourceHealthStatus.STALE
    return health.status


async def refresh_context_snapshot(
    state: ServerState,
    *,
    now: datetime,
    run_blocking: BlockingRunner,
    logger: logging.Logger,
    fetch_signals: LegacySignalFetcher | None = None,
) -> ContextSnapshot:
    await refresh_source_inputs(
        state,
        config=source_config_for_mute(state.config.source_inputs, state.config.muted_scopes),
        now=now,
        fetch_signals=fetch_signals,
        run_blocking=run_blocking,
        logger=logger,
        failure_log_message="Context snapshot source input refresh failed; using cached data",
    )
    return build_context_snapshot(state, now=now)


def render_coordination_from_snapshot(
    snapshot: ContextSnapshot,
    state: ServerState,
    *,
    repo: str | None,
    goal: str | None,
    paths: list[str] | None,
    now: datetime,
) -> dict[str, Any]:
    source_inputs = snapshot_source_inputs(snapshot)
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
        recency_days=state.config.source_inputs.recency_days,
    )
    active_effects = [item for item in guidance if item.effect != "continue"]
    summary = (
        f"{len(active_effects)} ambara-labeled source input(s) may affect this plan."
        if active_effects
        else f"{len(guidance)} ambara-labeled source input(s) noted; none affect current targets."
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
    include_source_inputs: bool | None = None,
    include_signals: bool | None = None,
    repo: str | None = None,
    goal: str | None = None,
    max_items: int = 5,
) -> dict[str, Any] | None:
    source_inputs_enabled = _source_inputs_enabled(
        include_source_inputs=include_source_inputs,
        include_signals=include_signals,
    )
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
    source_advisories = (
        list(snapshot.source_advisories)
        if source_inputs_enabled and source_inputs_configured(state.config.source_inputs)
        else []
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


def _source_inputs_enabled(
    *,
    include_source_inputs: bool | None,
    include_signals: bool | None,
) -> bool:
    if include_source_inputs is not None:
        return include_source_inputs
    return bool(include_signals)
