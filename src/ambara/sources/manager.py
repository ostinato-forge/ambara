# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Source manager that applies central safety and source budgets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ambara.sources.registry import SourceProviderRegistry
from ambara.sources.safety import enforce_source_budget, sanitize_source_artifact
from ambara.sources.types import (
    SourceArtifact,
    SourceFetchRequest,
    SourceInstanceConfig,
    SourceOmissions,
)


@dataclass(frozen=True)
class SourceManagerResult:
    source_instance_id: str
    artifacts: tuple[SourceArtifact, ...]
    omissions: SourceOmissions
    next_cursor: str | None = None
    etag: str | None = None
    ttl_seconds: int | None = None
    partial_errors: tuple[str, ...] = ()
    rate_limit_hint: str | None = None


class SourceManager:
    def __init__(self, registry: SourceProviderRegistry) -> None:
        self._registry = registry

    def fetch(
        self,
        config: SourceInstanceConfig,
        *,
        now: datetime,
        cursor: str | None = None,
        etag: str | None = None,
        since: datetime | None = None,
        auth: object | None = None,
    ) -> SourceManagerResult:
        provider = self._registry.require(config.provider)
        raw = provider.fetch(
            SourceFetchRequest(
                config=config,
                cursor=cursor,
                etag=etag,
                since=since,
                auth=auth,
                now=now,
            )
        )
        sanitized = tuple(
            sanitize_source_artifact(artifact, config=config) for artifact in raw.artifacts
        )
        budgeted, budget_omissions = enforce_source_budget(sanitized, config.budget)
        omissions = raw.omissions + budget_omissions
        for artifact in budgeted:
            omissions += artifact.omissions

        return SourceManagerResult(
            source_instance_id=config.id,
            artifacts=budgeted,
            omissions=omissions,
            next_cursor=raw.next_cursor,
            etag=raw.etag,
            ttl_seconds=raw.ttl_seconds,
            partial_errors=raw.partial_errors,
            rate_limit_hint=raw.rate_limit_hint,
        )
