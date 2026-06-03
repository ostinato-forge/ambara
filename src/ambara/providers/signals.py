# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Coordination signal provider entrypoints.

Aggregates signals from all configured providers (GitHub PRs, Jira issues).
Each provider is called independently — a failure in one does not block the other.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.git.config import PRSignalsConfig
from ambara.providers.errors import SignalProviderError
from ambara.providers.fixture_signals import fetch_fixture_signals
from ambara.providers.github_prs import fetch_all_signals as fetch_github_signals
from ambara.providers.jira_issues import fetch_all_signals as fetch_jira_signals

logger = logging.getLogger(__name__)


def fetch_all_signals(
    config: PRSignalsConfig,
    *,
    token: str | None = None,
) -> Sequence[PRSignal | CoordinationSignal]:
    if config.fixture_path:
        return fetch_fixture_signals(config)

    results: list[PRSignal | CoordinationSignal] = []
    errors: list[str] = []

    if config.repos:
        try:
            results.extend(fetch_github_signals(config, token=token))
        except Exception as exc:
            errors.append(f"GitHub: {exc}")
            logger.warning("GitHub signal fetch failed", exc_info=True)

    if config.jira_base_url and config.jira_projects:
        try:
            results.extend(fetch_jira_signals(config, token=token))
        except Exception as exc:
            errors.append(f"Jira: {exc}")
            logger.warning("Jira signal fetch failed", exc_info=True)

    if errors and not results:
        raise SignalProviderError("; ".join(errors))

    return results
