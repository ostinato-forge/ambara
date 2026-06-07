# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Source-input assembly for the CLI startup file adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ambara.server_coordination import build_coordination_payload_from_source_inputs
from ambara.server_signals import source_inputs_configured
from ambara.server_snapshot import (
    compiler_health_for_source_report,
    startup_source_health_payload_from_report,
    startup_source_omissions_payload_from_report,
)
from ambara.server_state import SyncHealth
from ambara.sources.config import SourceInputsConfig
from ambara.sources.runtime import fetch_source_runtime_report
from ambara.sources.types import SourceArtifact


class StartupSourceRefreshError(RuntimeError):
    """Raised when startup cannot inspect configured source inputs safely."""


@dataclass(frozen=True)
class StartupSourceContext:
    sync_health: SyncHealth
    coordination: dict[str, object] | None = None
    source_health: dict[str, object] | None = None
    source_omissions: dict[str, int] | None = None


def startup_source_context(
    config: SourceInputsConfig,
    *,
    repo: str | None,
    goal: str | None,
    now: datetime,
    sync_health: SyncHealth,
    token: str | None = None,
) -> StartupSourceContext:
    if not source_inputs_configured(config):
        return StartupSourceContext(sync_health=sync_health)

    try:
        source_runtime = fetch_source_runtime_report(config, token=token, now=now)
    except Exception as exc:
        raise StartupSourceRefreshError(
            "Source input refresh failed; run ambara sources doctor for details"
        ) from exc

    source_report = source_runtime.source_report
    return StartupSourceContext(
        sync_health=compiler_health_for_source_report(
            source_report,
            fallback=sync_health,
        ),
        coordination=_coordination_from_report(
            config,
            repo=repo,
            goal=goal,
            now=now,
            artifacts=source_report.artifacts,
            unavailable=source_report.status == "unavailable",
        ),
        source_health=startup_source_health_payload_from_report(source_report, now=now),
        source_omissions=startup_source_omissions_payload_from_report(source_report),
    )


def _coordination_from_report(
    config: SourceInputsConfig,
    *,
    repo: str | None,
    goal: str | None,
    now: datetime,
    artifacts: tuple[SourceArtifact, ...],
    unavailable: bool,
) -> dict[str, object]:
    if artifacts:
        return build_coordination_payload_from_source_inputs(
            artifacts,
            repo=repo,
            goal=goal,
            paths=None,
            now=now,
            recency_days=config.recency_days,
        )
    if unavailable:
        return _unavailable_source_coordination_payload()
    return build_coordination_payload_from_source_inputs(
        (),
        repo=repo,
        goal=goal,
        paths=None,
        now=now,
        recency_days=config.recency_days,
    )


def _unavailable_source_coordination_payload() -> dict[str, object]:
    return {
        "status": "unavailable",
        "summary": "Configured source inputs are unavailable.",
        "guidance": [],
        "agent_instruction": (
            "Do not treat the absence of coordination source inputs as a green light."
        ),
        "privacy_boundary": [
            "only configured repos are checked",
            "only source inputs carrying the configured ambara label are used",
            (
                "unlabeled reviews, comments, chats, editor activity, "
                "and read activity are not mined"
            ),
            "source actor identities are not included in coordination source inputs",
        ],
    }
