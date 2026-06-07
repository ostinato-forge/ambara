# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared source-input request flag handling for server render paths."""

from __future__ import annotations


def resolve_source_inputs_include(
    *,
    include_source_inputs: bool | None,
    include_pr_signals: bool | None,
    default: bool = True,
) -> bool:
    """Resolve source-native and legacy include flags without guessing conflicts."""
    if (
        include_source_inputs is not None
        and include_pr_signals is not None
        and include_source_inputs != include_pr_signals
    ):
        raise ValueError(
            "include_source_inputs and include_pr_signals disagree; "
            "set only one source-input include flag"
        )
    if include_source_inputs is not None:
        return include_source_inputs
    if include_pr_signals is not None:
        return include_pr_signals
    return default
