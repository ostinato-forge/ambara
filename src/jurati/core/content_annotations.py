"""Content safety annotation models — cached policy verdicts.

Pure module. No I/O. Defines the shapes stored in the annotation cache
so the read path can consume verdicts without re-scanning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from jurati.core.content_policy import PolicyAction, PolicyVerdict


@dataclass(frozen=True)
class AnnotationKey:
    policy_hash: str
    content_hash: str

    def format(self) -> str:
        return f"v1:{self.policy_hash[:12]}:{self.content_hash[:16]}"


@dataclass(frozen=True)
class AnnotationRecord:
    key: str
    content_hash: str
    policy_hash: str
    action: PolicyAction
    rule_ids: tuple[str, ...]
    first_seen_at: datetime
    last_seen_at: datetime
    entry_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "content_hash": self.content_hash,
            "policy_hash": self.policy_hash,
            "action": str(self.action),
            "rule_ids": list(self.rule_ids),
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "entry_ids": list(self.entry_ids),
        }


@dataclass
class AnnotationRun:
    scanned: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    blocked: int = 0
    require_review: int = 0
    warnings: int = 0


def annotation_key(policy_hash: str, content_hash: str) -> AnnotationKey:
    return AnnotationKey(policy_hash=policy_hash, content_hash=content_hash)


def record_from_verdict(
    key: AnnotationKey,
    verdict: PolicyVerdict,
    *,
    now: datetime,
    entry_id: str | None = None,
) -> AnnotationRecord:
    return AnnotationRecord(
        key=key.format(),
        content_hash=key.content_hash,
        policy_hash=key.policy_hash,
        action=verdict.action,
        rule_ids=verdict.rule_ids,
        first_seen_at=now,
        last_seen_at=now,
        entry_ids=(entry_id,) if entry_id else (),
    )
