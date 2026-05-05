"""Pure, deterministic signal classification and coordination guidance.

No I/O, no network, no file access. Receives signal objects and request
context as explicit inputs; returns CoordinationGuidance.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

_BODY_EXCERPT_LIMIT = 500

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
        )


@dataclass(frozen=True)
class PRSignal:
    signal_id: str
    provider: Literal["github"]
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


@dataclass(frozen=True)
class PRSignalEvidence:
    repo: str
    number: int
    url: str
    title: str
    author: str
    state: str
    updated_at: datetime
    matched_paths: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class CoordinationGuidance:
    effect: Literal["continue", "reuse", "revise", "pause", "handoff", "clarify"]
    urgency: Literal["quiet", "info", "notice", "warning", "critical"]
    summary: str
    instruction: str
    confidence: int
    evidence: tuple[PRSignalEvidence, ...]


def _overlapping_paths(
    signal_paths: tuple[str, ...],
    signal_areas: tuple[str, ...],
    requested_paths: list[str],
) -> tuple[str, ...]:
    requested_set = set(requested_paths)
    matched = set()
    for p in signal_paths:
        if p in requested_set:
            matched.add(p)
    for area in signal_areas:
        for rp in requested_paths:
            if rp.startswith(area + "/") or rp == area:
                matched.add(rp)
    return tuple(sorted(matched))


def _text_blob(signal: PRSignal | CoordinationSignal) -> str:
    parts = [signal.title]
    excerpt = signal.body_excerpt if isinstance(signal, PRSignal) else signal.excerpt
    if excerpt:
        parts.append(excerpt[:_BODY_EXCERPT_LIMIT])
    return " ".join(parts)


def _make_evidence(signal: PRSignal, matched: tuple[str, ...], reason: str) -> PRSignalEvidence:
    return PRSignalEvidence(
        repo=signal.repo,
        number=signal.number,
        url=signal.url,
        title=signal.title,
        author=signal.author,
        state=signal.state,
        updated_at=signal.updated_at,
        matched_paths=matched,
        reason=reason,
    )


def _make_evidence_from_coordination(
    signal: CoordinationSignal, matched: tuple[str, ...], reason: str
) -> PRSignalEvidence:
    number = 0
    if "pull/" in signal.artifact_ref:
        with contextlib.suppress(ValueError, IndexError):
            number = int(signal.artifact_ref.rsplit("pull/", 1)[1].split("/")[0])
    return PRSignalEvidence(
        repo=signal.source,
        number=number,
        url=signal.artifact_ref,
        title=signal.title,
        author=signal.actor,
        state=signal.state,
        updated_at=signal.updated_at,
        matched_paths=matched,
        reason=reason,
    )


def classify_signals(
    signals: list[PRSignal] | list[CoordinationSignal],
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

    for raw_signal in signals:
        if isinstance(raw_signal, PRSignal):
            coord = CoordinationSignal.from_pr_signal(raw_signal)
        else:
            coord = raw_signal

        if coord.updated_at < cutoff:
            continue
        if coord.state == "closed" and coord.resolved_at is None:
            continue

        same_source = repo is not None and coord.source == repo
        overlaps = _overlapping_paths(coord.subject_refs, coord.subject_areas, requested_paths)
        text = _text_blob(coord)

        guidance = _classify_one_coordination(
            coord,
            same_source=same_source,
            overlaps=overlaps,
            text=text,
            revise_re=revise_re,
            handoff_re=handoff_re,
        )
        if guidance is not None:
            results.append(guidance)

    results.sort(key=lambda g: (-_urgency_rank(g.urgency), -g.confidence))
    return results


def _urgency_rank(urgency: str) -> int:
    return {"critical": 4, "warning": 3, "notice": 2, "info": 1, "quiet": 0}.get(urgency, 0)


def _classify_one_coordination(
    signal: CoordinationSignal,
    *,
    same_source: bool,
    overlaps: tuple[str, ...],
    text: str,
    revise_re: re.Pattern[str],
    handoff_re: re.Pattern[str],
) -> CoordinationGuidance | None:
    evidence_reason: str
    effect: Literal["continue", "reuse", "revise", "pause", "handoff", "clarify"]
    mk_ev = _make_evidence_from_coordination

    if overlaps and signal.state == "merged":
        effect = "reuse"
        evidence_reason = "merged jurati-labeled artifact touched requested path"
        return CoordinationGuidance(
            effect=effect,
            urgency="notice",
            summary=f"{signal.actor} merged {signal.source}: {signal.title}",
            instruction="Inspect and reuse that work before building new code on the same target.",
            confidence=min(90, 70 + len(overlaps) * 10),
            evidence=(mk_ev(signal, overlaps, evidence_reason),),
        )

    if overlaps and signal.state == "open":
        effect = "pause"
        evidence_reason = "open jurati-labeled artifact touches requested path"
        return CoordinationGuidance(
            effect=effect,
            urgency="warning",
            summary=f"{signal.actor} has open {signal.source}: {signal.title}",
            instruction="Pause edits to the overlapping target and account for this artifact.",
            confidence=min(95, 75 + len(overlaps) * 10),
            evidence=(mk_ev(signal, overlaps, evidence_reason),),
        )

    if revise_re.search(text):
        effect = "revise"
        evidence_reason = "jurati-labeled artifact contains workflow/decision language"
        return CoordinationGuidance(
            effect=effect,
            urgency="notice",
            summary=f"{signal.source} may change constraints: {signal.title}",
            instruction="Update plan constraints based on this artifact before continuing.",
            confidence=60,
            evidence=(mk_ev(signal, overlaps, evidence_reason),),
        )

    if handoff_re.search(text):
        effect = "handoff"
        evidence_reason = "jurati-labeled artifact contains ownership/review language"
        return CoordinationGuidance(
            effect=effect,
            urgency="notice",
            summary=f"{signal.source} indicates ownership change: {signal.title}",
            instruction="Treat this artifact as the ownership or review handoff point.",
            confidence=55,
            evidence=(mk_ev(signal, overlaps, evidence_reason),),
        )

    if same_source and not overlaps:
        effect = "continue"
        evidence_reason = "jurati-labeled artifact in same source, different area"
        return CoordinationGuidance(
            effect=effect,
            urgency="info",
            summary=f"{signal.source} is parallel work: {signal.title}",
            instruction="Continue normally; keep this signal as background context.",
            confidence=80,
            evidence=(mk_ev(signal, (), evidence_reason),),
        )

    if same_source or overlaps:
        effect = "clarify"
        evidence_reason = "jurati-labeled artifact is relevant but ambiguous"
        return CoordinationGuidance(
            effect=effect,
            urgency="info",
            summary=f"{signal.source} may be relevant: {signal.title}",
            instruction="Ask only if the ambiguity blocks forming a safe plan.",
            confidence=30,
            evidence=(mk_ev(signal, overlaps, evidence_reason),),
        )

    return None
