# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Promote-tool orchestration: fetch a labeled source artifact, plan its
promotion to durable knowledge through the shared remember core, and format the
agent-facing receipt. Glue only — the decision lives in ``sources.promote`` /
``core.remember``; the write lives in ``git.remember``. ``server.py`` registers
the thin MCP tool and delegates here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ambara.core.content_policy import WritePolicy
from ambara.core.content_policy_config import default_config
from ambara.core.schema import EntryType
from ambara.git.remember import RememberOutcome, materialize_remember
from ambara.server_async import run_blocking
from ambara.server_read import _parse_enum
from ambara.server_state import ServerState
from ambara.sources.promote import PromotionResult, plan_source_promotion
from ambara.sources.types import SourceArtifact


def find_source_artifact(state: ServerState, artifact_id: str) -> SourceArtifact | None:
    """Locate a fetched source artifact by id in the current source report."""
    report = state.source_report
    if report is None:
        return None
    for artifact in report.artifacts:
        if artifact.artifact_id == artifact_id:
            return artifact
    return None


def plan_promotion(
    state: ServerState,
    artifact: SourceArtifact,
    *,
    entry_type: EntryType,
    now: datetime,
) -> PromotionResult:
    """Plan the promotion against the live knowledge index + content policy. Pure."""
    content_policy = state.content_policy or WritePolicy(default_config())
    return plan_source_promotion(
        artifact,
        entry_type=entry_type,
        index_entries=list(state.index.entries.values()),
        content_policy=content_policy,
        now=now,
    )


async def run_promote(
    state: ServerState,
    *,
    artifact_id: str,
    type: str | None,
    dry_run: bool,
    now: datetime,
) -> dict[str, Any]:
    """Resolve the artifact, plan, and (unless dry-run) open the review branch."""
    if type is None:
        entry_type = EntryType.PROJECT
    else:
        entry_type, err = _parse_enum(type, EntryType, "type")
        if err:
            return err

    artifact = find_source_artifact(state, artifact_id)
    if artifact is None:
        return artifact_not_found_response(artifact_id)

    result = plan_promotion(state, artifact, entry_type=entry_type, now=now)
    if result.action == "reject":
        return promotion_rejected_response(artifact_id, result)
    if dry_run:
        return promotion_dry_run_response(artifact_id, entry_type, result)

    assert result.plan is not None  # create plan guaranteed by action != "reject"
    plan = result.plan
    outcome = await run_blocking(
        lambda: materialize_remember(state.repo_path, plan, main_branch=state.config.main_branch)
    )
    return promotion_applied_response(artifact_id, entry_type, outcome)


def artifact_not_found_response(artifact_id: str) -> dict[str, Any]:
    return {
        "error": "artifact_not_found",
        "artifact_id": artifact_id,
        "hint": "Run the sources doctor/source-smoke surface to see available artifact ids.",
    }


def promotion_rejected_response(artifact_id: str, result: PromotionResult) -> dict[str, Any]:
    return {
        "status": "rejected",
        "artifact_id": artifact_id,
        "reason": result.reject_reason,
        "receipt": result.plan.receipt if result.plan is not None else {"action": "reject"},
    }


def promotion_dry_run_response(
    artifact_id: str, entry_type: EntryType, result: PromotionResult
) -> dict[str, Any]:
    plan = result.plan
    assert plan is not None and plan.intent is not None  # create plan invariant
    return {
        "status": "dry_run",
        "artifact_id": artifact_id,
        "entry_id": plan.intent.entry_id,
        "entry_type": entry_type.value,
        "branch": plan.intent.branch,
        "level": str(plan.level),
        "requires_pr": plan.requires_pr,
        "contradiction_ids": list(plan.contradiction_ids),
        "redactions": list(plan.redaction_rule_ids),
        "receipt": plan.receipt,
    }


def promotion_applied_response(
    artifact_id: str, entry_type: EntryType, outcome: RememberOutcome
) -> dict[str, Any]:
    return {
        "status": "ok",
        "artifact_id": artifact_id,
        "entry_id": outcome.entry_id,
        "entry_type": entry_type.value,
        "branch": outcome.branch,
        "sha": outcome.sha,
        "reused_existing": outcome.reused_existing,
        "write_mode": "review_branch",
        "receipt": outcome.receipt,
    }
