# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Registry for the built-in review-signal providers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.providers.github_prs import fetch_all_signals as fetch_github_signals
from ambara.providers.gitlab_mrs import fetch_all_signals as fetch_gitlab_signals
from ambara.providers.jira_issues import fetch_all_signals as fetch_jira_signals
from ambara.sources.config import PRSignalsConfig

SignalResult = Sequence[PRSignal | CoordinationSignal]


class SignalFetcher(Protocol):
    def __call__(
        self,
        config: PRSignalsConfig,
        *,
        token: str | None = None,
    ) -> SignalResult: ...


@dataclass(frozen=True)
class RegisteredSignalProvider:
    provider_id: str
    display_name: str
    fetch: SignalFetcher
    source: str = "built-in"


def built_in_signal_providers() -> dict[str, RegisteredSignalProvider]:
    return {
        "github": RegisteredSignalProvider(
            provider_id="github",
            display_name="GitHub",
            fetch=fetch_github_signals,
        ),
        "gitlab": RegisteredSignalProvider(
            provider_id="gitlab",
            display_name="GitLab",
            fetch=fetch_gitlab_signals,
        ),
        "jira": RegisteredSignalProvider(
            provider_id="jira",
            display_name="Jira",
            fetch=fetch_jira_signals,
        ),
    }


def resolve_signal_provider(provider_id: str) -> RegisteredSignalProvider | None:
    return built_in_signal_providers().get(_normalize_provider_id(provider_id))


def _normalize_provider_id(provider_id: str) -> str:
    return provider_id.strip().lower().replace("_", "-")
