"""Pydantic models for jurati knowledge entries."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class EntryType(StrEnum):
    PRINCIPLE = "principle"
    DECISION = "decision"
    WORKFLOW = "workflow"
    PROJECT = "project"
    ACTIVE = "active"


class EntryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DRAFT = "draft"
    PROPOSED = "proposed"


class EscalationLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


ESCALATION_MAP: dict[EntryType, EscalationLevel] = {
    EntryType.ACTIVE: EscalationLevel.L0,
    EntryType.PROJECT: EscalationLevel.L1,
    EntryType.WORKFLOW: EscalationLevel.L2,
    EntryType.DECISION: EscalationLevel.L2,
    EntryType.PRINCIPLE: EscalationLevel.L3,
}


def requires_pr(entry_type: EntryType) -> bool:
    level = ESCALATION_MAP[entry_type]
    return level in (EscalationLevel.L2, EscalationLevel.L3)


class Frontmatter(BaseModel):
    title: str
    type: EntryType
    status: EntryStatus = EntryStatus.ACTIVE
    author: str
    date: date
    projects: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    schema_version: int = 1
    expires: datetime | None = None


class Entry(BaseModel):
    path: str
    frontmatter: Frontmatter
    body: str
