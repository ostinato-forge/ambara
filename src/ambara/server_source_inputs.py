# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared source input selection for server read paths."""

from __future__ import annotations

from ambara.core.pr_signals import SignalLike, SourceInputLike
from ambara.core.scope_policy import filter_source_inputs
from ambara.server_state import ContextSnapshot, ServerState
from ambara.sources.types import SourceArtifact


def source_artifacts_from_report(state: ServerState) -> tuple[SourceArtifact, ...]:
    if state.source_report is None:
        return ()
    return state.source_report.artifacts


def source_artifacts_are_authoritative(state: ServerState) -> bool:
    return state.source_report is not None and bool(state.source_report.sources)


def source_inputs_for_state(state: ServerState) -> tuple[SourceInputLike, ...]:
    artifacts = source_artifacts_from_report(state)
    if artifacts or source_artifacts_are_authoritative(state):
        return filter_source_inputs(artifacts, state.config.muted_scopes)
    return filter_source_inputs(
        state.legacy_signal_cache.get_signals(),
        state.config.muted_scopes,
    )


def signal_inputs_for_state(state: ServerState) -> tuple[SignalLike, ...]:
    return source_inputs_for_state(state)


def source_inputs_for_snapshot(snapshot: ContextSnapshot) -> tuple[SourceInputLike, ...]:
    if snapshot.source_artifacts_authoritative:
        return snapshot.source_artifacts
    if snapshot.source_artifacts:
        return snapshot.source_artifacts
    return snapshot.legacy_signals


def signal_inputs_for_snapshot(snapshot: ContextSnapshot) -> tuple[SignalLike, ...]:
    return source_inputs_for_snapshot(snapshot)


def muted_source_input_count(
    state: ServerState,
    *,
    legacy_signals: tuple[SourceInputLike, ...],
    source_artifacts: tuple[SourceArtifact, ...],
) -> int:
    raw_source_artifacts = source_artifacts_from_report(state)
    if raw_source_artifacts or source_artifacts_are_authoritative(state):
        return len(raw_source_artifacts) - len(source_artifacts)
    return state.legacy_signal_cache.size - len(legacy_signals)


def muted_signal_count(
    state: ServerState,
    *,
    signals: tuple[SignalLike, ...],
    source_artifacts: tuple[SourceArtifact, ...],
) -> int:
    return muted_source_input_count(
        state,
        legacy_signals=signals,
        source_artifacts=source_artifacts,
    )
