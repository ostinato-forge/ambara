"""Pure, deterministic PR signal classification and coordination guidance.

No I/O, no network, no file access. Receives PRSignal objects and request
context as explicit inputs; returns CoordinationGuidance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

_BODY_EXCERPT_LIMIT = 500

_REVISE_KEYWORDS = re.compile(
    r"\b(workflow|decision|migration|deprecat\w*|architecture|release|security|ownership)\b",
    re.IGNORECASE,
)

_HANDOFF_KEYWORDS = re.compile(
    r"\b(handoff|hand-off|owner|review|blocked|waiting|assigned)\b",
    re.IGNORECASE,
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


def _text_blob(signal: PRSignal) -> str:
    parts = [signal.title]
    if signal.body_excerpt:
        parts.append(signal.body_excerpt[:_BODY_EXCERPT_LIMIT])
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


def classify_signals(
    signals: list[PRSignal],
    *,
    repo: str | None = None,
    _goal: str | None = None,
    paths: list[str] | None = None,
    now: datetime,
    recency_days: int = 30,
) -> list[CoordinationGuidance]:
    cutoff = now - timedelta(days=recency_days)
    results: list[CoordinationGuidance] = []
    requested_paths = paths or []

    for signal in signals:
        if signal.updated_at < cutoff:
            continue
        if signal.state == "closed" and signal.merged_at is None:
            continue

        same_repo = repo is not None and signal.repo == repo
        overlaps = _overlapping_paths(signal.changed_paths, signal.target_areas, requested_paths)
        text = _text_blob(signal)

        guidance = _classify_one(signal, same_repo=same_repo, overlaps=overlaps, text=text)
        if guidance is not None:
            results.append(guidance)

    results.sort(key=lambda g: (-_urgency_rank(g.urgency), -g.confidence))
    return results


def _urgency_rank(urgency: str) -> int:
    return {"critical": 4, "warning": 3, "notice": 2, "info": 1, "quiet": 0}.get(urgency, 0)


def _classify_one(
    signal: PRSignal,
    *,
    same_repo: bool,
    overlaps: tuple[str, ...],
    text: str,
) -> CoordinationGuidance | None:
    evidence_reason: str
    effect: Literal["continue", "reuse", "revise", "pause", "handoff", "clarify"]

    if overlaps and signal.state == "merged":
        effect = "reuse"
        evidence_reason = "merged jurati-labeled PR touched requested path"
        return CoordinationGuidance(
            effect=effect,
            urgency="notice",
            summary=f"{signal.author} merged {signal.repo}#{signal.number}: {signal.title}",
            instruction="Inspect and reuse that work before building new code on the same target.",
            confidence=min(90, 70 + len(overlaps) * 10),
            evidence=(_make_evidence(signal, overlaps, evidence_reason),),
        )

    if overlaps and signal.state == "open":
        effect = "pause"
        evidence_reason = "open jurati-labeled PR touches requested path"
        return CoordinationGuidance(
            effect=effect,
            urgency="warning",
            summary=f"{signal.author} has open {signal.repo}#{signal.number}: {signal.title}",
            instruction="Pause edits to the overlapping target and account for this PR.",
            confidence=min(95, 75 + len(overlaps) * 10),
            evidence=(_make_evidence(signal, overlaps, evidence_reason),),
        )

    if _REVISE_KEYWORDS.search(text):
        effect = "revise"
        evidence_reason = "jurati-labeled PR contains workflow/decision language"
        return CoordinationGuidance(
            effect=effect,
            urgency="notice",
            summary=f"{signal.repo}#{signal.number} may change constraints: {signal.title}",
            instruction="Update plan constraints based on this PR before continuing.",
            confidence=60,
            evidence=(_make_evidence(signal, overlaps, evidence_reason),),
        )

    if _HANDOFF_KEYWORDS.search(text):
        effect = "handoff"
        evidence_reason = "jurati-labeled PR contains ownership/review language"
        return CoordinationGuidance(
            effect=effect,
            urgency="notice",
            summary=f"{signal.repo}#{signal.number} indicates ownership change: {signal.title}",
            instruction="Treat this PR as the ownership or review handoff point.",
            confidence=55,
            evidence=(_make_evidence(signal, overlaps, evidence_reason),),
        )

    if same_repo and not overlaps:
        effect = "continue"
        evidence_reason = "jurati-labeled PR in same repo, different area"
        return CoordinationGuidance(
            effect=effect,
            urgency="info",
            summary=f"{signal.repo}#{signal.number} is parallel work: {signal.title}",
            instruction="Continue normally; keep this signal as background context.",
            confidence=80,
            evidence=(_make_evidence(signal, (), evidence_reason),),
        )

    if same_repo or overlaps:
        effect = "clarify"
        evidence_reason = "jurati-labeled PR is relevant but ambiguous"
        return CoordinationGuidance(
            effect=effect,
            urgency="info",
            summary=f"{signal.repo}#{signal.number} may be relevant: {signal.title}",
            instruction="Ask only if the ambiguity blocks forming a safe plan.",
            confidence=30,
            evidence=(_make_evidence(signal, overlaps, evidence_reason),),
        )

    return None
