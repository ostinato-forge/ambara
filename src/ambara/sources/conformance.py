# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Source-provider conformance helpers for no-network provider contract tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ambara.sources.manager import SourceManager
from ambara.sources.registry import SourceProviderRegistry, normalize_source_provider_id
from ambara.sources.types import (
    BodyPolicy,
    SourceArtifact,
    SourceInstanceConfig,
    SourceProvider,
    TextTrust,
)

FindingSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class SourceConformanceFinding:
    id: str
    severity: FindingSeverity
    message: str


@dataclass(frozen=True)
class SourceConformanceReport:
    provider_id: str
    findings: tuple[SourceConformanceFinding, ...] = ()
    artifacts: tuple[SourceArtifact, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(finding.severity == "error" for finding in self.findings)


def check_source_provider_contract(provider: SourceProvider) -> SourceConformanceReport:
    """Validate the static source provider contract."""

    findings: list[SourceConformanceFinding] = []
    provider_id = _provider_id(provider, findings)

    if not provider.display_name.strip():
        findings.append(
            SourceConformanceFinding(
                id="display_name.required",
                severity="error",
                message="source provider display_name is required",
            )
        )
    if not provider.categories:
        findings.append(
            SourceConformanceFinding(
                id="categories.required",
                severity="error",
                message="source provider must declare at least one category",
            )
        )
    if provider.categories != provider.capabilities.categories:
        findings.append(
            SourceConformanceFinding(
                id="capabilities.categories_mismatch",
                severity="error",
                message="provider categories must match capability categories",
            )
        )
    if not provider.capabilities.auth_modes:
        findings.append(
            SourceConformanceFinding(
                id="capabilities.auth_modes_required",
                severity="error",
                message="source provider must declare supported auth modes",
            )
        )
    if not provider.capabilities.body_policies:
        findings.append(
            SourceConformanceFinding(
                id="capabilities.body_policies_required",
                severity="error",
                message="source provider must declare supported body policies",
            )
        )
    if (
        BodyPolicy.DEFERRED_BODY in provider.capabilities.body_policies
        and not provider.capabilities.can_fetch_bodies
    ):
        findings.append(
            SourceConformanceFinding(
                id="capabilities.deferred_body_requires_fetch",
                severity="error",
                message="deferred_body policy requires can_fetch_bodies",
            )
        )

    return SourceConformanceReport(provider_id=provider_id, findings=tuple(findings))


def smoke_source_provider_contract(
    provider: SourceProvider,
    config: SourceInstanceConfig,
    *,
    now: datetime,
    auth: object | None = None,
) -> SourceConformanceReport:
    """Fetch a provider through SourceManager and validate sanitized artifacts."""

    static_report = check_source_provider_contract(provider)
    findings = list(static_report.findings)
    if config.category not in provider.categories:
        findings.append(
            SourceConformanceFinding(
                id="config.category_unsupported",
                severity="error",
                message=f"provider does not support source category {config.category.value!r}",
            )
        )

    artifacts: tuple[SourceArtifact, ...] = ()
    if not any(finding.severity == "error" for finding in findings):
        try:
            manager = SourceManager(SourceProviderRegistry([provider]))
            result = manager.fetch(config, now=now, auth=auth)
            artifacts = result.artifacts
        except Exception as exc:
            findings.append(
                SourceConformanceFinding(
                    id="fetch.failed",
                    severity="error",
                    message=str(exc),
                )
            )
        else:
            findings.extend(_artifact_findings(artifacts, config))

    return SourceConformanceReport(
        provider_id=static_report.provider_id,
        findings=tuple(findings),
        artifacts=artifacts,
    )


def _provider_id(
    provider: SourceProvider,
    findings: list[SourceConformanceFinding],
) -> str:
    try:
        return normalize_source_provider_id(provider.provider_id)
    except Exception as exc:
        findings.append(
            SourceConformanceFinding(
                id="provider_id.invalid",
                severity="error",
                message=str(exc),
            )
        )
        return ""


def _artifact_findings(
    artifacts: tuple[SourceArtifact, ...],
    config: SourceInstanceConfig,
) -> tuple[SourceConformanceFinding, ...]:
    findings: list[SourceConformanceFinding] = []
    for artifact in artifacts:
        prefix = f"artifact.{artifact.artifact_id}"
        if artifact.source_instance_id != config.id:
            findings.append(
                SourceConformanceFinding(
                    id=f"{prefix}.source_instance_mismatch",
                    severity="error",
                    message="artifact source_instance_id must match requested source config",
                )
            )
        if artifact.category != config.category:
            findings.append(
                SourceConformanceFinding(
                    id=f"{prefix}.category_mismatch",
                    severity="error",
                    message="artifact category must match requested source config",
                )
            )
        if artifact.body_policy != config.body_policy:
            findings.append(
                SourceConformanceFinding(
                    id=f"{prefix}.body_policy_mismatch",
                    severity="error",
                    message="artifact body_policy must match requested source config",
                )
            )
        if artifact.identity_policy != config.identity_policy:
            findings.append(
                SourceConformanceFinding(
                    id=f"{prefix}.identity_policy_mismatch",
                    severity="error",
                    message="artifact identity_policy must match requested source config",
                )
            )
        if artifact.text_trust is not TextTrust.UNTRUSTED_EXTERNAL:
            findings.append(
                SourceConformanceFinding(
                    id=f"{prefix}.text_trust",
                    severity="error",
                    message="external source artifacts must remain untrusted evidence",
                )
            )
        if config.body_policy is BodyPolicy.METADATA_ONLY and artifact.excerpt is not None:
            findings.append(
                SourceConformanceFinding(
                    id=f"{prefix}.metadata_only_excerpt",
                    severity="error",
                    message="metadata_only sources must not emit excerpts after manager safety",
                )
            )
    return tuple(findings)
