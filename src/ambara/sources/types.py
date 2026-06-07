# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Source kernel type definitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Protocol

SourceSubjectRefsStatus = Literal["available", "unavailable", "disabled"]


class SourceCategory(StrEnum):
    FORGE_REVIEW = "forge_review"
    WORK_TRACKER = "work_tracker"
    DOCS = "docs"
    CHAT_HANDOFF = "chat_handoff"
    INCIDENT = "incident"
    DESIGN = "design"
    CUSTOMER = "customer"
    FIXTURE = "fixture"


class BodyPolicy(StrEnum):
    METADATA_ONLY = "metadata_only"
    EXCERPT = "excerpt"
    SUMMARY_ONLY = "summary_only"
    DEFERRED_BODY = "deferred_body"


class IdentityPolicy(StrEnum):
    OMIT = "omit"
    SOURCE_SCOPED_PSEUDONYM = "source_scoped_pseudonym"


class TextTrust(StrEnum):
    TRUSTED_INTERNAL = "trusted_internal"
    UNTRUSTED_EXTERNAL = "untrusted_external"
    BLOCKED_EXTERNAL = "blocked_external"
    SUMMARY_GENERATED = "summary_generated"


class Sensitivity(StrEnum):
    STANDARD = "standard"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class AuthMode(StrEnum):
    NONE = "none"
    ENV_TOKEN = "env_token"
    OAUTH = "oauth"
    MANAGED_BROKER = "managed_broker"


@dataclass(frozen=True)
class SourceBudget:
    max_artifacts: int = 5
    max_excerpt_chars: int = 240

    def __post_init__(self) -> None:
        if self.max_artifacts < 1:
            raise ValueError("source budget max_artifacts must be at least 1")
        if self.max_excerpt_chars < 0:
            raise ValueError("source budget max_excerpt_chars cannot be negative")


@dataclass(frozen=True)
class SourceOmissions:
    privacy: int = 0
    safety: int = 0
    budget: int = 0
    freshness: int = 0
    source_error: int = 0

    @property
    def total(self) -> int:
        return self.privacy + self.safety + self.budget + self.freshness + self.source_error

    def add(
        self,
        *,
        privacy: int = 0,
        safety: int = 0,
        budget: int = 0,
        freshness: int = 0,
        source_error: int = 0,
    ) -> SourceOmissions:
        return SourceOmissions(
            privacy=self.privacy + privacy,
            safety=self.safety + safety,
            budget=self.budget + budget,
            freshness=self.freshness + freshness,
            source_error=self.source_error + source_error,
        )

    def __add__(self, other: SourceOmissions) -> SourceOmissions:
        return self.add(
            privacy=other.privacy,
            safety=other.safety,
            budget=other.budget,
            freshness=other.freshness,
            source_error=other.source_error,
        )


@dataclass(frozen=True)
class SourceProvenance:
    provider_id: str
    source_instance_id: str
    external_id: str
    url: str
    fetched_at: datetime | None = None
    source_updated_at: datetime | None = None


@dataclass(frozen=True)
class SourceCapabilities:
    categories: frozenset[SourceCategory]
    auth_modes: frozenset[AuthMode]
    selectors: frozenset[str]
    body_policies: frozenset[BodyPolicy]
    can_fetch_bodies: bool = False
    supports_cursor: bool = False
    supports_etag: bool = False
    supports_fixture: bool = False


@dataclass(frozen=True)
class SourceInstanceConfig:
    id: str
    provider: str
    category: SourceCategory
    selectors: Mapping[str, object]
    recency_days: int = 30
    body_policy: BodyPolicy = BodyPolicy.EXCERPT
    identity_policy: IdentityPolicy = IdentityPolicy.OMIT
    budget: SourceBudget = field(default_factory=SourceBudget)
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("source instance id is required")
        if not self.provider.strip():
            raise ValueError("source provider id is required")
        if self.recency_days < 1:
            raise ValueError("source recency_days must be at least 1")
        object.__setattr__(self, "selectors", MappingProxyType(dict(self.selectors)))


@dataclass(frozen=True)
class SourceArtifact:
    artifact_id: str
    provider_id: str
    source_instance_id: str
    category: SourceCategory
    artifact_type: str
    artifact_ref: str
    title: str
    excerpt: str | None
    state: str
    labels: tuple[str, ...]
    subject_refs: tuple[str, ...]
    subject_areas: tuple[str, ...]
    created_at: datetime | None
    updated_at: datetime | None
    resolved_at: datetime | None
    provenance: SourceProvenance
    body_policy: BodyPolicy
    identity_policy: IdentityPolicy
    text_trust: TextTrust
    sensitivity: Sensitivity
    omissions: SourceOmissions
    subject_refs_status: SourceSubjectRefsStatus = "available"

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("source artifact_id is required")
        if not self.provider_id.strip():
            raise ValueError("source artifact provider_id is required")
        if not self.source_instance_id.strip():
            raise ValueError("source artifact source_instance_id is required")
        object.__setattr__(self, "labels", tuple(self.labels))
        object.__setattr__(self, "subject_refs", tuple(self.subject_refs))
        object.__setattr__(self, "subject_areas", tuple(self.subject_areas))


@dataclass(frozen=True)
class SourceFetchRequest:
    config: SourceInstanceConfig
    now: datetime
    cursor: str | None = None
    etag: str | None = None
    since: datetime | None = None
    auth: object | None = None


@dataclass(frozen=True)
class SourceFetchResult:
    artifacts: tuple[SourceArtifact, ...] = ()
    next_cursor: str | None = None
    etag: str | None = None
    ttl_seconds: int | None = None
    partial_errors: tuple[str, ...] = ()
    rate_limit_hint: str | None = None
    omissions: SourceOmissions = SourceOmissions()

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "partial_errors", tuple(self.partial_errors))


class SourceProvider(Protocol):
    provider_id: str
    display_name: str
    categories: frozenset[SourceCategory]
    capabilities: SourceCapabilities

    def fetch(self, request: SourceFetchRequest) -> SourceFetchResult: ...
