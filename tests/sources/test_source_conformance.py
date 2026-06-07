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
from ambara.sources.legacy_providers import built_in_legacy_source_providers
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
