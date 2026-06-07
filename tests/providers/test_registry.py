# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for signal provider registry and entry-point discovery."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ambara.core.pr_signals import CoordinationSignal
from ambara.git.config import PRSignalsConfig
from ambara.providers.registry import (
    SIGNAL_PROVIDER_ENTRY_POINT_GROUP,
    RegisteredSignalProvider,
    SignalProviderRegistryError,
    built_in_signal_providers,
    discover_entry_point_signal_providers,
    resolve_signal_provider,
)


def test_registry_resolves_built_in_review_providers() -> None:
    providers = built_in_signal_providers()

    assert providers["github"].source == "built-in"
    assert providers["gitlab"].source == "built-in"
    assert providers["jira"].source == "built-in"
    assert resolve_signal_provider("GitHub") == providers["github"]
    assert resolve_signal_provider("jira") == providers["jira"]


def test_unknown_provider_returns_none() -> None:
    assert resolve_signal_provider("not-installed", eps=()) is None


def test_fake_entry_point_provider_is_discoverable() -> None:
    provider = _MemoryProvider()
    entry_point = _FakeEntryPoint("linear", provider)

    providers = discover_entry_point_signal_providers((entry_point,))

    assert providers["linear"].display_name == "Linear"
    assert providers["linear"].source == "entry-point"
    assert providers["linear"].fetch(PRSignalsConfig(), token=None) == []


def test_entry_point_can_be_plain_callable() -> None:
    def fetch(config: PRSignalsConfig, token: str | None = None) -> list[CoordinationSignal]:
        return []

    provider = resolve_signal_provider("asana", eps=(_FakeEntryPoint("asana", fetch),))

    assert isinstance(provider, RegisteredSignalProvider)
    assert provider.fetch(PRSignalsConfig(), token=None) == []


def test_entry_point_cannot_shadow_built_in_provider() -> None:
    entry_point = _FakeEntryPoint("github", _MemoryProvider("github", "Fake GitHub"))

    with pytest.raises(SignalProviderRegistryError, match="refusing to shadow"):
        discover_entry_point_signal_providers((entry_point,))

    with pytest.raises(SignalProviderRegistryError, match="refusing to shadow"):
        resolve_signal_provider("github", eps=(entry_point,))


def test_duplicate_entry_point_provider_ids_fail_closed() -> None:
    first = _FakeEntryPoint("linear", _MemoryProvider("linear", "Linear"))
    second = _FakeEntryPoint("linear-alt", _MemoryProvider("linear", "Linear Alt"))

    with pytest.raises(SignalProviderRegistryError, match="registered more than once"):
        discover_entry_point_signal_providers((first, second))


class _MemoryProvider:
    def __init__(self, provider_id: str = "linear", display_name: str = "Linear") -> None:
        self.provider_id = provider_id
        self.display_name = display_name

    def fetch_signals(
        self, config: PRSignalsConfig, token: str | None = None
    ) -> list[CoordinationSignal]:
        return []


@dataclass(frozen=True)
class _FakeEntryPoint:
    name: str
    loaded: object
    group: str = SIGNAL_PROVIDER_ENTRY_POINT_GROUP
    value: str = "tests.providers.fake:provider"

    def load(self) -> object:
        return self.loaded
