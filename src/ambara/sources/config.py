# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Source configuration shapes and legacy signal compatibility shims."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ambara.sources.types import (
    BodyPolicy,
    IdentityPolicy,
    SourceBudget,
    SourceCategory,
    SourceInstanceConfig,
)

LEGACY_SIGNAL_SOURCE_BUDGET = SourceBudget()


@dataclass(frozen=True)
class SourceInputsConfig:
    provider: str = "github"
    label: str = "ambara"
    recency_days: int = 30
    repos: tuple[str, ...] = ()
    fixture_path: str | None = None
    include_body_excerpt: bool = True
    include_changed_paths: bool = True
    gitlab_base_url: str | None = None
    jira_base_url: str | None = None
    jira_projects: tuple[str, ...] = ()


PRSignalsConfig = SourceInputsConfig


@dataclass(frozen=True)
class SourcesConfig:
    instances: tuple[SourceInstanceConfig, ...] = ()

    def enabled_instances(self) -> tuple[SourceInstanceConfig, ...]:
        return tuple(instance for instance in self.instances if instance.enabled)


def sources_from_source_inputs_config(config: SourceInputsConfig) -> SourcesConfig:
    """Synthesize source instances from bounded source selector config.

    This shim deliberately copies selectors only. Auth material remains in env
    or a future auth broker and is never persisted in source config.
    """

    instances: list[SourceInstanceConfig] = []

    if config.fixture_path:
        instances.append(
            SourceInstanceConfig(
                id="legacy-fixture-signals",
                provider="fixture",
                category=SourceCategory.FIXTURE,
                selectors=MappingProxyType(
                    {
                        "fixture_path": config.fixture_path,
                        "repos": config.repos,
                        "label": config.label,
                        "include_changed_paths": config.include_changed_paths,
                    }
                ),
                recency_days=config.recency_days,
                body_policy=BodyPolicy.EXCERPT,
                identity_policy=IdentityPolicy.OMIT,
                budget=LEGACY_SIGNAL_SOURCE_BUDGET,
            )
        )

    if config.repos:
        provider = (config.provider or "github").strip().lower()
        selectors: dict[str, object] = {
            "repos": config.repos,
            "label": config.label,
            "include_changed_paths": config.include_changed_paths,
        }
        if config.gitlab_base_url:
            selectors["base_url"] = config.gitlab_base_url
        instances.append(
            SourceInstanceConfig(
                id=f"legacy-{provider}-review-signals",
                provider=provider,
                category=SourceCategory.FORGE_REVIEW,
                selectors=selectors,
                recency_days=config.recency_days,
                body_policy=(
                    BodyPolicy.EXCERPT if config.include_body_excerpt else BodyPolicy.METADATA_ONLY
                ),
                identity_policy=IdentityPolicy.OMIT,
                budget=LEGACY_SIGNAL_SOURCE_BUDGET,
            )
        )

    if config.jira_base_url and config.jira_projects:
        instances.append(
            SourceInstanceConfig(
                id="legacy-jira-issue-signals",
                provider="jira",
                category=SourceCategory.WORK_TRACKER,
                selectors={
                    "base_url": config.jira_base_url,
                    "projects": config.jira_projects,
                    "label": config.label,
                    "include_changed_paths": config.include_changed_paths,
                },
                recency_days=config.recency_days,
                body_policy=(
                    BodyPolicy.EXCERPT if config.include_body_excerpt else BodyPolicy.METADATA_ONLY
                ),
                identity_policy=IdentityPolicy.OMIT,
                budget=LEGACY_SIGNAL_SOURCE_BUDGET,
            )
        )

    return SourcesConfig(instances=tuple(instances))


def sources_from_legacy_pr_signals(config: SourceInputsConfig) -> SourcesConfig:
    return sources_from_source_inputs_config(config)


# Source-selector env vars that were removed in favor of the AMBARA_SOURCE_*
# names. Setting one without its replacement is a clear error rather than a
# silent fall-back to the default selector.
_REMOVED_SOURCE_ENV = {
    "AMBARA_SIGNAL_PROVIDER": "AMBARA_SOURCE_PROVIDER",
    "AMBARA_PR_SIGNAL_REPOS": "AMBARA_SOURCE_REPOS",
    "AMBARA_PR_SIGNAL_FIXTURE": "AMBARA_SOURCE_FIXTURE",
}


def source_inputs_config_from_env(
    env: Mapping[str, str] | None = None,
) -> SourceInputsConfig:
    """Read source selectors without requiring a knowledge remote.

    ``ambara sources doctor`` needs to inspect source setup even when the
    project has not loaded the full runtime config. This intentionally reads
    selectors only; auth material stays in the environment or future managed
    auth broker.
    """

    environ = os.environ if env is None else env
    _reject_removed_source_env(environ)
    return SourceInputsConfig(
        provider=environ.get("AMBARA_SOURCE_PROVIDER") or "github",
        repos=_csv(environ.get("AMBARA_SOURCE_REPOS", "")),
        fixture_path=environ.get("AMBARA_SOURCE_FIXTURE") or None,
        gitlab_base_url=environ.get("AMBARA_GITLAB_BASE_URL") or None,
        jira_base_url=environ.get("AMBARA_JIRA_BASE_URL") or None,
        jira_projects=_csv(environ.get("AMBARA_JIRA_PROJECTS", "")),
    )


def _reject_removed_source_env(environ: Mapping[str, str]) -> None:
    for removed, replacement in _REMOVED_SOURCE_ENV.items():
        if environ.get(removed) and not environ.get(replacement):
            raise ValueError(f"{removed} was removed; set {replacement} instead.")


def legacy_pr_signals_config_from_env(
    env: Mapping[str, str] | None = None,
) -> SourceInputsConfig:
    return source_inputs_config_from_env(env)


def _csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())
