# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Per-source cache records and freshness metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ambara.sources.health import SourceHealth, SourceHealthStatus
from ambara.sources.types import SourceArtifact, SourceOmissions


@dataclass(frozen=True)
class SourceCacheRecord:
    source_instance_id: str
    artifacts: tuple[SourceArtifact, ...]
    stored_at: datetime
    expires_at: datetime | None = None
    cursor: str | None = None
    etag: str | None = None
    omissions: SourceOmissions = SourceOmissions()


@dataclass(frozen=True)
class SourceCacheLookup:
    source_instance_id: str
    artifacts: tuple[SourceArtifact, ...]
    health: SourceHealth
    omissions: SourceOmissions = SourceOmissions()
    stale: bool = False
    cursor: str | None = None
    etag: str | None = None
    expires_at: datetime | None = None


class SourceCache:
    def __init__(self) -> None:
        self._records: dict[str, SourceCacheRecord] = {}
        self._health: dict[str, SourceHealth] = {}

    @property
    def artifact_count(self) -> int:
        return sum(len(record.artifacts) for record in self._records.values())

    @property
    def source_count(self) -> int:
        return len(self._records)

    @property
    def last_success(self) -> datetime | None:
        if not self._records:
            return None
        return max(record.stored_at for record in self._records.values())

    def lookup(self, source_instance_id: str, *, now: datetime) -> SourceCacheLookup:
        record = self._records.get(source_instance_id)
        if record is None:
            health = self._health.get(
                source_instance_id,
                SourceHealth(
                    source_instance_id=source_instance_id,
                    status=SourceHealthStatus.UNAVAILABLE,
                ),
            )
            return SourceCacheLookup(source_instance_id, (), health)

        stale = record.expires_at is not None and record.expires_at <= now
        status = SourceHealthStatus.STALE if stale else SourceHealthStatus.FRESH
        health = self._health.get(
            source_instance_id,
            SourceHealth(
                source_instance_id=source_instance_id,
                status=status,
                last_success=record.stored_at,
                stale_after=record.expires_at,
            ),
        )
        if health.status is SourceHealthStatus.FRESH and stale:
            health = SourceHealth(
                source_instance_id=source_instance_id,
                status=SourceHealthStatus.STALE,
                last_success=health.last_success,
                last_failure=health.last_failure,
                consecutive_failures=health.consecutive_failures,
                stale_after=record.expires_at,
                message=health.message,
            )
        return SourceCacheLookup(
            source_instance_id,
            record.artifacts,
            health,
            omissions=record.omissions,
            stale=stale or health.status is SourceHealthStatus.STALE,
            cursor=record.cursor,
            etag=record.etag,
            expires_at=record.expires_at,
        )

    def record_success(
        self,
        source_instance_id: str,
        *,
        artifacts: tuple[SourceArtifact, ...],
        now: datetime,
        ttl_seconds: int | None = None,
        cursor: str | None = None,
        etag: str | None = None,
        omissions: SourceOmissions | None = None,
    ) -> SourceCacheRecord:
        expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None
        record = SourceCacheRecord(
            source_instance_id=source_instance_id,
            artifacts=tuple(artifacts),
            stored_at=now,
            expires_at=expires_at,
            cursor=cursor,
            etag=etag,
            omissions=omissions or SourceOmissions(),
        )
        self._records[source_instance_id] = record
        self._health[source_instance_id] = SourceHealth(
            source_instance_id=source_instance_id,
            status=SourceHealthStatus.FRESH,
            last_success=now,
            consecutive_failures=0,
            stale_after=expires_at,
        )
        return record

    def record_failure(
        self,
        source_instance_id: str,
        *,
        now: datetime,
        message: str,
    ) -> SourceHealth:
        previous = self._health.get(source_instance_id)
        record = self._records.get(source_instance_id)
        consecutive = (previous.consecutive_failures if previous else 0) + 1
        status = SourceHealthStatus.STALE if record is not None else SourceHealthStatus.UNAVAILABLE
        health = SourceHealth(
            source_instance_id=source_instance_id,
            status=status,
            last_success=previous.last_success if previous else None,
            last_failure=now,
            consecutive_failures=consecutive,
            stale_after=record.expires_at if record is not None else None,
            message=message,
        )
        self._health[source_instance_id] = health
        return health
