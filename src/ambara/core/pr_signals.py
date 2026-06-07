# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Pure, deterministic source-input classification and coordination guidance.

No I/O, no network, no file access. Receives source inputs and request context
as explicit inputs; returns CoordinationGuidance.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, TypeGuard, cast

if TYPE_CHECKING:
    from ambara.sources.types import SourceArtifact
else:
    SourceArtifact = Any

_BODY_EXCERPT_LIMIT = 500
PathStatus = Literal["available", "unavailable", "disabled"]

_DEFAULT_REVISE_KEYWORDS = (
    "workflow",
    "decision",
    "migration",
    "deprecat",
    "architecture",
    "release",
    "security",
    "ownership",
)

_DEFAULT_HANDOFF_KEYWORDS = (
    "handoff",
    "hand-off",
    "owner",
    "review",
    "blocked",
    "waiting",
    "assigned",
)


def _build_keyword_pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    parts: list[str] = []
    for w in words:
        escaped = re.escape(w)
        parts.append(escaped + r"\w*")
    joined = "|".join(parts)
    return re.compile(rf"\b({joined})\b", re.IGNORECASE)


_REVISE_KEYWORDS = _build_keyword_pattern(_DEFAULT_REVISE_KEYWORDS)
_HANDOFF_KEYWORDS = _build_keyword_pattern(_DEFAULT_HANDOFF_KEYWORDS)


@dataclass(frozen=True)
class CoordinationSignal:
    """Provider-neutral coordination signal shape."""

    signal_id: str
    provider: str
    source: str
    artifact_ref: str
    title: str
    excerpt: str | None
    actor: str
    state: str
    labels: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    subject_refs: tuple[str, ...]
    subject_areas: tuple[str, ...]
    subject_refs_status: PathStatus = "available"

    @classmethod
    def from_pr_signal(cls, pr: PRSignal) -> CoordinationSignal:
        return cls(
            signal_id=pr.signal_id,
            provider=pr.provider,
            source=pr.repo,
            artifact_ref=pr.url,
            title=pr.title,
            excerpt=pr.body_excerpt,
            actor=pr.author,
            state=pr.state,
            labels=pr.labels,
            created_at=pr.created_at,
            updated_at=pr.updated_at,
            resolved_at=pr.merged_at,
            subject_refs=pr.changed_paths,
            subject_areas=pr.target_areas,
            subject_refs_status=pr.changed_paths_status,
        )


@dataclass(frozen=True)
class PRSignal:
    signal_id: str
    provider: Literal["github", "gitlab"]
    repo: str
    number: int
    url: str
    title: str
    body_excerpt: str | None
    author: str
    state: Literal["open", "merged", "closed"]
    labels: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None
    changed_paths: tuple[str, ...]
    target_areas: tuple[str, ...]
    changed_paths_status: PathStatus = "available"


@dataclass(frozen=True)
class PRSignalEvidence:
    repo: str
    number: int
    url: str
    title: str
    state: str
    updated_at: datetime
    matched_paths: tuple[str, ...]
    reason: str
    merged_at: datetime | None = None
    body_excerpt: str | None = None
    changed_paths_status: PathStatus = "available"


@dataclass(frozen=True)
class CoordinationGuidance:
    effect: Literal["continue", "reuse", "revise", "pause", "handoff", "clarify"]
    urgency: Literal["quiet", "info", "notice", "warning", "critical"]
    summary: str
    instruction: str
    confidence: int
    evidence: tuple[PRSignalEvidence, ...]


type SourceInputLike = PRSignal | CoordinationSignal | SourceArtifact
type SignalLike = SourceInputLike


