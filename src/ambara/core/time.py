# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared datetime formatting helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
