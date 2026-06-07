# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Testing helpers for source providers and source-kernel fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

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


def make_source_artifact(**overrides: object) -> SourceArtifact:
    now = datetime(2026, 6, 5, tzinfo=UTC)
    fields: dict[str, object] = {
        "artifact_id": "github:org/api:pull:42",
        "provider_id": "github",
        "source_instance_id": "repo-reviews",
        "category": SourceCategory.FORGE_REVIEW,
        "artifact_type": "pull_request",
        "artifact_ref": "https://github.com/org/api/pull/42",
        "title": "Review the auth migration",
        "excerpt": "API and web agents should coordinate on the auth contract.",
        "state": "open",
        "labels": ("ambara",),
        "subject_refs": ("contracts/auth/session.json",),
        "subject_areas": ("contracts/auth",),
        "subject_refs_status": "available",
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
        "provenance": SourceProvenance(
            provider_id="github",
            source_instance_id="repo-reviews",
            external_id="42",
            url="https://github.com/org/api/pull/42",
            fetched_at=now,
            source_updated_at=now,
        ),
        "body_policy": BodyPolicy.EXCERPT,
        "identity_policy": IdentityPolicy.OMIT,
        "text_trust": TextTrust.UNTRUSTED_EXTERNAL,
        "sensitivity": Sensitivity.STANDARD,
        "omissions": SourceOmissions(),
    }
    fields.update(overrides)
    return SourceArtifact(**fields)  # type: ignore[arg-type]
