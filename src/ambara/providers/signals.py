# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Coordination signal provider entrypoints.

Aggregates signals from configured review providers and Jira issues.
Each provider is called independently — a failure in one does not block the other.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.providers.errors import SignalProviderError
from ambara.sources.config import PRSignalsConfig
from ambara.sources.runtime import SourceSignalReport, fetch_source_signal_report

logger = logging.getLogger(__name__)

__all__ = ["SourceSignalReport", "fetch_all_signals", "fetch_source_signal_report"]


def fetch_all_signals(
    config: PRSignalsConfig,
    *,
    token: str | None = None,
) -> Sequence[PRSignal | CoordinationSignal]:
    report = fetch_source_signal_report(config, token=token)
    errors = _legacy_signal_provider_errors(report.source_report.source_errors)

    for error in errors:
        logger.warning("Signal source refresh issue: %s", error)

    if errors and not report.legacy_signals:
        raise SignalProviderError("; ".join(errors))

    return list(report.legacy_signals)


def _legacy_signal_provider_errors(source_errors: tuple[str, ...]) -> tuple[str, ...]:
    errors: list[str] = []
    for error in source_errors:
        label, separator, message = error.partition(": ")
        if separator and message.startswith("unknown source provider"):
            message = "unknown signal provider; expected github, gitlab, jira, or fixture"
            errors.append(f"{label}: {message}")
            continue
        errors.append(error)
    return tuple(errors)
