# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Deterministic scenarios used by performance baseline gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ambara.core.index import Index
from ambara.core.pr_signals import CoordinationGuidance, classify_source_inputs
from ambara.core.schema import (
    EntryStatus,
    EntryType,
    EscalationLevel,
    RecordedBy,
    Sensitivity,
)
from ambara.server_read import build_startup_v2_payload
from ambara.server_state import SyncHealth
from ambara.sources.types import (
    BodyPolicy,
    IdentityPolicy,
    SourceArtifact,
    SourceCategory,
    SourceOmissions,
    SourceProvenance,
    TextTrust,
)
from ambara.sources.types import (
    Sensitivity as SourceSensitivity,
)
from tests.core.conftest import make_entry

NOW = datetime(2026, 6, 11, 10, 0, tzinfo=UTC)
STARTUP_V2_PRODUCTION_DAY_BASELINE = "startup-v2-production-day"
_CLIENTS = ("codex", "claude-code", "cursor", "gemini")
_USER_COUNT = 100
_SERVICE_COUNT = 10


@dataclass(frozen=True)
class StartupPerformanceScenario:
    index: Index
    coordination: dict[str, object]
    source_health: dict[str, object]
    source_omissions: dict[str, int]
    service_id: int = 3

    def build_packet(self) -> dict[str, Any]:
        return build_startup_v2_payload(
            self.index,
            now=NOW + timedelta(minutes=15),
            sync_health=SyncHealth(last_success=NOW),
            freshness_warning_seconds=300,
            stale_after_seconds=900,
            repo="org/monorepo",
            goal=(
                f"continue service {self.service_id} handoff "
                "without missing source blockers"
            ),
            max_entries=5,
            coordination=self.coordination,
            source_health=self.source_health,
            source_omissions=self.source_omissions,
        )


def startup_v2_production_day_scenario() -> StartupPerformanceScenario:
    """Build deterministic inputs once so latency samples time startup compilation."""

    service_id = 3
    path = f"services/service-{service_id}/handler.py"
    guidance = classify_source_inputs(
        _production_day_source_artifacts(),
        repo="org/monorepo",
        paths=[path],
        now=NOW,
    )
    return StartupPerformanceScenario(
        index=_production_day_index(),
        coordination=_coordination_payload(guidance),
        source_health=_partial_source_health(),
        source_omissions=_source_omissions(),
        service_id=service_id,
    )


def startup_v2_production_day_packet() -> dict[str, Any]:
    """Build a realistic startup packet with source pressure and partial outage state."""

    return startup_v2_production_day_scenario().build_packet()


def _production_day_index() -> Index:
    index = Index()
    for user_id in range(_USER_COUNT):
        service_id = user_id % _SERVICE_COUNT
        client = _CLIENTS[user_id % len(_CLIENTS)]
        index.add(
            make_entry(
                entry_id=f"handoff-user-{user_id:03d}",
                title=f"Service {service_id} handoff from user-{user_id:03d}",
                entry_type=EntryType.ACTIVE,
                level=EscalationLevel.L0,
                status=EntryStatus.ACTIVE,
                created_at=NOW - timedelta(hours=4, minutes=user_id),
                updated_at=NOW - timedelta(minutes=user_id),
                projects=[f"service-{service_id}"],
                tags=["handoff", "normal-day"],
                body=(
                    f"user-{user_id:03d} left service {service_id} ready for the next agent "
                    "after tests, review, and the current rollout checklist."
                ),
                review_required=False,
                recorded_by=RecordedBy(client=client),
            )
        )

    for service_id in range(_SERVICE_COUNT):
        index.add(
            make_entry(
                entry_id=f"service-{service_id}-api-contract",
                title=f"Service {service_id} API contract decision",
                entry_type=EntryType.DECISION,
                level=EscalationLevel.L2,
                status=EntryStatus.ACTIVE,
                updated_at=NOW - timedelta(days=1),
                projects=[f"service-{service_id}"],
                tags=["api", "decision"],
                body=f"Service {service_id} uses the reviewed response envelope.",
            )
        )

    index.add(
        make_entry(
            entry_id="restricted-payroll-token",
            title="Restricted payroll token handling",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            status=EntryStatus.ACTIVE,
            sensitivity=Sensitivity.RESTRICTED,
            body="Restricted payroll token must never appear in broad context.",
        )
    )
    return index


