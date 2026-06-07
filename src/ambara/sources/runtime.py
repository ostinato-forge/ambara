# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Runtime source refresh helpers for legacy-configured source selectors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.sources.adapters import legacy_signal_from_source_artifact
from ambara.sources.cache import SourceCache
from ambara.sources.config import (
    SourceInputsConfig,
    SourcesConfig,
    sources_from_source_inputs_config,
)
from ambara.sources.inspect import SourceInspectionReport, inspect_sources
from ambara.sources.legacy_providers import source_registry_for_legacy_sources


@dataclass(frozen=True)
class SourceRuntimeReport:
    legacy_signals: tuple[PRSignal | CoordinationSignal, ...]
    source_report: SourceInspectionReport

    @property
    def signals(self) -> tuple[PRSignal | CoordinationSignal, ...]:
        return self.legacy_signals


@dataclass(frozen=True, init=False)
class SourceSignalReport:
    legacy_signals: tuple[PRSignal | CoordinationSignal, ...]
    source_report: SourceInspectionReport

    def __init__(
        self,
        legacy_signals: tuple[PRSignal | CoordinationSignal, ...] | None = None,
        source_report: SourceInspectionReport | None = None,
        *,
        signals: tuple[PRSignal | CoordinationSignal, ...] | None = None,
    ) -> None:
        if source_report is None:
            raise TypeError("SourceSignalReport requires source_report")
        if signals is not None:
            if legacy_signals is not None and signals != legacy_signals:
                raise ValueError("signals compatibility alias must match legacy_signals")
            legacy_signals = signals
        object.__setattr__(self, "legacy_signals", legacy_signals or ())
        object.__setattr__(self, "source_report", source_report)

    @property
    def signals(self) -> tuple[PRSignal | CoordinationSignal, ...]:
        return self.legacy_signals


def fetch_source_runtime_report(
    config: SourceInputsConfig,
    *,
    token: str | None = None,
    now: datetime | None = None,
    source_cache: SourceCache | None = None,
) -> SourceRuntimeReport:
    report_now = now or datetime.now(UTC)
    sources = _runtime_sources_from_source_inputs(config)
    registry = source_registry_for_legacy_sources(sources)
    source_report = inspect_sources(
        sources,
        registry=registry,
        now=report_now,
        auth=token,
        cache=source_cache,
    )
    legacy_signals = tuple(
        legacy_signal_from_source_artifact(artifact, now=report_now)
        for inspection in source_report.sources
        for artifact in inspection.artifacts
    )
    return SourceRuntimeReport(
        legacy_signals=legacy_signals,
        source_report=source_report,
    )


def fetch_source_signal_report(
    config: SourceInputsConfig,
    *,
    token: str | None = None,
    now: datetime | None = None,
    source_cache: SourceCache | None = None,
) -> SourceSignalReport:
    report = fetch_source_runtime_report(
        config,
        token=token,
        now=now,
        source_cache=source_cache,
    )
    return SourceSignalReport(
        legacy_signals=report.legacy_signals,
        source_report=report.source_report,
    )


def _runtime_sources_from_source_inputs(config: SourceInputsConfig) -> SourcesConfig:
    sources = sources_from_source_inputs_config(config)
    if not config.fixture_path:
        return sources
    fixture_instances = tuple(
        instance for instance in sources.enabled_instances() if instance.provider == "fixture"
    )
    return SourcesConfig(instances=fixture_instances)
