# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Content safety policy engine — deterministic, offline write gate.

Evaluates text against configurable pattern rules and returns a verdict.
No I/O, no network, no file access. Pure functions on explicit inputs.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from ambara.core.schema import EntryType, EscalationLevel, Sensitivity, Visibility

if TYPE_CHECKING:
    from ambara.core.content_policy_config import ContentPolicyConfig


class PolicyAction(StrEnum):
    BLOCK = "block"
    REQUIRE_REVIEW = "require_review"
    ALLOW_WITH_WARNING = "allow_with_warning"
    ALLOW = "allow"


_ACTION_RANK = {
    PolicyAction.BLOCK: 3,
    PolicyAction.REQUIRE_REVIEW: 2,
    PolicyAction.ALLOW_WITH_WARNING: 1,
    PolicyAction.ALLOW: 0,
}


@dataclass(frozen=True)
class CallerScope:
    actor: str | None = None
    actor_kind: Literal["human", "bot", "ci", "unknown"] = "unknown"
    client_slug: str | None = None
    source: Literal[
        "mcp", "github_actions", "gitlab_ci", "gh_cli", "git_config", "unknown"
    ] = "unknown"
    repo: str | None = None
    repo_role: Literal["admin", "maintain", "write", "triage", "read", "none", "unknown"] = (
        "unknown"
    )
    trusted: bool = False
    groups: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicySubject:
    source: Literal["record", "propose", "sync", "signal", "migration", "ci"]
    title: str
    body: str
    entry_id: str | None = None
    path: str | None = None
    entry_type: EntryType | None = None
    level: EscalationLevel | None = None
    projects: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    visibility: Visibility | None = None
    sensitivity: Sensitivity | None = None


@dataclass(frozen=True)
class PolicyMatch:
    rule_id: str
    action: PolicyAction
    field: Literal["title", "body"]
    start: int
    end: int
    matched_text_hash: str
    reason: str


@dataclass(frozen=True)
class PolicyVerdict:
    action: PolicyAction
    rule_ids: tuple[str, ...]
    matches: tuple[PolicyMatch, ...]
    review_labels: tuple[str, ...]
    warning: str | None
    message: str


def _hash_match(text: str, start: int, end: int) -> str:
    return hashlib.sha256(text[start:end].encode()).hexdigest()[:16]


def _scan_text(
    text: str,
    field: Literal["title", "body"],
    rules: dict[str, re.Pattern[str]],
    action: PolicyAction,
) -> list[PolicyMatch]:
    matches: list[PolicyMatch] = []
    for rule_id, pattern in rules.items():
        for m in pattern.finditer(text):
            matches.append(
                PolicyMatch(
                    rule_id=rule_id,
                    action=action,
                    field=field,
                    start=m.start(),
                    end=m.end(),
                    matched_text_hash=_hash_match(text, m.start(), m.end()),
                    reason=f"{action} rule {rule_id} matched",
                )
            )
    return matches


class WritePolicy:
    """Evaluates content against policy rules. Pure, stateless after init."""

    def __init__(self, config: ContentPolicyConfig) -> None:
        self._config = config
        self._block_rules = config.compiled_block_rules
        self._review_rules = config.compiled_review_rules
        self._warning_rules = config.compiled_warning_rules
        self._mode = config.mode

    def evaluate(
        self,
        subject: PolicySubject,
        caller: CallerScope,
        *,
        now: datetime | None = None,
    ) -> PolicyVerdict:
        if self._mode == "disabled":
            return PolicyVerdict(
                action=PolicyAction.ALLOW,
                rule_ids=(),
                matches=(),
                review_labels=(),
                warning=None,
                message="Content policy disabled.",
            )

        all_matches: list[PolicyMatch] = []

        for text_field, field_name in [
            (subject.title, "title"),
            (subject.body, "body"),
        ]:
            if not text_field:
                continue
            field_lit: Literal["title", "body"] = field_name  # type: ignore[assignment]
            all_matches.extend(
                _scan_text(text_field, field_lit, self._block_rules, PolicyAction.BLOCK)
            )
            all_matches.extend(
                _scan_text(
                    text_field,
                    field_lit,
                    self._review_rules,
                    PolicyAction.REQUIRE_REVIEW,
                )
            )
            all_matches.extend(
                _scan_text(
                    text_field,
                    field_lit,
                    self._warning_rules,
                    PolicyAction.ALLOW_WITH_WARNING,
                )
            )

        if not all_matches:
            return PolicyVerdict(
                action=PolicyAction.ALLOW,
                rule_ids=(),
                matches=(),
                review_labels=(),
                warning=None,
                message="No policy findings.",
            )

        worst_action = max((m.action for m in all_matches), key=lambda a: _ACTION_RANK[a])
        rule_ids = tuple(sorted({m.rule_id for m in all_matches}))

        review_labels: list[str] = []
        if worst_action == PolicyAction.BLOCK:
            review_labels = self._config.block_labels
        elif worst_action == PolicyAction.REQUIRE_REVIEW:
            review_labels = self._config.review_labels
        elif worst_action == PolicyAction.ALLOW_WITH_WARNING:
            review_labels = self._config.warning_labels

        warning: str | None = None
        if worst_action == PolicyAction.ALLOW_WITH_WARNING:
            warning = f"Content matched warning rules: {', '.join(rule_ids)}"

        if self._mode == "observe":
            return PolicyVerdict(
                action=PolicyAction.ALLOW,
                rule_ids=rule_ids,
                matches=tuple(all_matches),
                review_labels=(),
                warning=f"[observe mode] Would {worst_action}: {', '.join(rule_ids)}",
                message=f"Observation: content would be {worst_action} in enforce mode.",
            )

        message = _verdict_message(worst_action, rule_ids)

        return PolicyVerdict(
            action=worst_action,
            rule_ids=rule_ids,
            matches=tuple(all_matches),
            review_labels=tuple(review_labels),
            warning=warning,
            message=message,
        )


def _verdict_message(action: PolicyAction, rule_ids: tuple[str, ...]) -> str:
    ids = ", ".join(rule_ids)
    if action == PolicyAction.BLOCK:
        return f"Content blocked by policy ({ids}). Remove the sensitive material and retry."
    if action == PolicyAction.REQUIRE_REVIEW:
        return f"Content requires review ({ids}). The entry will be created with a review label."
    if action == PolicyAction.ALLOW_WITH_WARNING:
        return f"Content allowed with warning ({ids})."
    return "No policy findings."


def subject_content_hash(subject: PolicySubject) -> str:
    """Stable hash of the content fields that matter for policy evaluation."""
    canonical = (
        f"title:{subject.title}\n"
        f"body:{subject.body}\n"
        f"type:{subject.entry_type or ''}\n"
        f"level:{subject.level or ''}\n"
        f"visibility:{subject.visibility or ''}\n"
        f"sensitivity:{subject.sensitivity or ''}\n"
        f"projects:{','.join(sorted(subject.projects))}\n"
        f"tags:{','.join(sorted(subject.tags))}"
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
