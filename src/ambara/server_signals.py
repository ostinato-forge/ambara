# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared source and compatibility signal refresh helpers for server surfaces."""

from __future__ import annotations

import logging
from datetime import datetime

from ambara.server_state import ServerState
from ambara.server_types import BlockingRunner
from ambara.sources.config import SourceInputsConfig
from ambara.sources.inspect import SourceInspectionReport
from ambara.sources.runtime import fetch_source_runtime_report

_SOURCE_REPORT_REFRESH_INTERVAL_SECONDS = 300


def source_inputs_configured(config: SourceInputsConfig) -> bool:
    return bool(
        config.fixture_path or config.repos or (config.jira_base_url and config.jira_projects)
    )


async def refresh_source_inputs(
    state: ServerState,
    *,
    config: SourceInputsConfig,
    now: datetime,
    run_blocking: BlockingRunner,
    logger: logging.Logger,
    failure_log_message: str,
) -> None:
    if not source_inputs_configured(config):
        return
    if not source_report_needs_refresh(state, now=now):
        return
    await _refresh_source_report(
        state,
        config=config,
        now=now,
        run_blocking=run_blocking,
        logger=logger,
        failure_log_message=failure_log_message,
    )


async def _refresh_source_report(
    state: ServerState,
    *,
    config: SourceInputsConfig,
    now: datetime,
    run_blocking: BlockingRunner,
    logger: logging.Logger,
    failure_log_message: str,
) -> None:
    try:
        report = await run_blocking(
            lambda: fetch_source_runtime_report(
                config,
                now=now,
                source_cache=state.source_cache,
            )
        )
    except Exception as exc:
        state.source_report_last_refresh = now
        state.source_health.last_failure = now
        state.source_health.last_error = str(exc)
        state.source_health.consecutive_failures += 1
        logger.warning(failure_log_message, exc_info=True)
        return

    state.source_report = report.source_report
    state.source_report_last_refresh = now
    _sync_source_refresh_health_from_report(state, report.source_report)
    errors = report.source_report.source_errors

    if errors:
        logger.warning(failure_log_message)


def source_report_needs_refresh(state: ServerState, *, now: datetime) -> bool:
    if state.source_report_last_refresh is None:
        return True
    if state.source_report is not None:
        for inspection in state.source_report.sources:
            stale_after = inspection.health.stale_after
            if stale_after is not None and stale_after <= now:
                return True
    return (
        now - state.source_report_last_refresh
    ).total_seconds() >= _SOURCE_REPORT_REFRESH_INTERVAL_SECONDS


def _sync_source_refresh_health_from_report(
    state: ServerState, report: SourceInspectionReport
) -> None:
    aggregate = report.aggregate_health
    state.source_health.last_success = aggregate.last_success
    state.source_health.last_failure = aggregate.last_failure
    state.source_health.last_error = aggregate.message
    state.source_health.consecutive_failures = aggregate.consecutive_failures
