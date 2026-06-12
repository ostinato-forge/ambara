# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Fixture-backed preview source providers for public-preview sources."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from ambara.providers.errors import SignalProviderError
from ambara.sources.types import (
    AuthMode,
    BodyPolicy,
    Sensitivity,
    SourceArtifact,
    SourceCapabilities,
    SourceCategory,
    SourceFetchRequest,
    SourceFetchResult,
    SourceOmissions,
    SourceProvenance,
    SourceSubjectRefsStatus,
    TextTrust,
)

_BODY_EXCERPT_LIMIT = 500
_PATH_STATUSES = {"available", "unavailable", "disabled"}


@dataclass(frozen=True)
class PreviewFixtureSourceProvider:
    provider_id: str
    display_name: str
    category: SourceCategory
    artifact_type: str
    collection_key: str
    selector_names: frozenset[str]
    default_state: str

    @property
    def categories(self) -> frozenset[SourceCategory]:
        return frozenset({self.category})

    @property
    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            categories=self.categories,
            auth_modes=frozenset({AuthMode.NONE}),
            selectors=self.selector_names,
            body_policies=frozenset({BodyPolicy.METADATA_ONLY, BodyPolicy.EXCERPT}),
            supports_fixture=True,
        )

    def fetch(self, request: SourceFetchRequest) -> SourceFetchResult:
        fixture_path = _optional_str(request.config.selectors.get("fixture_path"))
        if fixture_path is None:
            raise SignalProviderError(
                f"{self.display_name} preview source requires a fixture_path selector"
            )

        payload = _read_fixture(fixture_path)
        raw_items = _fixture_items(payload, collection_key=self.collection_key)
        cutoff = request.now - timedelta(days=request.config.recency_days)
        label = _optional_str(request.config.selectors.get("label"))
        artifacts = tuple(
            artifact
            for raw in raw_items
            if isinstance(raw, Mapping)
            for artifact in (self._artifact_from_raw(raw, request, label=label, cutoff=cutoff),)
            if artifact is not None
        )
        return SourceFetchResult(
            artifacts=artifacts,
            ttl_seconds=_ttl_seconds(request.config.selectors.get("ttl_seconds")),
        )

    def _artifact_from_raw(
        self,
        raw: Mapping[str, object],
        request: SourceFetchRequest,
        *,
        label: str | None,
        cutoff: datetime,
    ) -> SourceArtifact | None:
        labels = _string_tuple(raw.get("labels"))
        if label and label not in labels:
            return None

        updated_at = (
            _parse_datetime(raw.get("updated_at"))
            or _parse_datetime(raw.get("source_updated_at"))
            or request.now
        )
        if updated_at < cutoff:
            return None

        if not _matches_scope(raw, request.config.selectors):
            return None

        external_id = _external_id(raw)
        if external_id is None:
            return None
        source = _source_name(raw, request.config.selectors, fallback=request.config.id)
        artifact_ref = _artifact_ref(raw)
        excerpt = _excerpt(raw, request.config.body_policy)
        subject_refs = _string_tuple(raw.get("subject_refs")) or _string_tuple(
            raw.get("changed_paths")
        )
        subject_areas = _string_tuple(raw.get("subject_areas"))

        return SourceArtifact(
            artifact_id=str(raw.get("artifact_id") or f"{self.provider_id}:{source}:{external_id}"),
            provider_id=self.provider_id,
            source_instance_id=request.config.id,
            category=request.config.category,
            artifact_type=str(raw.get("artifact_type") or self.artifact_type),
            artifact_ref=artifact_ref,
            title=str(raw.get("title") or raw.get("name") or external_id),
            excerpt=excerpt,
            state=str(raw.get("state") or raw.get("status") or self.default_state),
            labels=labels,
            subject_refs=subject_refs,
            subject_areas=subject_areas,
            created_at=_parse_datetime(raw.get("created_at")),
            updated_at=updated_at,
            resolved_at=_parse_datetime(raw.get("resolved_at"))
            or _parse_datetime(raw.get("completed_at")),
            provenance=SourceProvenance(
                provider_id=self.provider_id,
                source_instance_id=request.config.id,
                external_id=external_id,
                url=artifact_ref,
                fetched_at=request.now,
                source_updated_at=updated_at,
            ),
            body_policy=request.config.body_policy,
            identity_policy=request.config.identity_policy,
            text_trust=TextTrust.UNTRUSTED_EXTERNAL,
            sensitivity=_sensitivity(raw.get("sensitivity")),
            omissions=SourceOmissions(),
            subject_refs_status=_subject_refs_status(raw.get("subject_refs_status"), subject_refs),
        )


