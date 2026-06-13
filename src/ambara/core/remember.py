# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti
"""Pure decision core for remembering a labeled thing as durable knowledge.

One entry point — ``plan_remember`` — orchestrates the durable-write decision
(content-policy gate -> secret/review escalation -> contradiction detection ->
reject/redact reasons -> honest receipt) and delegates entry construction to the
pure ``core.changes.plan_capture``. No I/O: the caller supplies the policy, the
current index, and the clock. Adapters (commit capture, source promote) build a
``RememberCandidate`` and call this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ambara.core.changes import WriteIntent, plan_capture
from ambara.core.content_policy import CallerScope, PolicyAction, PolicySubject, WritePolicy
from ambara.core.curation import detect_contradictions
from ambara.core.schema import Entry, EntryType, EscalationLevel, SourceMeta, requires_pr

RememberKind = Literal["capture", "promote"]

_PROVENANCE_MARKER = "<!-- ambara:provenance:v1 -->"


@dataclass(frozen=True)
class RememberProvenance:
    """Source-input provenance for a promoted memory (the link back to truth)."""

    provider: str
    external_id: str
    url: str
    captured_at: datetime


@dataclass(frozen=True)
class RememberCandidate:
    """A normalized 'thing to remember', produced by an adapter."""

    kind: RememberKind
    entry_id: str
    title: str
    body: str
    entry_type: EntryType
    requested_level: EscalationLevel
    branch_prefix: str
    source_meta: SourceMeta | None = None
    provenance: RememberProvenance | None = None
    projects: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    secrets_present: bool = False


@dataclass(frozen=True)
class RememberPlan:
    """The decision: create (with a WriteIntent) or reject, plus honest receipt."""

    action: Literal["create", "reject"]
    intent: WriteIntent | None
    level: EscalationLevel
    requires_pr: bool
    reject_reasons: tuple[str, ...] = ()
    redaction_rule_ids: tuple[str, ...] = ()
    contradiction_ids: tuple[str, ...] = ()
    receipt: dict[str, object] = field(default_factory=dict)


def _provenance_footer(provenance: RememberProvenance | None) -> str:
    if provenance is None:
        return ""
    day = provenance.captured_at.date().isoformat()
    return (
        f"\n\n{_PROVENANCE_MARKER}\n"
        f"**Source:** [{provenance.provider}/{provenance.external_id}]"
        f"({provenance.url}) · captured {day}\n"
    )


def plan_remember(
    candidate: RememberCandidate,
    *,
    index_entries: list[Entry],
    content_policy: WritePolicy,
    now: datetime,
    caller: CallerScope | None = None,
) -> RememberPlan:
    """Decide how to durably remember a candidate. Pure: no I/O, deterministic."""
    subject = PolicySubject(
        source="ci" if candidate.kind == "capture" else "propose",
        title=candidate.title,
        body=candidate.body,
        entry_id=candidate.entry_id,
        entry_type=candidate.entry_type,
        level=candidate.requested_level,
        projects=candidate.projects,
        tags=candidate.tags,
    )
    verdict = content_policy.evaluate(subject, caller or CallerScope(), now=now)

    level = candidate.requested_level
    if verdict.action == PolicyAction.BLOCK:
        return RememberPlan(
            action="reject",
            intent=None,
            level=level,
            requires_pr=requires_pr(level),
            reject_reasons=(verdict.message,),
            redaction_rule_ids=verdict.rule_ids,
            receipt={"action": "reject", "reasons": [verdict.message]},
        )

    if verdict.action == PolicyAction.REQUIRE_REVIEW and level in (
        EscalationLevel.L0,
        EscalationLevel.L1,
    ):
        level = EscalationLevel.L2
    if candidate.secrets_present and level in (EscalationLevel.L0, EscalationLevel.L1):
        level = EscalationLevel.L2

    conflicts = detect_contradictions(
        candidate.title, index_entries, entry_type=candidate.entry_type
    )
    contradiction_ids = tuple(entry.frontmatter.id for entry in conflicts)

    body = candidate.body + _provenance_footer(candidate.provenance)
    intent = plan_capture(
        candidate.entry_type,
        candidate.title,
        body,
        entry_id=candidate.entry_id,
        level=level,
        now=now,
        source=candidate.source_meta,
        projects=list(candidate.projects),
        tags=list(candidate.tags),
        branch_prefix=candidate.branch_prefix,
    )

    needs_pr = requires_pr(level)
    return RememberPlan(
        action="create",
        intent=intent,
        level=level,
        requires_pr=needs_pr,
        redaction_rule_ids=verdict.rule_ids,
        contradiction_ids=contradiction_ids,
        receipt={
            "action": "create",
            "entry_id": candidate.entry_id,
            "level": str(level),
            "requires_pr": needs_pr,
            "redactions": list(verdict.rule_ids),
            "contradiction_ids": list(contradiction_ids),
        },
    )