def coordination_signal_from_source_artifact(
    artifact: SourceArtifact,
    *,
    now: datetime,
    actor: str = "unknown",
) -> CoordinationSignal:
    """Normalize a source artifact for pure coordination/curation logic."""

    return CoordinationSignal(
        signal_id=artifact.artifact_id,
        provider=artifact.provider_id,
        source=_source_from_artifact(artifact),
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


def _overlapping_source_refs(
    source_refs: tuple[str, ...],
    source_areas: tuple[str, ...],
    requested_paths: list[str],
) -> tuple[str, ...]:
    requested_set = set(requested_paths)
    matched = set()
    for p in source_refs:
        if p in requested_set:
            matched.add(p)
    for area in source_areas:
        for rp in requested_paths:
            if rp.startswith(area + "/") or rp == area:
                matched.add(rp)
    return tuple(sorted(matched))


def _source_input_text_blob(source_input: PRSignal | CoordinationSignal) -> str:
    parts = [source_input.title]
    excerpt = (
        source_input.body_excerpt if isinstance(source_input, PRSignal) else source_input.excerpt
    )
    if excerpt:
        parts.append(excerpt[:_BODY_EXCERPT_LIMIT])
    return " ".join(parts)


def _make_evidence_from_pr_signal(
    source_input: PRSignal, matched: tuple[str, ...], reason: str
) -> PRSignalEvidence:
    return PRSignalEvidence(
        repo=source_input.repo,
        number=source_input.number,
        url=source_input.url,
        title=source_input.title,
        state=source_input.state,
        updated_at=source_input.updated_at,
        matched_paths=matched,
        reason=reason,
        merged_at=source_input.merged_at,
        body_excerpt=source_input.body_excerpt,
        changed_paths_status=source_input.changed_paths_status,
    )


def _make_evidence_from_coordination(
    source_input: CoordinationSignal, matched: tuple[str, ...], reason: str
) -> PRSignalEvidence:
    number = 0
    if "pull/" in source_input.artifact_ref:
        with contextlib.suppress(ValueError, IndexError):
            number = int(source_input.artifact_ref.rsplit("pull/", 1)[1].split("/")[0])
    elif "merge_requests/" in source_input.artifact_ref:
        with contextlib.suppress(ValueError, IndexError):
            number = int(source_input.artifact_ref.rsplit("merge_requests/", 1)[1].split("/")[0])
    return PRSignalEvidence(
        repo=source_input.source,
        number=number,
        url=source_input.artifact_ref,
        title=source_input.title,
        state=source_input.state,
        updated_at=source_input.updated_at,
        matched_paths=matched,
        reason=reason,
        merged_at=source_input.resolved_at,
        body_excerpt=source_input.excerpt,
        changed_paths_status=source_input.subject_refs_status,
    )


def classify_source_inputs(
    source_inputs: Sequence[SourceInputLike],
    *,
    repo: str | None = None,
    _goal: str | None = None,
    paths: list[str] | None = None,
    now: datetime,
    recency_days: int = 30,
    revise_keywords: tuple[str, ...] | None = None,
    handoff_keywords: tuple[str, ...] | None = None,
) -> list[CoordinationGuidance]:
    cutoff = now - timedelta(days=recency_days)
    results: list[CoordinationGuidance] = []
    requested_paths = paths or []

    revise_re = _build_keyword_pattern(revise_keywords) if revise_keywords else _REVISE_KEYWORDS
    handoff_re = _build_keyword_pattern(handoff_keywords) if handoff_keywords else _HANDOFF_KEYWORDS

    for source_input in source_inputs:
        coord = coordination_signal_from_any(source_input, now=now)

        if coord.updated_at < cutoff:
            continue
        same_source = repo is not None and coord.source == repo
        overlaps = _overlapping_source_refs(
            coord.subject_refs,
            coord.subject_areas,
            requested_paths,
        )
        text = _source_input_text_blob(coord)

        guidance = _classify_one_coordination(
            coord,
            same_source=same_source,
            overlaps=overlaps,
            requested_paths=requested_paths,
            text=text,
            revise_re=revise_re,
            handoff_re=handoff_re,
        )
        if guidance is not None:
            results.append(guidance)

    results.sort(key=lambda g: (-_urgency_rank(g.urgency), -g.confidence))
    return results


def classify_signals(
    signals: Sequence[SignalLike],
    *,
    repo: str | None = None,
    _goal: str | None = None,
    paths: list[str] | None = None,
    now: datetime,
    recency_days: int = 30,
    revise_keywords: tuple[str, ...] | None = None,
    handoff_keywords: tuple[str, ...] | None = None,
) -> list[CoordinationGuidance]:
    return classify_source_inputs(
        signals,
        repo=repo,
        _goal=_goal,
        paths=paths,
        now=now,
        recency_days=recency_days,
        revise_keywords=revise_keywords,
        handoff_keywords=handoff_keywords,
    )


def coordination_signal_from_any(
    source_input: SourceInputLike,
    *,
    now: datetime,
) -> CoordinationSignal:
    if isinstance(source_input, PRSignal):
        return CoordinationSignal.from_pr_signal(source_input)
    if _is_source_artifact(source_input):
        return coordination_signal_from_source_artifact(source_input, now=now)
    return cast(CoordinationSignal, source_input)


def _is_source_artifact(value: object) -> TypeGuard[SourceArtifact]:
    return all(
        hasattr(value, attribute)
        for attribute in (
            "artifact_id",
            "provider_id",
            "source_instance_id",
            "artifact_ref",
            "subject_refs",
            "subject_areas",
            "subject_refs_status",
        )
    )


def _source_from_artifact(artifact: SourceArtifact) -> str:
    if artifact.provider_id in {"github", "gitlab"}:
        parsed = _review_source_from_signal_id(artifact.artifact_id)
        if parsed is not None:
            return parsed
        parsed = _review_source_from_url(artifact.provider_id, artifact.artifact_ref)
        if parsed is not None:
            return parsed
    if artifact.provider_id == "jira":
        parts = artifact.artifact_id.split(":")
        if len(parts) >= 2:
            return parts[1].split("-", 1)[0]
    if artifact.provider_id == "fixture":
        parts = artifact.artifact_id.split(":")
        if len(parts) >= 2:
            return parts[1]
    return artifact.source_instance_id


def _review_source_from_signal_id(signal_id: str) -> str | None:
    parts = signal_id.split(":")
    for marker in ("pull", "merge_request"):
        if marker in parts:
            marker_index = parts.index(marker)
            if marker_index < 2:
                return None
            return ":".join(parts[1:marker_index])
    return None


def _review_source_from_url(provider_id: str, artifact_ref: str) -> str | None:
    if provider_id == "github":
        match = re.search(r"/([^/]+/[^/]+)/pull/\d+$", artifact_ref)
    elif provider_id == "gitlab":
        match = re.search(r"/(.+?)/-/merge_requests/\d+$", artifact_ref)
    else:
        return None
    if match is None:
        return None
    return match.group(1)


def _urgency_rank(urgency: str) -> int:
    return {"critical": 4, "warning": 3, "notice": 2, "info": 1, "quiet": 0}.get(urgency, 0)


def _classify_one_coordination(
    source_input: CoordinationSignal,
    *,
    same_source: bool,
    overlaps: tuple[str, ...],
    requested_paths: list[str],
    text: str,
    revise_re: re.Pattern[str],
    handoff_re: re.Pattern[str],
) -> CoordinationGuidance | None:
    evidence_reason: str
    effect: Literal["continue", "reuse", "revise", "pause", "handoff", "clarify"]
    mk_ev = _make_evidence_from_coordination

    if overlaps and source_input.state == "merged":
        effect = "reuse"
        evidence_reason = "merged ambara-labeled artifact touched requested path"
        return CoordinationGuidance(
            effect=effect,
            urgency="notice",
            summary=f"Merged review on {source_input.source}: {source_input.title}",
            instruction="Inspect and reuse that work before building new code on the same target.",
            confidence=min(90, 70 + len(overlaps) * 10),
            evidence=(mk_ev(source_input, overlaps, evidence_reason),),
        )

    if overlaps and source_input.state == "open":
        effect = "pause"
        evidence_reason = "open ambara-labeled artifact touches requested path"
        return CoordinationGuidance(
            effect=effect,
            urgency="warning",
            summary=f"Open review on {source_input.source}: {source_input.title}",
            instruction="Pause edits to the overlapping target and account for this artifact.",
            confidence=min(95, 75 + len(overlaps) * 10),
            evidence=(mk_ev(source_input, overlaps, evidence_reason),),
        )

    if overlaps and source_input.state == "closed":
        effect = "clarify"
        evidence_reason = "closed ambara-labeled artifact touched requested path without merge"
        return CoordinationGuidance(
            effect=effect,
            urgency="info",
            summary=f"Closed (not merged) review on {source_input.source}: {source_input.title}",
            instruction=(
                "Do not reuse this as landed work; treat it as closed context unless "
                "the current task depends on why it was not merged."
            ),
            confidence=min(70, 50 + len(overlaps) * 10),
            evidence=(mk_ev(source_input, overlaps, evidence_reason),),
        )

    if revise_re.search(text):
        effect = "revise"
        evidence_reason = "ambara-labeled artifact contains workflow/decision language"
        return CoordinationGuidance(
            effect=effect,
            urgency="notice",
            summary=f"{source_input.source} may change constraints: {source_input.title}",
            instruction="Update plan constraints based on this artifact before continuing.",
            confidence=60,
            evidence=(mk_ev(source_input, overlaps, evidence_reason),),
        )

    if handoff_re.search(text):
        effect = "handoff"
        evidence_reason = "ambara-labeled artifact contains ownership/review language"
        return CoordinationGuidance(
            effect=effect,
            urgency="notice",
            summary=f"{source_input.source} indicates ownership change: {source_input.title}",
            instruction="Treat this artifact as the ownership or review handoff point.",
            confidence=55,
            evidence=(mk_ev(source_input, overlaps, evidence_reason),),
        )

    if same_source and requested_paths and source_input.subject_refs_status != "available":
        effect = "clarify"
        evidence_reason = "changed paths unavailable for ambara-labeled artifact"
        return CoordinationGuidance(
            effect=effect,
            urgency="info",
            summary=(
                f"{source_input.source} has {source_input.state} review context with unavailable "
                f"paths: {source_input.title}"
            ),
            instruction=(
                "Do not assume path overlap from this source input alone; use the title, "
                "state, and excerpt as planning context."
            ),
            confidence=35,
            evidence=(mk_ev(source_input, (), evidence_reason),),
        )

    if same_source and not overlaps:
        effect = "continue"
        evidence_reason = "ambara-labeled artifact in same source, different area"
        return CoordinationGuidance(
            effect=effect,
            urgency="info",
            summary=f"{source_input.source} is parallel work: {source_input.title}",
            instruction="Continue normally; keep this source input as background context.",
            confidence=80,
            evidence=(mk_ev(source_input, (), evidence_reason),),
        )

    if same_source or overlaps:
        effect = "clarify"
        evidence_reason = "ambara-labeled artifact is relevant but ambiguous"
        return CoordinationGuidance(
            effect=effect,
            urgency="info",
            summary=f"{source_input.source} may be relevant: {source_input.title}",
            instruction="Ask only if the ambiguity blocks forming a safe plan.",
            confidence=30,
            evidence=(mk_ev(source_input, overlaps, evidence_reason),),
        )

    if source_input.provider not in {"github", "gitlab"}:
        effect = "continue"
        evidence_reason = "ambara-labeled artifact from different source"
        return CoordinationGuidance(
            effect=effect,
            urgency="quiet",
            summary=f"{source_input.source}: {source_input.title}",
            instruction="Background context from a related team source input.",
            confidence=20,
            evidence=(mk_ev(source_input, (), evidence_reason),),
        )

    return None
