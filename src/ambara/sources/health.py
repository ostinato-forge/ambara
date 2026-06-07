# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Per-source health metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SourceHealthStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class SourceHealth:
    source_instance_id: str
    status: SourceHealthStatus
    last_success: datetime | None = None
    last_failure: datetime | None = None
    consecutive_failures: int = 0
    stale_after: datetime | None = None
    message: str | None = None

    @property
    def has_successful_baseline(self) -> bool:
        return self.last_success is not None
