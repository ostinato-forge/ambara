# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Central source safety enforcement."""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from ambara.core.context_rendering import (
    safe_artifact_ref,
    sanitize_source_paths,
    sanitize_untrusted_source_text,
    source_text_contains_markdown_syntax,
)
from ambara.sources.types import (
    BodyPolicy,
    Sensitivity,
    SourceArtifact,
    SourceBudget,
    SourceInstanceConfig,
    SourceOmissions,
    TextTrust,
)

_REDACTION_MARKER = "[redacted:credential]"


def sanitize_source_artifact(
    artifact: SourceArtifact,
    *,
    config: SourceInstanceConfig | None = None,
) -> SourceArtifact:
    """Apply central policy before cache or startup rendering can consume an artifact."""

    budget = config.budget if config is not None else SourceBudget()
    body_policy = config.body_policy if config is not None else artifact.body_policy
    identity_policy = config.identity_policy if config is not None else artifact.identity_policy
    omissions = artifact.omissions

    markdown_safety = source_text_contains_markdown_syntax(artifact.title)
    title = _sanitize_text(artifact.title, field="title", max_chars=160)
    if title is None:
        title = "[omitted source title]"
        omissions = omissions.add(safety=1)

    excerpt: str | None
    if body_policy == BodyPolicy.METADATA_ONLY:
        excerpt = None
        if artifact.excerpt:
            omissions = omissions.add(privacy=1)
    else:
        markdown_safety = markdown_safety or source_text_contains_markdown_syntax(
            artifact.excerpt
        )
        excerpt = _sanitize_text(
            artifact.excerpt,
            field="excerpt",
            max_chars=budget.max_excerpt_chars,
        )

    if markdown_safety:
        omissions = omissions.add(safety=1)

    if _REDACTION_MARKER in title or (excerpt is not None and _REDACTION_MARKER in excerpt):
        omissions = omissions.add(safety=1)

    artifact_ref = safe_artifact_ref(artifact.artifact_ref)
    if artifact_ref is None:
        artifact_ref = ""
        omissions = omissions.add(privacy=1)

    subject_refs = sanitize_source_paths(artifact.subject_refs)
    subject_areas = sanitize_source_paths(artifact.subject_areas)
    subject_refs_status = artifact.subject_refs_status
    if len(subject_refs) != len(artifact.subject_refs):
        omissions = omissions.add(privacy=1)
        if not subject_refs and subject_refs_status == "available":
            subject_refs_status = "unavailable"
    if len(subject_areas) != len(artifact.subject_areas):
        omissions = omissions.add(privacy=1)

    sensitivity = (
        Sensitivity.SENSITIVE if omissions.safety else artifact.sensitivity
    )

    return replace(
        artifact,
        artifact_ref=artifact_ref,
        title=title,
        excerpt=excerpt,
        subject_refs=subject_refs,
        subject_areas=subject_areas,
        subject_refs_status=subject_refs_status,
        body_policy=body_policy,
        identity_policy=identity_policy,
        text_trust=TextTrust.UNTRUSTED_EXTERNAL,
        sensitivity=sensitivity,
        omissions=omissions,
    )


def enforce_source_budget(
    artifacts: tuple[SourceArtifact, ...],
    budget: SourceBudget,
) -> tuple[tuple[SourceArtifact, ...], SourceOmissions]:
    kept = artifacts[: budget.max_artifacts]
    omitted = max(0, len(artifacts) - len(kept))
    return kept, SourceOmissions(budget=omitted)


def _sanitize_text(
    raw: str | None,
    *,
    field: Literal["title", "excerpt"],
    max_chars: int,
) -> str | None:
    return sanitize_untrusted_source_text(raw, field=field, max_chars=max_chars)
