# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Public Ambara provider API."""

from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.providers.errors import SignalProviderError
from ambara.providers.github_prs import fetch_all_signals as fetch_github_signals
from ambara.providers.gitlab_mrs import fetch_all_signals as fetch_gitlab_signals
from ambara.providers.jira_issues import fetch_all_signals as fetch_jira_signals
from ambara.providers.protocol import SignalProvider
from ambara.sources.config import PRSignalsConfig

__all__ = [
    "CoordinationSignal",
    "PRSignal",
    "PRSignalsConfig",
    "SignalProvider",
    "SignalProviderError",
    "fetch_all_signals",
    "fetch_gitlab_signals",
    "fetch_github_signals",
    "fetch_jira_signals",
]


def __getattr__(name: str) -> object:
    if name == "fetch_all_signals":
        from ambara.providers.signals import fetch_all_signals

        return fetch_all_signals
    raise AttributeError(f"module 'ambara.providers' has no attribute {name!r}")
