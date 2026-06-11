# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for ambara.core.time datetime formatting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from ambara.core.time import format_timestamp


def test_format_timestamp_renders_utc_with_z_suffix() -> None:
    value = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    assert format_timestamp(value) == "2026-05-02T12:00:00Z"


def test_format_timestamp_normalizes_offset_to_utc() -> None:
    value = datetime(2026, 5, 2, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    assert format_timestamp(value) == "2026-05-02T12:00:00Z"


def test_format_timestamp_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        format_timestamp(datetime(2026, 5, 2, 12, 0))
