# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Source inspection and smoke commands."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click

from ambara.sources.config import (
    SourcesConfig,
    source_inputs_config_from_env,
    sources_from_source_inputs_config,
)
from ambara.sources.health import SourceHealth, SourceHealthStatus
from ambara.sources.inspect import SourceInspection, SourceInspectionReport, inspect_sources
from ambara.sources.legacy_providers import source_registry_for_legacy_sources
from ambara.sources.registry import normalize_source_provider_id
from ambara.sources.types import (
    BodyPolicy,
    SourceArtifact,
    SourceBudget,
    SourceCategory,
    SourceInstanceConfig,
    SourceOmissions,
    SourceProvider,
)

_PARTIAL_SOURCE_REFRESH_MESSAGE = "partial source refresh failed"
_RATE_LIMITED_SOURCE_REFRESH_MESSAGE = "source refresh rate limited"
_SOURCE_REFRESH_FAILED_MESSAGE = "source refresh failed"


def register_source_commands(main: click.Group) -> None:
    """Register source commands without expanding the main CLI facade."""

    @main.group("sources")
    def sources_cmd() -> None:
        """Inspect configured Ambara sources."""

    @sources_cmd.command("list")
    @click.option("--json", "as_json", is_flag=True, help="Print machine-readable output.")
    def sources_list_cmd(as_json: bool) -> None:
        """List built-in source providers."""

        sources = SourcesConfig()
        registry = source_registry_for_legacy_sources(sources)
        provider_payloads = [
            _provider_payload(registry.require(provider_id))
            for provider_id in registry.provider_ids()
        ]
        if as_json:
            click.echo(json.dumps({"providers": provider_payloads}, indent=2, sort_keys=True))
            return

        click.echo("Ambara source providers")
        for provider in provider_payloads:
            click.echo(
                f"  - {provider['id']}: {provider['display_name']} "
                f"({', '.join(provider['categories'])})"
            )

    @sources_cmd.command("doctor")
    @click.option("--json", "as_json", is_flag=True, help="Print machine-readable output.")
    @click.option("--strict", is_flag=True, help="Exit non-zero unless all sources are fresh.")
    @_source_options
    def sources_doctor_cmd(
        as_json: bool,
        strict: bool,
        provider: str | None,
        fixture_path: str | None,
        repos: tuple[str, ...],
        projects: tuple[str, ...],
        base_url: str | None,
        label: str,
        recency_days: int,
        body_policy: str,
        max_artifacts: int,
        max_excerpt_chars: int,
        ttl_seconds: int | None,
    ) -> None:
        """Check configured source health without leaking source contents."""

        sources = _sources_from_options_or_env(
            provider=provider,
            fixture_path=fixture_path,
            repos=repos,
            projects=projects,
            base_url=base_url,
            label=label,
            recency_days=recency_days,
            body_policy=body_policy,
            max_artifacts=max_artifacts,
            max_excerpt_chars=max_excerpt_chars,
            ttl_seconds=ttl_seconds,
        )
        report = _run_source_report(sources)
        _print_report(report, as_json=as_json, include_artifacts=False, title="source doctor")
        if strict and report.status != "ok":
            sys.exit(1)

    @main.command("source-smoke")
    @click.option("--json", "as_json", is_flag=True, help="Print machine-readable output.")
    @_source_options
    def source_smoke_cmd(
        as_json: bool,
        provider: str | None,
        fixture_path: str | None,
        repos: tuple[str, ...],
        projects: tuple[str, ...],
        base_url: str | None,
        label: str,
        recency_days: int,
        body_policy: str,
        max_artifacts: int,
        max_excerpt_chars: int,
        ttl_seconds: int | None,
    ) -> None:
        """Smoke one source through registry, manager, and central safety."""

        if provider is None:
            raise click.ClickException("--provider is required for source-smoke")
        sources = SourcesConfig(
            instances=(
                _source_instance_from_options(
                    provider=provider,
                    fixture_path=fixture_path,
                    repos=repos,
                    projects=projects,
                    base_url=base_url,
                    label=label,
                    recency_days=recency_days,
                    body_policy=body_policy,
                    max_artifacts=max_artifacts,
                    max_excerpt_chars=max_excerpt_chars,
                    ttl_seconds=ttl_seconds,
                ),
            )
        )
        report = _run_source_report(sources)
        _print_report(report, as_json=as_json, include_artifacts=True, title="source smoke")
        if report.status != "ok":
            sys.exit(1)


