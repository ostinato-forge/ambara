# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared signal cache refresh helpers for server surfaces."""

from __future__ import annotations

import logging
from datetime import datetime

from ambara.git.config import PRSignalsConfig
from ambara.server_state import ServerState
from ambara.server_types import BlockingRunner, SignalFetcher


def signals_configured(config: PRSignalsConfig) -> bool:
    return bool(
        config.fixture_path or config.repos or (config.jira_base_url and config.jira_projects)
    )


async def refresh_signal_cache(
    state: ServerState,
    *,
    config: PRSignalsConfig,
    now: datetime,
    fetch_signals: SignalFetcher,
    run_blocking: BlockingRunner,
    logger: logging.Logger,
    failure_log_message: str,
) -> None:
    cache = state.signal_cache
    if not signals_configured(config) or not cache.needs_refresh(now):
        return

    try:
        signals = await run_blocking(lambda: fetch_signals(config))
        if signals or cache.size == 0:
            cache.update(signals, now=now)
        else:
            cache.evict_stale(now=now)
        state.signal_health.last_success = now
        state.signal_health.last_error = None
        state.signal_health.consecutive_failures = 0
    except Exception as exc:
        state.signal_health.last_failure = now
        state.signal_health.last_error = str(exc)
        state.signal_health.consecutive_failures += 1
        logger.warning(failure_log_message, exc_info=True)
