# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti
"""Promote a labeled source artifact into durable Ambara knowledge.

Pure bridge from the source kernel to the remember core: distill an (already
safety-sanitized) SourceArtifact into a compact RememberCandidate, then plan the
durable write through the shared remember core. No I/O — the caller supplies the
index, the policy, and the clock. The artifact's text was already
redacted/budgeted by ``sources.safety`` before it reaches here; this layer adds
source-level promotability guards (no restricted, no blocked text, no empty
content) on top of the content-policy gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ambara.core.content_policy import WritePolicy
from ambara.core.remember import (
    RememberCandidate,
    RememberPlan,
    RememberProvenance,
    plan_remember,
)
from ambara.core.schema import DEFAULT_LEVEL_MAP, Entry, EntryType
from ambara.sources.types import Sensitivity, SourceArtifact, TextTrust

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class PromotionResult:
    action: Literal["create", "reject"]
    reject_reason: str | None
    plan: RememberPlan | None


def promotable_reject_reason(artifact: SourceArtifact) -> str | None:
    """Source-level promotability guard, applied before the content-policy gate."""
    if artifact.sensitivity == Sensitivity.RESTRICTED:
        return "restricted source artifact is not promotable"
    if artifact.text_trust == TextTrust.BLOCKED_EXTERNAL:
        return "blocked source text is not promotable"
    if not artifact.title.strip():
        return "no promotable content (empty title)"
    return None


def promote_candidate_from_artifact(
    artifact: SourceArtifact, *, entry_type: EntryType, now: datetime
) -> RememberCandidate:
    """Distill an artifact into a compact RememberCandidate (provenance preserved)."""
    provenance = RememberProvenance(
        provider=artifact.provenance.provider_id,
        external_id=artifact.provenance.external_id,
        url=artifact.provenance.url,
        captured_at=now,
    )
    entry_id = _slug(f"{artifact.provenance.provider_id}-{artifact.provenance.external_id}")
    return RememberCandidate(
        kind="promote",
        entry_id=entry_id,
        title=artifact.title,
        body=(artifact.excerpt or "").strip(),
        entry_type=entry_type,
        requested_level=DEFAULT_LEVEL_MAP[entry_type][0],
        branch_prefix="ambara/promote",
        provenance=provenance,
        projects=tuple(artifact.subject_areas),
        tags=tuple(artifact.labels),
    )


def plan_source_promotion(
    artifact: SourceArtifact,
    *,
    entry_type: EntryType,
    index_entries: list[Entry],
    content_policy: WritePolicy,
    now: datetime,
) -> PromotionResult:
    """Plan a promotion: source guard -> distill -> content-policy gate. Pure."""
    reason = promotable_reject_reason(artifact)
    if reason is not None:
        return PromotionResult(action="reject", reject_reason=reason, plan=None)

    candidate = promote_candidate_from_artifact(artifact, entry_type=entry_type, now=now)
    plan = plan_remember(
        candidate, index_entries=index_entries, content_policy=content_policy, now=now
    )
    if plan.action == "reject":
        reject_reason = plan.reject_reasons[0] if plan.reject_reasons else "content policy"
        return PromotionResult(action="reject", reject_reason=reject_reason, plan=plan)
    return PromotionResult(action="create", reject_reason=None, plan=plan)


def _slug(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    if len(slug) < 3:
        slug = f"src-{slug}" if slug else "source"
    return slug[:120]