def _source_options(fn: Callable[..., object]) -> Callable[..., object]:
    wrapped: Callable[..., object] = fn
    wrapped = click.option(
        "--provider",
        default=None,
        help="Source provider id. Defaults to configured source env for sources doctor.",
    )(wrapped)
    wrapped = click.option(
        "--fixture",
        "fixture_path",
        default=None,
        type=click.Path(dir_okay=False),
        help="Local fixture JSON path for no-network source smoke.",
    )(wrapped)
    wrapped = click.option("--repo", "repos", multiple=True, help="Allowed repo selector.")(wrapped)
    wrapped = click.option(
        "--project",
        "projects",
        multiple=True,
        help="Allowed work project key.",
    )(wrapped)
    wrapped = click.option("--base-url", default=None, help="Provider base URL for Jira/GitLab.")(
        wrapped
    )
    wrapped = click.option("--label", default="ambara", show_default=True, help="Required label.")(
        wrapped
    )
    wrapped = click.option(
        "--recency-days",
        default=30,
        show_default=True,
        type=int,
        help="Maximum source artifact age.",
    )(wrapped)
    wrapped = click.option(
        "--body-policy",
        default=BodyPolicy.EXCERPT.value,
        show_default=True,
        type=click.Choice([policy.value for policy in BodyPolicy]),
        help="How much source body text may be represented.",
    )(wrapped)
    wrapped = click.option(
        "--max-artifacts",
        default=5,
        show_default=True,
        type=int,
        help="Per-source artifact cap.",
    )(wrapped)
    wrapped = click.option(
        "--max-excerpt-chars",
        default=240,
        show_default=True,
        type=int,
        help="Per-artifact excerpt character cap.",
    )(wrapped)
    wrapped = click.option(
        "--ttl-seconds",
        default=None,
        type=int,
        help="Fixture-only TTL override for no-network stale-source proof.",
    )(wrapped)
    return wrapped


def _sources_from_options_or_env(
    *,
    provider: str | None,
    fixture_path: str | None,
    repos: tuple[str, ...],
    projects: tuple[str, ...],
    base_url: str | None,
    label: str,
    recency_days: int,
    body_policy: str,
    max_artifacts: int,
    max_excerpt_chars: int,
    ttl_seconds: int | None,
) -> SourcesConfig:
    if (
        provider is None
        and fixture_path is None
        and not repos
        and not projects
        and base_url is None
    ):
        return sources_from_source_inputs_config(source_inputs_config_from_env())
    return SourcesConfig(
        instances=(
            _source_instance_from_options(
                provider=provider or "fixture",
                fixture_path=fixture_path,
                repos=repos,
                projects=projects,
                base_url=base_url,
                label=label,
                recency_days=recency_days,
                body_policy=body_policy,
                max_artifacts=max_artifacts,
                max_excerpt_chars=max_excerpt_chars,
                ttl_seconds=ttl_seconds,
            ),
        )
    )


def _source_instance_from_options(
    *,
    provider: str,
    fixture_path: str | None,
    repos: tuple[str, ...],
    projects: tuple[str, ...],
    base_url: str | None,
    label: str,
    recency_days: int,
    body_policy: str,
    max_artifacts: int,
    max_excerpt_chars: int,
    ttl_seconds: int | None,
) -> SourceInstanceConfig:
    provider_id = normalize_source_provider_id(provider)
    selectors: dict[str, object] = {"label": label}
    category = SourceCategory.FORGE_REVIEW

    if provider_id == "fixture":
        if fixture_path is None:
            raise click.ClickException("--fixture is required for fixture source smoke")
        selectors["fixture_path"] = str(Path(fixture_path).expanduser())
        selectors["repos"] = repos
        if ttl_seconds is not None:
            if ttl_seconds < 0:
                raise click.ClickException("--ttl-seconds must be zero or greater")
            selectors["ttl_seconds"] = ttl_seconds
        category = SourceCategory.FIXTURE
    elif ttl_seconds is not None:
        raise click.ClickException("--ttl-seconds is only supported for fixture sources")
    elif provider_id in {"github", "gitlab"}:
        if not repos:
            raise click.ClickException("--repo is required for forge review source smoke")
        selectors["repos"] = repos
        if base_url:
            selectors["base_url"] = base_url
    elif provider_id == "jira":
        if not base_url:
            raise click.ClickException("--base-url is required for Jira source smoke")
        if not projects:
            raise click.ClickException("--project is required for Jira source smoke")
        selectors["base_url"] = base_url
        selectors["projects"] = projects
        category = SourceCategory.WORK_TRACKER
    elif repos:
        selectors["repos"] = repos

    return SourceInstanceConfig(
        id=f"smoke-{provider_id}",
        provider=provider_id,
        category=category,
        selectors=selectors,
        recency_days=recency_days,
        body_policy=BodyPolicy(body_policy),
        budget=SourceBudget(
            max_artifacts=max_artifacts,
            max_excerpt_chars=max_excerpt_chars,
        ),
    )


def _run_source_report(sources: SourcesConfig) -> SourceInspectionReport:
    registry = source_registry_for_legacy_sources(sources)
    return inspect_sources(
        sources,
        registry=registry,
        now=datetime.now(UTC),
        auth=_source_token_from_env(),
    )


def _source_token_from_env() -> str | None:
    for name in (
        "AMBARA_SOURCE_TOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITLAB_TOKEN",
        "JIRA_API_TOKEN",
    ):
        token = os.environ.get(name)
        if token:
            return token
    return None