def _production_day_source_artifacts() -> tuple[SourceArtifact, ...]:
    artifacts: list[SourceArtifact] = []
    for user_id in range(_USER_COUNT):
        provider = ("github", "gitlab", "jira")[user_id % 3]
        service_id = user_id % _SERVICE_COUNT
        path = f"services/service-{service_id}/handler.py"
        artifacts.append(
            _source_artifact(
                provider=provider,
                external_id=str(1000 + user_id),
                title=f"Service {service_id} review handoff for user-{user_id:03d}",
                excerpt="Review handoff touches the service handler for today's agents.",
                subject_refs=(path,),
                subject_areas=(f"services/service-{service_id}",),
                state="open" if user_id % 5 == 0 else "merged",
                updated_at=NOW - timedelta(minutes=user_id),
            )
        )
    return tuple(artifacts)


def _source_artifact(
    *,
    provider: str,
    external_id: str,
    title: str,
    excerpt: str,
    subject_refs: tuple[str, ...],
    subject_areas: tuple[str, ...],
    state: str,
    updated_at: datetime,
) -> SourceArtifact:
    if provider == "gitlab":
        artifact_ref = f"https://gitlab.com/org/monorepo/-/merge_requests/{external_id}"
        artifact_id = f"gitlab:org/monorepo:merge_request:{external_id}"
        source_instance_id = "repo-merge-requests"
        category = SourceCategory.FORGE_REVIEW
    elif provider == "jira":
        artifact_ref = f"https://jira.example/browse/AMB-{external_id}"
        artifact_id = f"jira:AMB-{external_id}"
        source_instance_id = "work-tracker"
        category = SourceCategory.WORK_TRACKER
    else:
        artifact_ref = f"https://github.com/org/monorepo/pull/{external_id}"
        artifact_id = f"github:org/monorepo:pull:{external_id}"
        source_instance_id = "repo-pull-requests"
        category = SourceCategory.FORGE_REVIEW
    return SourceArtifact(
        artifact_id=artifact_id,
        provider_id=provider,
        source_instance_id=source_instance_id,
        category=category,
        artifact_type="review" if category is SourceCategory.FORGE_REVIEW else "issue",
        artifact_ref=artifact_ref,
        title=title,
        excerpt=excerpt,
        state=state,
        labels=("ambara",),
        subject_refs=subject_refs,
        subject_areas=subject_areas,
        created_at=NOW - timedelta(hours=6),
        updated_at=updated_at,
        resolved_at=updated_at if state == "merged" else None,
        provenance=SourceProvenance(
            provider_id=provider,
            source_instance_id=source_instance_id,
            external_id=external_id,
            url=artifact_ref,
            fetched_at=NOW,
            source_updated_at=updated_at,
        ),
        body_policy=BodyPolicy.EXCERPT,
        identity_policy=IdentityPolicy.OMIT,
        text_trust=TextTrust.UNTRUSTED_EXTERNAL,
        sensitivity=SourceSensitivity.STANDARD,
        omissions=SourceOmissions(),
    )


def _coordination_payload(guidance: list[CoordinationGuidance]) -> dict[str, object]:
    return {
        "status": "ok",
        "summary": f"{len(guidance)} source input(s) found.",
        "guidance": [
            {
                "effect": item.effect,
                "urgency": item.urgency,
                "confidence": item.confidence,
                "summary": item.summary,
                "evidence": [
                    {"repo": evidence.repo, "url": evidence.url} for evidence in item.evidence
                ],
            }
            for item in guidance
        ],
        "privacy_boundary": ["fixture source artifacts are sanitized by core"],
    }


def _partial_source_health() -> dict[str, object]:
    return {
        "configured": 4,
        "fresh": 2,
        "stale": 1,
        "unavailable": 1,
        "error": 0,
        "sources": [
            {
                "id": "repo-pull-requests",
                "provider": "github",
                "status": "stale",
                "baseline_available": True,
                "rate_limited": True,
            },
            {
                "id": "team-docs",
                "provider": "notion",
                "status": "unavailable",
                "baseline_available": False,
                "rate_limited": False,
            },
        ],
    }


def _source_omissions() -> dict[str, int]:
    return {
        "privacy": 4,
        "safety": 1,
        "budget": 63,
        "freshness": 2,
        "source_error": 1,
        "total": 71,
    }
