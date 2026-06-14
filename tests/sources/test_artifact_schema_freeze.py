# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Guard for the frozen v1 source-artifact schema (ADR 0001).

The source-artifact contract is the input shape for token accounting (#174)
and curation relevance (#175). Any change to these fields or vocabularies must
land together with an ADR superseding docs/decisions/0001, and a deliberate
update here. If this test surprises you, read that ADR before editing it.
"""

from __future__ import annotations

import dataclasses
import typing

from ambara.sources import types as source_types

_ADR = "docs/decisions/0001-source-artifact-schema-freeze.md"


def _fields(cls: type) -> dict[str, str]:
    return {field.name: str(field.type) for field in dataclasses.fields(cls)}


def _assert_frozen(cls: type, expected: dict[str, str]) -> None:
    actual = _fields(cls)
    assert actual == expected, (
        f"{cls.__name__} is frozen as schema v1 by {_ADR}; "
        f"supersede the ADR before changing it. Drift: "
        f"{set(actual.items()) ^ set(expected.items())}"
    )


def test_source_artifact_fields_frozen() -> None:
    _assert_frozen(
        source_types.SourceArtifact,
        {
            "artifact_id": "str",
            "provider_id": "str",
            "source_instance_id": "str",
            "category": "SourceCategory",
            "artifact_type": "str",
            "artifact_ref": "str",
            "title": "str",
            "excerpt": "str | None",
            "state": "str",
            "labels": "tuple[str, ...]",
            "subject_refs": "tuple[str, ...]",
            "subject_areas": "tuple[str, ...]",
            "created_at": "datetime | None",
            "updated_at": "datetime | None",
            "resolved_at": "datetime | None",
            "provenance": "SourceProvenance",
            "body_policy": "BodyPolicy",
            "identity_policy": "IdentityPolicy",
            "text_trust": "TextTrust",
            "sensitivity": "Sensitivity",
            "omissions": "SourceOmissions",
            "subject_refs_status": "SourceSubjectRefsStatus",
        },
    )


def test_source_provenance_fields_frozen() -> None:
    _assert_frozen(
        source_types.SourceProvenance,
        {
            "provider_id": "str",
            "source_instance_id": "str",
            "external_id": "str",
            "url": "str",
            "fetched_at": "datetime | None",
            "source_updated_at": "datetime | None",
        },
    )


def test_source_omissions_fields_frozen() -> None:
    _assert_frozen(
        source_types.SourceOmissions,
        {
            "privacy": "int",
            "safety": "int",
            "budget": "int",
            "freshness": "int",
            "source_error": "int",
        },
    )


def test_source_fetch_request_fields_frozen() -> None:
    _assert_frozen(
        source_types.SourceFetchRequest,
        {
            "config": "SourceInstanceConfig",
            "now": "datetime",
            "cursor": "str | None",
            "etag": "str | None",
            "since": "datetime | None",
            "auth": "object | None",
        },
    )


def test_source_fetch_result_fields_frozen() -> None:
    _assert_frozen(
        source_types.SourceFetchResult,
        {
            "artifacts": "tuple[SourceArtifact, ...]",
            "next_cursor": "str | None",
            "etag": "str | None",
            "ttl_seconds": "int | None",
            "partial_errors": "tuple[str, ...]",
            "rate_limit_hint": "str | None",
            "omissions": "SourceOmissions",
        },
    )


def test_source_instance_config_fields_frozen() -> None:
    _assert_frozen(
        source_types.SourceInstanceConfig,
        {
            "id": "str",
            "provider": "str",
            "category": "SourceCategory",
            "selectors": "Mapping[str, object]",
            "recency_days": "int",
            "body_policy": "BodyPolicy",
            "identity_policy": "IdentityPolicy",
            "budget": "SourceBudget",
            "enabled": "bool",
        },
    )


def test_source_budget_fields_frozen() -> None:
    _assert_frozen(
        source_types.SourceBudget,
        {
            "max_artifacts": "int",
            "max_excerpt_chars": "int",
            "max_title_chars": "int",
        },
    )


def test_source_capabilities_fields_frozen() -> None:
    _assert_frozen(
        source_types.SourceCapabilities,
        {
            "categories": "frozenset[SourceCategory]",
            "auth_modes": "frozenset[AuthMode]",
            "selectors": "frozenset[str]",
            "body_policies": "frozenset[BodyPolicy]",
            "can_fetch_bodies": "bool",
            "supports_cursor": "bool",
            "supports_etag": "bool",
            "supports_fixture": "bool",
        },
    )


def test_vocabulary_enums_frozen() -> None:
    expected = {
        "SourceCategory": {
            "forge_review",
            "work_tracker",
            "docs",
            "chat_handoff",
            "incident",
            "design",
            "customer",
            "fixture",
        },
        "BodyPolicy": {"metadata_only", "excerpt", "summary_only", "deferred_body"},
        "IdentityPolicy": {"omit", "source_scoped_pseudonym"},
        "TextTrust": {
            "trusted_internal",
            "untrusted_external",
            "blocked_external",
            "summary_generated",
        },
        "Sensitivity": {"standard", "sensitive", "restricted"},
        "AuthMode": {"none", "env_token", "oauth", "managed_broker"},
    }
    for name, members in expected.items():
        enum_cls = getattr(source_types, name)
        actual = {member.value for member in enum_cls}
        assert actual == members, (
            f"{name} vocabulary is frozen as schema v1 by {_ADR}; "
            f"supersede the ADR before changing it. Drift: {actual ^ members}"
        )


def test_subject_refs_status_literal_frozen() -> None:
    assert set(typing.get_args(source_types.SourceSubjectRefsStatus)) == {
        "available",
        "unavailable",
        "disabled",
    }, f"SourceSubjectRefsStatus is frozen as schema v1 by {_ADR}"
