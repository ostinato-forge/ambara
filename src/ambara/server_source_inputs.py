# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared source input selection for server read paths."""

from __future__ import annotations

from ambara.core.pr_signals import SourceInputLike
from ambara.core.scope_policy import filter_source_inputs
from ambara.server_state import ContextSnapshot, ServerState
from ambara.sources.types import SourceArtifact


def source_artifacts_from_report(state: ServerState) -> tuple[SourceArtifact, ...]:
    if state.source_report is None:
        return ()
    return state.source_report.artifacts


def source_inputs_for_state(state: ServerState) -> tuple[SourceInputLike, ...]:
    return filter_source_inputs(source_artifacts_from_report(state), state.config.muted_scopes)


def source_inputs_for_snapshot(snapshot: ContextSnapshot) -> tuple[SourceInputLike, ...]:
    return snapshot.source_artifacts


def muted_source_input_count(
    state: ServerState,
    *,
    source_artifacts: tuple[SourceArtifact, ...],
) -> int:
    return len(source_artifacts_from_report(state)) - len(source_artifacts)
