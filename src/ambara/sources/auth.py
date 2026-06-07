# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Source authentication references.

Source config stores references to auth material, never raw tokens. The runtime
auth broker for managed deployments can resolve these references later without
changing the source artifact contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SourceAuthRefKind(StrEnum):
    ENV = "env"
    KEYRING = "keyring"
    MANAGED = "managed"


@dataclass(frozen=True)
class SourceAuthRef:
    kind: SourceAuthRefKind
    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("source auth reference name is required")
        if any(marker in self.name.lower() for marker in ("token=", "password=", "secret=")):
            raise ValueError("source auth references must not contain raw credentials")
