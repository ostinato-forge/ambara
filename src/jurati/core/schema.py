"""Pydantic models for jurati knowledge entries."""

from __future__ import annotations

import re
from datetime import datetime  # noqa: TC003 - Pydantic needs this at runtime.
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,120}$")


class EntryType(StrEnum):
    PRINCIPLE = "principle"
    DECISION = "decision"
    WORKFLOW = "workflow"
    PROJECT = "project"
    ACTIVE = "active"


class EntryStatus(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


class EscalationLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


DEFAULT_LEVEL_MAP: dict[EntryType, list[EscalationLevel]] = {
    EntryType.ACTIVE: [EscalationLevel.L0],
    EntryType.PROJECT: [EscalationLevel.L1],
    EntryType.WORKFLOW: [EscalationLevel.L2],
    EntryType.DECISION: [EscalationLevel.L2, EscalationLevel.L3],
    EntryType.PRINCIPLE: [EscalationLevel.L3],
}


class Sensitivity(StrEnum):
    NORMAL = "normal"
    INTERNAL = "internal"
    RESTRICTED = "restricted"


class ReviewMeta(BaseModel):
    required: bool = False
    pr: str | None = None


class Frontmatter(BaseModel):
    schema_version: int = 1
    id: str
    title: str
    type: EntryType
    level: EscalationLevel
    status: EntryStatus = EntryStatus.DRAFT
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    projects: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: str | None = None
    sensitivity: Sensitivity = Sensitivity.NORMAL
    review: ReviewMeta = Field(default_factory=ReviewMeta)

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not ID_PATTERN.match(v):
            raise ValueError(f"id must match {ID_PATTERN.pattern}, got {v!r}")
        return v


class Entry(BaseModel):
    path: str
    frontmatter: Frontmatter
    body: str


def requires_pr(level: EscalationLevel) -> bool:
    return level in (EscalationLevel.L2, EscalationLevel.L3)


def is_level_allowed(entry_type: EntryType, level: EscalationLevel) -> bool:
    return level in DEFAULT_LEVEL_MAP.get(entry_type, [])