def built_in_preview_source_providers() -> tuple[PreviewFixtureSourceProvider, ...]:
    return (
        PreviewFixtureSourceProvider(
            provider_id="linear",
            display_name="Linear",
            category=SourceCategory.WORK_TRACKER,
            artifact_type="issue",
            collection_key="issues",
            selector_names=frozenset({"fixture_path", "teams", "projects", "label", "ttl_seconds"}),
            default_state="open",
        ),
        PreviewFixtureSourceProvider(
            provider_id="confluence",
            display_name="Confluence",
            category=SourceCategory.DOCS,
            artifact_type="page",
            collection_key="pages",
            selector_names=frozenset({"fixture_path", "spaces", "label", "ttl_seconds"}),
            default_state="current",
        ),
    )


def _read_fixture(fixture_path: str) -> object:
    try:
        return json.loads(Path(fixture_path).expanduser().read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SignalProviderError("Source fixture unavailable") from exc


def _fixture_items(payload: object, *, collection_key: str) -> tuple[object, ...]:
    if isinstance(payload, list):
        return tuple(payload)
    if isinstance(payload, Mapping):
        raw = payload.get(collection_key, payload.get("artifacts", []))
        if isinstance(raw, list):
            return tuple(raw)
    raise SignalProviderError(f"Source fixture must be a list or contain {collection_key}[]")


def _matches_scope(raw: Mapping[str, object], selectors: Mapping[str, object]) -> bool:
    projects = _string_tuple(selectors.get("projects"))
    if projects and _optional_str(raw.get("project")) not in projects:
        return False

    teams = _string_tuple(selectors.get("teams"))
    if teams and _optional_str(raw.get("team")) not in teams:
        return False

    spaces = _string_tuple(selectors.get("spaces"))
    return not (spaces and _optional_str(raw.get("space")) not in spaces)


def _external_id(raw: Mapping[str, object]) -> str | None:
    for key in ("external_id", "id", "key"):
        value = _optional_str(raw.get(key))
        if value is not None:
            return value
    return None


def _source_name(
    raw: Mapping[str, object],
    selectors: Mapping[str, object],
    *,
    fallback: str,
) -> str:
    for key in ("source", "team", "space", "project"):
        value = _optional_str(raw.get(key))
        if value is not None:
            return value
    for key in ("teams", "spaces", "projects"):
        values = _string_tuple(selectors.get(key))
        if values:
            return values[0]
    return fallback


def _artifact_ref(raw: Mapping[str, object]) -> str:
    return _optional_str(raw.get("artifact_ref")) or _optional_str(raw.get("url")) or ""


def _excerpt(raw: Mapping[str, object], body_policy: BodyPolicy) -> str | None:
    if body_policy is BodyPolicy.METADATA_ONLY:
        return None
    for key in ("excerpt", "description_excerpt", "body_excerpt", "body"):
        value = _optional_str(raw.get(key))
        if value is not None:
            return value[:_BODY_EXCERPT_LIMIT]
    return None


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, Sequence):
        return tuple(str(part).strip() for part in value if str(part).strip())
    return ()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sensitivity(value: object) -> Sensitivity:
    raw = _optional_str(value)
    if raw is None:
        return Sensitivity.STANDARD
    try:
        return Sensitivity(raw)
    except ValueError:
        return Sensitivity.STANDARD


def _subject_refs_status(
    value: object,
    subject_refs: tuple[str, ...],
) -> SourceSubjectRefsStatus:
    raw = str(value or ("available" if subject_refs else "unavailable")).lower()
    if raw in _PATH_STATUSES:
        return cast(SourceSubjectRefsStatus, raw)
    return "unavailable"


def _ttl_seconds(value: object) -> int | None:
    if value is None:
        return None
    try:
        ttl = int(str(value))
    except ValueError:
        return None
    return max(ttl, 0)
