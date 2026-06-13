# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti
"""Tests for source-artifact -> durable-knowledge promotion (distill + plan)."""

from __future__ import annotations

from datetime import UTC, datetime

from ambara.core.content_policy import WritePolicy
from ambara.core.content_policy_config import default_config
from ambara.core.schema import EntryType
from ambara.sources.promote import (
    plan_source_promotion,
    promotable_reject_reason,
    promote_candidate_from_artifact,
)
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

NOW = datetime(2026, 6, 13, tzinfo=UTC)


def _policy() -> WritePolicy:
    return WritePolicy(default_config())


def _artifact(**kw: object) -> SourceArtifact:
    base: dict[str, object] = dict(
        artifact_id="github:42",
        provider_id="github",
        source_instance_id="gh-main",
        category=SourceCategory.FORGE_REVIEW,
        artifact_type="pull_request",
        artifact_ref="org/repo#42",
        title="Adopt gRPC internally",
        excerpt="We will use gRPC for internal services.",
        state="merged",
        labels=("decision",),
        subject_refs=(),
        subject_areas=("api",),
        created_at=NOW,
        updated_at=NOW,
        resolved_at=None,
        provenance=SourceProvenance(
            provider_id="github",
            source_instance_id="gh-main",
            external_id="42",
            url="https://github.com/org/repo/pull/42",
        ),
        body_policy=BodyPolicy.EXCERPT,
        identity_policy=IdentityPolicy.OMIT,
        text_trust=TextTrust.UNTRUSTED_EXTERNAL,
        sensitivity=Sensitivity.STANDARD,
        omissions=SourceOmissions(),
    )
    base.update(kw)
    return SourceArtifact(**base)  # type: ignore[arg-type]


def test_distill_builds_compact_candidate_with_provenance() -> None:
    cand = promote_candidate_from_artifact(_artifact(), entry_type=EntryType.PROJECT, now=NOW)
    assert cand.kind == "promote"
    assert cand.entry_id == "github-42"
    assert cand.title == "Adopt gRPC internally"
    assert cand.body == "We will use gRPC for internal services."
    assert cand.provenance is not None
    assert cand.provenance.provider == "github"
    assert cand.provenance.external_id == "42"
    assert "api" in cand.projects  # subject_areas -> projects
    assert "decision" in cand.tags  # labels -> tags
    assert cand.branch_prefix == "ambara/promote"
    assert len(cand.body) <= 240  # distilled, not a raw dump


def test_promotable_reject_restricted() -> None:
    reason = promotable_reject_reason(_artifact(sensitivity=Sensitivity.RESTRICTED))
    assert reason is not None
    assert "restricted" in reason.lower()


def test_promotable_reject_blocked_text() -> None:
    reason = promotable_reject_reason(_artifact(text_trust=TextTrust.BLOCKED_EXTERNAL))
    assert reason is not None


def test_promotable_reject_empty_title() -> None:
    assert promotable_reject_reason(_artifact(title="   ")) is not None


def test_promotable_clean_artifact() -> None:
    assert promotable_reject_reason(_artifact()) is None


def test_plan_source_promotion_create() -> None:
    result = plan_source_promotion(
        _artifact(),
        entry_type=EntryType.PROJECT,
        index_entries=[],
        content_policy=_policy(),
        now=NOW,
    )
    assert result.action == "create"
    assert result.plan is not None
    assert result.plan.intent is not None
    assert "<!-- ambara:provenance:v1 -->" in result.plan.intent.content


def test_plan_source_promotion_rejects_restricted_before_planning() -> None:
    result = plan_source_promotion(
        _artifact(sensitivity=Sensitivity.RESTRICTED),
        entry_type=EntryType.PROJECT,
        index_entries=[],
        content_policy=_policy(),
        now=NOW,
    )
    assert result.action == "reject"
    assert result.plan is None
    assert result.reject_reason is not None


def test_plan_source_promotion_rejects_on_content_policy() -> None:
    artifact = _artifact(excerpt="leaked -----BEGIN PRIVATE KEY-----")  # gitleaks:allow
    result = plan_source_promotion(
        artifact,
        entry_type=EntryType.PROJECT,
        index_entries=[],
        content_policy=_policy(),
        now=NOW,
    )
    assert result.action == "reject"
    assert result.reject_reason is not None


def test_distill_slug_pads_short_ids() -> None:
    artifact = _artifact(
        provenance=SourceProvenance(
            provider_id="x",
            source_instance_id="s",
            external_id="",
            url="https://example/x",
        )
    )
    cand = promote_candidate_from_artifact(artifact, entry_type=EntryType.PROJECT, now=NOW)
    assert len(cand.entry_id) >= 3  # padded so it satisfies schema.ID_PATTERN
