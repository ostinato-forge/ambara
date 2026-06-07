# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Inspectable source health reports for CLI/user-path smoke tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ambara.sources.cache import SourceCache
from ambara.sources.config import SourcesConfig
from ambara.sources.health import SourceHealth, SourceHealthStatus
from ambara.sources.manager import SourceManager
from ambara.sources.registry import SourceProviderRegistry
from ambara.sources.types import SourceArtifact, SourceInstanceConfig, SourceOmissions

_PARTIAL_SOURCE_REFRESH_MESSAGE = "partial source refresh failed"
_RATE_LIMITED_SOURCE_REFRESH_MESSAGE = "source refresh rate limited"
_SOURCE_REFRESH_FAILED_MESSAGE = "source refresh failed"


@dataclass(frozen=True)
class SourceInspection:
    config: SourceInstanceConfig
    provider_display_name: str | None
    health: SourceHealth
    artifacts: tuple[SourceArtifact, ...] = ()
    omissions: SourceOmissions = SourceOmissions()
    partial_errors: tuple[str, ...] = ()
    rate_limited: bool = False


@dataclass(frozen=True)
class SourceInspectionReport:
    sources: tuple[SourceInspection, ...]
    provider_ids: tuple[str, ...]

    @property
    def status(self) -> str:
        if not self.sources:
            return "not_configured"
        statuses = {inspection.health.status for inspection in self.sources}
        if SourceHealthStatus.UNAVAILABLE in statuses or SourceHealthStatus.ERROR in statuses:
            return "unavailable"
        if SourceHealthStatus.STALE in statuses:
            return "stale"
        return "ok"

    @property
    def artifact_count(self) -> int:
        return sum(len(inspection.artifacts) for inspection in self.sources)

    @property
    def artifacts(self) -> tuple[SourceArtifact, ...]:
        return tuple(artifact for inspection in self.sources for artifact in inspection.artifacts)

    @property
    def omissions(self) -> SourceOmissions:
        total = SourceOmissions()
        for inspection in self.sources:
            total += inspection.omissions
        return total

    @property
    def source_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        for inspection in self.sources:
            if inspection.health.last_failure is None:
                continue
            label = inspection.provider_display_name or inspection.config.provider
            message = inspection.health.message or "source refresh failed"
            errors.append(f"{label}: {message}")
        return tuple(errors)

    @property
    def aggregate_health(self) -> SourceHealth:
        statuses = {inspection.health.status for inspection in self.sources}
        if SourceHealthStatus.ERROR in statuses:
            status = SourceHealthStatus.ERROR
        elif SourceHealthStatus.UNAVAILABLE in statuses:
            status = SourceHealthStatus.UNAVAILABLE
        elif SourceHealthStatus.STALE in statuses:
            status = SourceHealthStatus.STALE
        else:
            status = SourceHealthStatus.FRESH

        successes = tuple(
            health.last_success
            for health in (inspection.health for inspection in self.sources)
            if health.last_success is not None
        )
        failures = tuple(
            health.last_failure
            for health in (inspection.health for inspection in self.sources)
            if health.last_failure is not None
        )
        stale_after = tuple(
            health.stale_after
            for health in (inspection.health for inspection in self.sources)
            if health.stale_after is not None
        )
        return SourceHealth(
            source_instance_id="source-report",
            status=status,
            last_success=max(successes) if successes else None,
            last_failure=max(failures) if failures else None,
            consecutive_failures=max(
                (inspection.health.consecutive_failures for inspection in self.sources),
                default=0,
            ),
            stale_after=min(stale_after) if stale_after else None,
            message="; ".join(self.source_errors) or None,
        )


def inspect_sources(
    sources: SourcesConfig,
    *,
    registry: SourceProviderRegistry,
    now: datetime,
    auth: object | None = None,
    cache: SourceCache | None = None,
) -> SourceInspectionReport:
    """Fetch configured sources and return per-source freshness truth."""

    cache = cache or SourceCache()
    manager = SourceManager(registry)
    inspections: list[SourceInspection] = []

    for instance in sources.enabled_instances():
        provider = registry.resolve(instance.provider)
        if provider is None:
            health = cache.record_failure(
                instance.id,
                now=now,
                message=f"unknown source provider {instance.provider!r}",
            )
            inspections.append(
                SourceInspection(
                    config=instance,
                    provider_display_name=None,
                    health=health,
                    omissions=SourceOmissions(source_error=1),
                )
            )
            continue

        cached = cache.lookup(instance.id, now=now)
        try:
            result = manager.fetch(
                instance,
                now=now,
                cursor=cached.cursor,
                etag=cached.etag,
                since=cached.health.last_success,
                auth=auth,
            )
        except Exception:
            health = cache.record_failure(
                instance.id,
                now=now,
                message=_SOURCE_REFRESH_FAILED_MESSAGE,
            )
            lookup = cache.lookup(instance.id, now=now)
            omissions = lookup.omissions.add(source_error=1)
            inspections.append(
                SourceInspection(
                    config=instance,
                    provider_display_name=provider.display_name,
                    health=health,
                    artifacts=lookup.artifacts,
                    omissions=omissions,
                )
            )
            continue

        degraded = bool(result.partial_errors or result.rate_limit_hint)
        source_error_count = len(result.partial_errors)
        if result.rate_limit_hint:
            source_error_count += 1
        omissions = result.omissions.add(source_error=source_error_count)
        if not degraded or result.artifacts:
            cache.record_success(
                instance.id,
                artifacts=result.artifacts,
                now=now,
                ttl_seconds=result.ttl_seconds,
                cursor=result.next_cursor,
                etag=result.etag,
                omissions=omissions,
            )
        if degraded:
            message = (
                _RATE_LIMITED_SOURCE_REFRESH_MESSAGE
                if result.rate_limit_hint
                else _PARTIAL_SOURCE_REFRESH_MESSAGE
            )
            cache.record_failure(
                instance.id,
                now=now,
                message=message,
            )
        lookup = cache.lookup(instance.id, now=now)
        inspections.append(
            SourceInspection(
                config=instance,
                provider_display_name=provider.display_name,
                health=lookup.health,
                artifacts=lookup.artifacts,
                omissions=omissions,
                partial_errors=result.partial_errors,
                rate_limited=bool(result.rate_limit_hint),
            )
        )

    return SourceInspectionReport(
        sources=tuple(inspections),
        provider_ids=registry.provider_ids(),
    )
