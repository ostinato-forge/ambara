# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Adapters between legacy signal shapes and source artifacts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, cast

from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.sources.types import (
    BodyPolicy,
    IdentityPolicy,
    Sensitivity,
    SourceArtifact,
    SourceCategory,
    SourceOmissions,
    SourceProvenance,
    TextTrust,
)

LegacySignal = PRSignal | CoordinationSignal


def source_artifact_from_legacy_signal(
    signal: LegacySignal,
    *,
    source_instance_id: str | None = None,
    fetched_at: datetime | None = None,
    body_policy: BodyPolicy = BodyPolicy.EXCERPT,
    identity_policy: IdentityPolicy = IdentityPolicy.OMIT,
    category: SourceCategory | None = None,
) -> SourceArtifact:
    if isinstance(signal, PRSignal):
        return source_artifact_from_pr_signal(
            signal,
            source_instance_id=source_instance_id,
            fetched_at=fetched_at,
            body_policy=body_policy,
            identity_policy=identity_policy,
            category=category,
        )
    return source_artifact_from_coordination_signal(
        signal,
        source_instance_id=source_instance_id,
        fetched_at=fetched_at,
        body_policy=body_policy,
        identity_policy=identity_policy,
        category=category,
    )


def source_artifact_from_pr_signal(
    signal: PRSignal,
    *,
    source_instance_id: str | None = None,
    fetched_at: datetime | None = None,
    body_policy: BodyPolicy = BodyPolicy.EXCERPT,
    identity_policy: IdentityPolicy = IdentityPolicy.OMIT,
    category: SourceCategory | None = None,
) -> SourceArtifact:
    provider = signal.provider
    artifact_type = "merge_request" if provider == "gitlab" else "pull_request"
    instance_id = source_instance_id or f"legacy-{provider}-review-signals"
    return SourceArtifact(
        artifact_id=signal.signal_id,
        provider_id=provider,
        source_instance_id=instance_id,
        category=category or SourceCategory.FORGE_REVIEW,
        artifact_type=artifact_type,
        artifact_ref=signal.url,
        title=signal.title,
        excerpt=signal.body_excerpt,
        state=signal.state,
        labels=signal.labels,
        subject_refs=signal.changed_paths,
        subject_areas=signal.target_areas,
        subject_refs_status=signal.changed_paths_status,
        created_at=signal.created_at,
        updated_at=signal.updated_at,
        resolved_at=signal.merged_at,
        provenance=SourceProvenance(
            provider_id=provider,
            source_instance_id=instance_id,
            external_id=signal.signal_id,
            url=signal.url,
            fetched_at=fetched_at,
            source_updated_at=signal.updated_at,
        ),
        body_policy=body_policy,
        identity_policy=identity_policy,
        text_trust=TextTrust.UNTRUSTED_EXTERNAL,
        sensitivity=Sensitivity.STANDARD,
        omissions=SourceOmissions(),
    )


def source_artifact_from_coordination_signal(
    signal: CoordinationSignal,
    *,
    source_instance_id: str | None = None,
    fetched_at: datetime | None = None,
    body_policy: BodyPolicy = BodyPolicy.EXCERPT,
    identity_policy: IdentityPolicy = IdentityPolicy.OMIT,
    category: SourceCategory | None = None,
) -> SourceArtifact:
    instance_id = source_instance_id or f"legacy-{signal.provider}-signals"
    return SourceArtifact(
        artifact_id=signal.signal_id,
        provider_id=signal.provider,
        source_instance_id=instance_id,
        category=category or _category_for_legacy_provider(signal.provider),
        artifact_type=_artifact_type_for_legacy_provider(signal.provider),
        artifact_ref=signal.artifact_ref,
        title=signal.title,
        excerpt=signal.excerpt,
        state=signal.state,
        labels=signal.labels,
        subject_refs=signal.subject_refs,
        subject_areas=signal.subject_areas,
        subject_refs_status=signal.subject_refs_status,
        created_at=signal.created_at,
        updated_at=signal.updated_at,
        resolved_at=signal.resolved_at,
        provenance=SourceProvenance(
            provider_id=signal.provider,
            source_instance_id=instance_id,
            external_id=signal.signal_id,
            url=signal.artifact_ref,
            fetched_at=fetched_at,
            source_updated_at=signal.updated_at,
        ),
        body_policy=body_policy,
        identity_policy=identity_policy,
        text_trust=TextTrust.UNTRUSTED_EXTERNAL,
        sensitivity=Sensitivity.STANDARD,
        omissions=SourceOmissions(),
    )


