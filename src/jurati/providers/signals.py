"""Coordination signal provider entrypoints.

Aggregates signals from all configured providers (GitHub PRs, Jira issues).
Each provider is called independently — a failure in one does not block the other.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from jurati.core.pr_signals import CoordinationSignal, PRSignal
from jurati.git.config import PRSignalsConfig
from jurati.providers.fixture_signals import fetch_fixture_signals
from jurati.providers.github_prs import fetch_all_signals as fetch_github_signals
from jurati.providers.jira_issues import fetch_all_signals as fetch_jira_signals

logger = logging.getLogger(__name__)


def fetch_all_signals(
    config: PRSignalsConfig,
    *,
    token: str | None = None,
) -> Sequence[PRSignal | CoordinationSignal]:
    if config.fixture_path:
        return fetch_fixture_signals(config)

    results: list[PRSignal | CoordinationSignal] = []

    if config.repos:
        try:
            results.extend(fetch_github_signals(config, token=token))
        except Exception:
            logger.warning("GitHub signal fetch failed", exc_info=True)

    if config.jira_base_url and config.jira_projects:
        try:
            results.extend(fetch_jira_signals(config, token=token))
        except Exception:
            logger.warning("Jira signal fetch failed", exc_info=True)

    return results
