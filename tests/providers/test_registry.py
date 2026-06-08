# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for the built-in signal provider registry."""

from __future__ import annotations

from ambara.providers.registry import (
    built_in_signal_providers,
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
    assert resolve_signal_provider("not-installed") is None
