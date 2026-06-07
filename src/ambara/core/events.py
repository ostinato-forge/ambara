# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Event types for ambara knowledge lifecycle.

Events are only emitted for L1+ entries. L0 is fire-and-forget by design.
No ENTRY_MERGED event — merge is a git host operation, not ambara's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class EventType(StrEnum):
    ENTRY_PROPOSED = "entry_proposed"
    ENTRY_EXPIRED = "entry_expired"


@dataclass(frozen=True)
class EventRecord:
    timestamp: datetime
    event_type: EventType
    entry_id: str
    entry_type: str
    level: str
    visibility: str

    def to_dict(self) -> dict[str, str]:
        return {
            "timestamp": self.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "event_type": str(self.event_type),
            "entry_id": self.entry_id,
            "entry_type": self.entry_type,
            "level": self.level,
            "visibility": self.visibility,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def path(self) -> str:
        ts = self.timestamp.astimezone(UTC)
        date_dir = ts.strftime("%Y-%m-%d")
        file_ts = ts.strftime("%Y%m%dT%H%M%SZ")
        return f"events/{date_dir}/{file_ts}-{self.entry_id}.json"
