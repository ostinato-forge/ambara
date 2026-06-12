# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ambara.sources.conformance import (
    check_source_provider_contract,
    smoke_source_provider_contract,
)
from ambara.sources.legacy_providers import (
    built_in_legacy_source_providers,
    built_in_source_providers,
)
from ambara.sources.preview_providers import built_in_preview_source_providers
from ambara.sources.testing import make_source_artifact
from ambara.sources.types import (
    AuthMode,
    BodyPolicy,
    SourceCapabilities,
    SourceCategory,
    SourceFetchRequest,
    SourceFetchResult,
    SourceInstanceConfig,
)

NOW = datetime(2026, 6, 5, tzinfo=UTC)


def test_builtin_legacy_source_providers_pass_static_conformance() -> None:
    providers = built_in_legacy_source_providers()
    reports = [check_source_provider_contract(provider) for provider in providers]

    assert [report.provider_id for report in reports] == ["github", "gitlab", "jira", "fixture"]
    assert all(report.ok for report in reports)
    fixture = next(provider for provider in providers if provider.provider_id == "fixture")
    assert "ttl_seconds" in fixture.capabilities.selectors


def test_builtin_source_providers_include_preview_scope() -> None:
    providers = built_in_source_providers()
    reports = [check_source_provider_contract(provider) for provider in providers]

    assert {report.provider_id for report in reports} == {
        "confluence",
        "fixture",
        "github",
        "gitlab",
        "jira",
        "linear",
    }
    assert all(report.ok for report in reports)


def test_preview_source_providers_pass_no_network_smoke(tmp_path: Path) -> None:
    linear_fixture = tmp_path / "linear.json"
    linear_fixture.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "id": "LIN-12",
                        "url": "https://linear.app/acme/issue/LIN-12/auth",
                        "title": "Auth release handoff",
                        "description_excerpt": "Coordinate auth release work.",
                        "state": "completed",
                        "labels": ["ambara"],
                        "project": "Auth Platform",
                        "updated_at": NOW.isoformat(),
                        "subject_refs": ["src/auth/tokens.py"],
                    }
                ]
            }
        )
    )
    confluence_fixture = tmp_path / "confluence.json"
    confluence_fixture.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "id": "98765",
                        "url": "https://wiki.example.com/spaces/ENG/pages/98765/Auth",
                        "title": "Auth token runbook",
                        "excerpt": "Current token rotation steps.",
                        "labels": ["ambara"],
                        "space": "ENG",
                        "updated_at": NOW.isoformat(),
                        "subject_areas": ["auth"],
                    }
                ]
            }
        )
    )
    providers = {provider.provider_id: provider for provider in built_in_preview_source_providers()}

    linear_report = smoke_source_provider_contract(
        providers["linear"],
        SourceInstanceConfig(
            id="linear-smoke",
            provider="linear",
            category=SourceCategory.WORK_TRACKER,
            selectors={
                "fixture_path": str(linear_fixture),
                "projects": ("Auth Platform",),
                "label": "ambara",
            },
            recency_days=90,
        ),
        now=NOW,
    )
    confluence_report = smoke_source_provider_contract(
        providers["confluence"],
        SourceInstanceConfig(
            id="confluence-smoke",
            provider="confluence",
            category=SourceCategory.DOCS,
            selectors={
                "fixture_path": str(confluence_fixture),
                "spaces": ("ENG",),
                "label": "ambara",
            },
            recency_days=90,
        ),
        now=NOW,
    )

    assert linear_report.ok
    assert confluence_report.ok
    assert linear_report.artifacts[0].provider_id == "linear"
    assert confluence_report.artifacts[0].provider_id == "confluence"


def test_fixture_source_provider_passes_no_network_smoke(tmp_path: Path) -> None:
    fixture = tmp_path / "signals.json"
    fixture.write_text(
        json.dumps(
            {
                "signals": [
                    {
                        "repo": "org/api",
                        "number": 42,
                        "url": "https://github.com/org/api/pull/42",
                        "title": "Coordinate auth rollout",
                        "body_excerpt": "Review the handoff before continuing.",
                        "author": "alice@example.com",
                        "state": "open",
                        "labels": ["ambara"],
                        "created_at": NOW.isoformat(),
                        "updated_at": NOW.isoformat(),
                        "changed_paths": ["src/auth/token.py"],
                    }
                ]
            }
        )
        + "\n"
    )
    provider = next(
        provider
        for provider in built_in_legacy_source_providers()
        if provider.provider_id == "fixture"
    )
    config = SourceInstanceConfig(
        id="fixture-smoke",
        provider="fixture",
        category=SourceCategory.FIXTURE,
        selectors={"fixture_path": str(fixture), "repos": ("org/api",), "label": "ambara"},
        recency_days=90,
    )

    report = smoke_source_provider_contract(provider, config, now=NOW)

    assert report.ok
    assert len(report.artifacts) == 1
    assert report.artifacts[0].source_instance_id == "fixture-smoke"
    assert report.artifacts[0].text_trust.value == "untrusted_external"


def test_invalid_provider_reports_contract_errors() -> None:
    provider = _Provider(
        provider_id="bad",
        display_name="",
        categories=frozenset({SourceCategory.DOCS}),
        capabilities=SourceCapabilities(
            categories=frozenset({SourceCategory.WORK_TRACKER}),
            auth_modes=frozenset(),
            selectors=frozenset(),
            body_policies=frozenset({BodyPolicy.DEFERRED_BODY}),
            can_fetch_bodies=False,
        ),
    )

    report = check_source_provider_contract(provider)

    assert report.ok is False
    assert {finding.id for finding in report.findings} >= {
        "display_name.required",
        "capabilities.categories_mismatch",
        "capabilities.auth_modes_required",
        "capabilities.deferred_body_requires_fetch",
    }


def test_smoke_detects_provider_artifact_contract_mismatch() -> None:
    provider = _Provider(
        provider_id="fake",
        categories=frozenset({SourceCategory.FORGE_REVIEW}),
        capabilities=SourceCapabilities(
            categories=frozenset({SourceCategory.FORGE_REVIEW}),
            auth_modes=frozenset({AuthMode.NONE}),
            selectors=frozenset({"repos"}),
            body_policies=frozenset({BodyPolicy.EXCERPT}),
        ),
        result=SourceFetchResult(
            artifacts=(
                make_source_artifact(
                    artifact_id="fake:bad",
                    provider_id="fake",
                    source_instance_id="wrong-source",
                    category=SourceCategory.WORK_TRACKER,
                ),
            )
        ),
    )
    config = SourceInstanceConfig(
        id="expected-source",
        provider="fake",
        category=SourceCategory.FORGE_REVIEW,
        selectors={"repos": ("org/api",)},
    )

    report = smoke_source_provider_contract(provider, config, now=NOW)

    assert report.ok is False
    assert {
        "artifact.fake:bad.source_instance_mismatch",
        "artifact.fake:bad.category_mismatch",
    } <= {finding.id for finding in report.findings}


@dataclass(frozen=True)
class _Provider:
    provider_id: str
    display_name: str = "Fake Provider"
    categories: frozenset[SourceCategory] = frozenset({SourceCategory.FORGE_REVIEW})
    capabilities: SourceCapabilities = SourceCapabilities(
        categories=frozenset({SourceCategory.FORGE_REVIEW}),
        auth_modes=frozenset({AuthMode.NONE}),
        selectors=frozenset({"repos"}),
        body_policies=frozenset({BodyPolicy.EXCERPT}),
    )
    result: SourceFetchResult = SourceFetchResult()

    def fetch(self, request: SourceFetchRequest) -> SourceFetchResult:
        return self.result