def coordination_signal_from_source_artifact(
    artifact: SourceArtifact,
    *,
    now: datetime,
    actor: str = "unknown",
) -> CoordinationSignal:
    return CoordinationSignal(
        signal_id=artifact.artifact_id,
        provider=artifact.provider_id,
        source=_coordination_source_from_artifact(artifact),
        artifact_ref=artifact.artifact_ref,
        title=artifact.title,
        excerpt=artifact.excerpt,
        actor=actor,
        state=artifact.state,
        labels=artifact.labels,
        created_at=artifact.created_at or now,
        updated_at=artifact.updated_at or now,
        resolved_at=artifact.resolved_at,
        subject_refs=artifact.subject_refs,
        subject_areas=artifact.subject_areas,
        subject_refs_status=artifact.subject_refs_status,
    )


def legacy_signal_from_source_artifact(
    artifact: SourceArtifact,
    *,
    now: datetime,
) -> LegacySignal:
    if artifact.provider_id in {"github", "gitlab"} and artifact.artifact_type in {
        "pull_request",
        "merge_request",
    }:
        repo, number = _review_repo_and_number(artifact)
        return PRSignal(
            signal_id=artifact.artifact_id,
            provider=cast(Literal["github", "gitlab"], artifact.provider_id),
            repo=repo,
            number=number,
            url=artifact.artifact_ref,
            title=artifact.title,
            body_excerpt=artifact.excerpt,
            author="unknown",
            state=_review_state(artifact.state),
            labels=artifact.labels,
            created_at=artifact.created_at or now,
            updated_at=artifact.updated_at or now,
            merged_at=artifact.resolved_at,
            changed_paths=artifact.subject_refs,
            target_areas=artifact.subject_areas,
            changed_paths_status=artifact.subject_refs_status,
        )
    return coordination_signal_from_source_artifact(
        artifact,
        now=now,
        actor="unknown",
    )


def _category_for_legacy_provider(provider_id: str) -> SourceCategory:
    if provider_id == "jira":
        return SourceCategory.WORK_TRACKER
    if provider_id == "fixture":
        return SourceCategory.FIXTURE
    return SourceCategory.FORGE_REVIEW


def _review_repo_and_number(artifact: SourceArtifact) -> tuple[str, int]:
    parsed = _review_repo_and_number_from_signal_id(artifact.artifact_id)
    if parsed is not None:
        return parsed
    parsed = _review_repo_and_number_from_url(artifact.provider_id, artifact.artifact_ref)
    if parsed is not None:
        return parsed
    return artifact.source_instance_id, 0


def _review_repo_and_number_from_signal_id(signal_id: str) -> tuple[str, int] | None:
    parts = signal_id.split(":")
    for marker in ("pull", "merge_request"):
        if marker in parts:
            marker_index = parts.index(marker)
            if marker_index < 2 or marker_index + 1 >= len(parts):
                return None
            repo = ":".join(parts[1:marker_index])
            try:
                number = int(parts[marker_index + 1])
            except ValueError:
                return None
            return repo, number
    return None


def _review_repo_and_number_from_url(
    provider_id: str,
    artifact_ref: str,
) -> tuple[str, int] | None:
    if provider_id == "github":
        match = re.search(r"/([^/]+/[^/]+)/pull/(\d+)$", artifact_ref)
    elif provider_id == "gitlab":
        match = re.search(r"/(.+?)/-/merge_requests/(\d+)$", artifact_ref)
    else:
        return None
    if match is None:
        return None
    return match.group(1), int(match.group(2))


def _coordination_source_from_artifact(artifact: SourceArtifact) -> str:
    parts = artifact.artifact_id.split(":")
    if artifact.provider_id == "jira" and len(parts) >= 2:
        return parts[1].split("-", 1)[0]
    if artifact.provider_id == "fixture" and len(parts) >= 2:
        return parts[1]
    return artifact.source_instance_id


def _review_state(value: str) -> Literal["open", "merged", "closed"]:
    normalized = value.lower()
    if normalized in {"open", "merged", "closed"}:
        return cast(Literal["open", "merged", "closed"], normalized)
    if normalized in {"resolved", "done"}:
        return "merged"
    return "open"


def _artifact_type_for_legacy_provider(provider_id: str) -> str:
    if provider_id == "jira":
        return "issue"
    if provider_id == "gitlab":
        return "merge_request"
    if provider_id == "github":
        return "pull_request"
    return "coordination_signal"
