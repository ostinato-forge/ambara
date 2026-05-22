"""Coordination signal provider entrypoints."""

from __future__ import annotations

from collections.abc import Sequence

from jurati.core.pr_signals import CoordinationSignal, PRSignal
from jurati.git.config import PRSignalsConfig
from jurati.providers.fixture_signals import fetch_fixture_signals
from jurati.providers.github_prs import fetch_all_signals as fetch_github_signals
from jurati.providers.jira_issues import fetch_all_signals as fetch_jira_signals


def fetch_all_signals(
    config: PRSignalsConfig,
    *,
    token: str | None = None,
) -> Sequence[PRSignal | CoordinationSignal]:
    if config.fixture_path:
        return fetch_fixture_signals(config)
    if config.provider == "github":
        return fetch_github_signals(config, token=token)
    if config.provider == "jira":
        return fetch_jira_signals(config, token=token)
    return []