def _print_report(
    report: SourceInspectionReport,
    *,
    as_json: bool,
    include_artifacts: bool,
    title: str,
) -> None:
    if as_json:
        click.echo(
            json.dumps(
                _report_payload(report, include_artifacts=include_artifacts),
                indent=2,
                sort_keys=True,
            )
        )
        return

    click.echo(f"Ambara {title}")
    click.echo(f"  status:        {report.status}")
    click.echo(f"  providers:     {', '.join(report.provider_ids) or 'none'}")
    click.echo(f"  sources:       {len(report.sources)}")
    click.echo(f"  artifacts:     {report.artifact_count}")
    if not report.sources:
        click.echo("  note:          no admin-managed or legacy source selectors configured")
        return
    click.echo("")
    for inspection in report.sources:
        click.echo(
            f"  - {inspection.config.id} ({inspection.config.provider}): "
            f"{inspection.health.status.value}, artifacts {len(inspection.artifacts)}"
        )
        message = _safe_health_message(inspection.health)
        if message:
            click.echo(f"    message: {message}")
        if inspection.omissions.total:
            click.echo(f"    omissions: {inspection.omissions.total}")


def _report_payload(
    report: SourceInspectionReport,
    *,
    include_artifacts: bool,
) -> dict[str, Any]:
    return {
        "status": report.status,
        "provider_ids": list(report.provider_ids),
        "source_count": len(report.sources),
        "artifact_count": report.artifact_count,
        "omissions": _omissions_payload(report.omissions),
        "sources": [
            _inspection_payload(inspection, include_artifacts=include_artifacts)
            for inspection in report.sources
        ],
    }


def _inspection_payload(
    inspection: SourceInspection,
    *,
    include_artifacts: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": inspection.config.id,
        "provider": inspection.config.provider,
        "provider_display_name": inspection.provider_display_name,
        "category": inspection.config.category.value,
        "enabled": inspection.config.enabled,
        "body_policy": inspection.config.body_policy.value,
        "identity_policy": inspection.config.identity_policy.value,
        "artifact_count": len(inspection.artifacts),
        "health": _health_payload(inspection.health),
        "omissions": _omissions_payload(inspection.omissions),
        "partial_error_count": len(inspection.partial_errors),
        "partial_errors": [_PARTIAL_SOURCE_REFRESH_MESSAGE for _ in inspection.partial_errors],
        "rate_limited": inspection.rate_limited,
    }
    if include_artifacts:
        payload["artifacts"] = [_artifact_payload(artifact) for artifact in inspection.artifacts]
    return payload


def _health_payload(health: SourceHealth) -> dict[str, Any]:
    return {
        "source_instance_id": health.source_instance_id,
        "status": health.status.value
        if isinstance(health.status, SourceHealthStatus)
        else str(health.status),
        "last_success": _iso(health.last_success),
        "last_failure": _iso(health.last_failure),
        "consecutive_failures": health.consecutive_failures,
        "stale_after": _iso(health.stale_after),
        "message": _safe_health_message(health),
    }


def _safe_health_message(health: SourceHealth) -> str | None:
    if health.message is None:
        return None
    if health.message == _PARTIAL_SOURCE_REFRESH_MESSAGE:
        return _PARTIAL_SOURCE_REFRESH_MESSAGE
    if health.message == _RATE_LIMITED_SOURCE_REFRESH_MESSAGE:
        return _RATE_LIMITED_SOURCE_REFRESH_MESSAGE
    return _SOURCE_REFRESH_FAILED_MESSAGE


def _artifact_payload(artifact: SourceArtifact) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "provider_id": artifact.provider_id,
        "source_instance_id": artifact.source_instance_id,
        "category": artifact.category.value,
        "artifact_type": artifact.artifact_type,
        "artifact_ref": artifact.artifact_ref,
        "title": artifact.title,
        "excerpt": artifact.excerpt,
        "state": artifact.state,
        "labels": list(artifact.labels),
        "subject_refs": list(artifact.subject_refs),
        "subject_areas": list(artifact.subject_areas),
        "subject_refs_status": artifact.subject_refs_status,
        "text_trust": artifact.text_trust.value,
        "sensitivity": artifact.sensitivity.value,
        "omissions": _omissions_payload(artifact.omissions),
        "provenance": {
            "provider_id": artifact.provenance.provider_id,
            "source_instance_id": artifact.provenance.source_instance_id,
            "external_id": artifact.provenance.external_id,
            "url": artifact.provenance.url,
            "fetched_at": _iso(artifact.provenance.fetched_at),
            "source_updated_at": _iso(artifact.provenance.source_updated_at),
        },
    }


def _omissions_payload(omissions: SourceOmissions) -> dict[str, int]:
    return {
        "privacy": omissions.privacy,
        "safety": omissions.safety,
        "budget": omissions.budget,
        "freshness": omissions.freshness,
        "source_error": omissions.source_error,
        "total": omissions.total,
    }


def _provider_payload(provider: SourceProvider) -> dict[str, Any]:
    return {
        "id": provider.provider_id,
        "display_name": provider.display_name,
        "categories": sorted(category.value for category in provider.categories),
        "auth_modes": sorted(mode.value for mode in provider.capabilities.auth_modes),
        "selectors": sorted(provider.capabilities.selectors),
        "body_policies": sorted(policy.value for policy in provider.capabilities.body_policies),
        "supports_fixture": provider.capabilities.supports_fixture,
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
