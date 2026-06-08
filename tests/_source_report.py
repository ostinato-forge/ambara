# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared test helper: build a SourceInspectionReport from PR signals.

Used by server read-path tests to seed ``state.source_report`` (the single
source path) the way the legacy signal cache used to be seeded.
"""

from __future__ import annotations

from datetime import datetime

from ambara.core.pr_signals import PRSignal
from ambara.sources.adapters import source_artifact_from_pr_signal
from ambara.sources.health import SourceHealth, SourceHealthStatus
from ambara.sources.inspect import SourceInspection, SourceInspectionReport
from ambara.sources.types import SourceCategory, SourceInstanceConfig


def source_report_for_signals(
    *signals: PRSignal,
    now: datetime,
    repos: tuple[str, ...] = ("org/api",),
    instance_id: str = "source-reviews",
) -> SourceInspectionReport:
    config = SourceInstanceConfig(
        id=instance_id,
        provider="github",
        category=SourceCategory.FORGE_REVIEW,
        selectors={"repos": repos},
    )
    return SourceInspectionReport(
        sources=(
            SourceInspection(
                config=config,
                provider_display_name="GitHub",
                health=SourceHealth(
                    source_instance_id=config.id,
                    status=SourceHealthStatus.FRESH,
                    last_success=now,
                ),
                artifacts=tuple(
                    source_artifact_from_pr_signal(
                        signal,
                        source_instance_id=config.id,
                        fetched_at=now,
                    )
                    for signal in signals
                ),
            ),
        ),
        provider_ids=("github",),
    )
