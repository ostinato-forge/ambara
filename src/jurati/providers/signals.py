"""Coordination signal provider entrypoints."""

from __future__ import annotations

from jurati.core.pr_signals import PRSignal
from jurati.git.config import PRSignalsConfig
from jurati.providers.fixture_signals import fetch_fixture_signals
from jurati.providers.github_prs import fetch_all_signals as fetch_github_signals


def fetch_all_signals(
    config: PRSignalsConfig,
    *,
    token: str | None = None,
) -> list[PRSignal]:
    if config.fixture_path:
        return fetch_fixture_signals(config)
    if config.provider == "github":
        return fetch_github_signals(config, token=token)
    return []
