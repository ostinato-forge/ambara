# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for the public ambara.providers API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from ambara.providers import (
    CoordinationSignal,
    PRSignalsConfig,
    SignalProvider,
    fetch_all_signals,
    fetch_github_signals,
    fetch_gitlab_signals,
    fetch_jira_signals,
)


class MemoryProvider:
    provider_id = "memory"

    def fetch_signals(self, config: dict[str, Any]) -> list[CoordinationSignal]:
        return []

    def needs_refresh(self, last_fetch: datetime, now: datetime) -> bool:
        return now > last_fetch


def test_signal_provider_protocol_is_public() -> None:
    assert isinstance(MemoryProvider(), SignalProvider)


def test_provider_aggregator_is_public() -> None:
    signal = CoordinationSignal(
        signal_id="jira:OPS:issue:OPS-123",
        provider="jira",
        source="OPS",
        artifact_ref="https://jira.example/browse/OPS-123",
        title="Auth migration blocker",
        excerpt=None,
        actor="alice",
        state="open",
        labels=("ambara",),
        created_at=datetime(2026, 6, 2, tzinfo=UTC),
        updated_at=datetime(2026, 6, 2, tzinfo=UTC),
        resolved_at=None,
        subject_refs=(),
        subject_areas=(),
    )
    config = PRSignalsConfig(jira_base_url="https://jira.example", jira_projects=("OPS",))

    with patch("ambara.sources.legacy_providers.fetch_jira_signals", return_value=[signal]):
        results = fetch_all_signals(config)

    assert len(results) == 1
    assert results[0].signal_id == signal.signal_id
    assert results[0].source == "OPS"


def test_provider_specific_fetchers_are_public() -> None:
    assert callable(fetch_gitlab_signals)
    assert callable(fetch_github_signals)
    assert callable(fetch_jira_signals)
