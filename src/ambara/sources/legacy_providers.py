# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""SourceProvider wrappers around the v0.7 signal providers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.providers.fixture_signals import fetch_fixture_signals
from ambara.providers.github_prs import fetch_all_signals as fetch_github_signals
from ambara.providers.gitlab_mrs import fetch_all_signals as fetch_gitlab_signals
from ambara.providers.jira_issues import fetch_all_signals as fetch_jira_signals
from ambara.sources.adapters import source_artifact_from_legacy_signal
from ambara.sources.config import PRSignalsConfig, SourcesConfig
from ambara.sources.preview_providers import built_in_preview_source_providers
from ambara.sources.registry import SourceProviderRegistry
from ambara.sources.types import (
    AuthMode,
    BodyPolicy,
    SourceCapabilities,
    SourceCategory,
    SourceFetchRequest,
    SourceFetchResult,
    SourceProvider,
)

LegacySignalFetcher = Callable[
    [PRSignalsConfig, str | None],
    Sequence[PRSignal | CoordinationSignal],
]


@dataclass(frozen=True)
class LegacySignalSourceProvider:
    provider_id: str
    display_name: str
    category: SourceCategory
    _fetcher: LegacySignalFetcher

    @property
    def categories(self) -> frozenset[SourceCategory]:
        return frozenset({self.category})

    @property
    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            categories=self.categories,
            auth_modes=frozenset({AuthMode.ENV_TOKEN}),
            selectors=_selectors_for_category(self.category),
            body_policies=frozenset({BodyPolicy.METADATA_ONLY, BodyPolicy.EXCERPT}),
            supports_fixture=self.provider_id == "fixture",
        )

    def fetch(self, request: SourceFetchRequest) -> SourceFetchResult:
        selectors = dict(request.config.selectors)
        selectors.setdefault("provider", self.provider_id)
        config = pr_signals_config_from_source_instance(selectors)
        config = PRSignalsConfig(
            provider=self.provider_id,
            label=config.label,
            recency_days=request.config.recency_days,
            repos=config.repos,
            fixture_path=config.fixture_path,
            include_body_excerpt=request.config.body_policy is BodyPolicy.EXCERPT,
            include_changed_paths=config.include_changed_paths,
            gitlab_base_url=config.gitlab_base_url,
            jira_base_url=config.jira_base_url,
            jira_projects=config.jira_projects,
        )
        token = request.auth if isinstance(request.auth, str) else None
        signals = self._fetcher(config, token)
        artifacts = tuple(
            source_artifact_from_legacy_signal(
                signal,
                source_instance_id=request.config.id,
                fetched_at=request.now,
                body_policy=request.config.body_policy,
                identity_policy=request.config.identity_policy,
                category=request.config.category,
            )
            for signal in signals
        )
        return SourceFetchResult(
            artifacts=artifacts,
            ttl_seconds=_ttl_seconds(selectors.get("ttl_seconds")),
        )


def built_in_legacy_source_providers() -> tuple[LegacySignalSourceProvider, ...]:
    return (
        LegacySignalSourceProvider(
            provider_id="github",
            display_name="GitHub",
            category=SourceCategory.FORGE_REVIEW,
            _fetcher=lambda config, token: fetch_github_signals(config, token=token),
        ),
        LegacySignalSourceProvider(
            provider_id="gitlab",
            display_name="GitLab",
            category=SourceCategory.FORGE_REVIEW,
            _fetcher=lambda config, token: fetch_gitlab_signals(config, token=token),
        ),
        LegacySignalSourceProvider(
            provider_id="jira",
            display_name="Jira",
            category=SourceCategory.WORK_TRACKER,
            _fetcher=lambda config, token: fetch_jira_signals(config, token=token),
        ),
        LegacySignalSourceProvider(
            provider_id="fixture",
            display_name="Fixture",
            category=SourceCategory.FIXTURE,
            _fetcher=lambda config, token: fetch_fixture_signals(config),
        ),
    )


def built_in_source_providers() -> tuple[SourceProvider, ...]:
    """Return every source provider registered by default."""

    return cast(
        tuple[SourceProvider, ...],
        (*built_in_legacy_source_providers(), *built_in_preview_source_providers()),
    )


def source_registry_for_legacy_sources(sources: SourcesConfig) -> SourceProviderRegistry:
    """Build the runtime source registry from the built-in source providers."""

    return SourceProviderRegistry(built_in_source_providers())


def pr_signals_config_from_source_instance(
    selectors: Mapping[str, object],
) -> PRSignalsConfig:
    provider = str(selectors.get("provider", "github"))
    base_url = _optional_str(selectors.get("base_url"))
    return PRSignalsConfig(
        provider=provider,
        label=str(selectors.get("label", "ambara")),
        repos=_string_tuple(selectors.get("repos")),
        fixture_path=_optional_str(selectors.get("fixture_path")),
        gitlab_base_url=base_url if provider == "gitlab" else None,
        jira_base_url=base_url if provider == "jira" else None,
        jira_projects=_string_tuple(selectors.get("projects")),
        include_changed_paths=_bool_selector(selectors.get("include_changed_paths"), default=True),
    )


def _selectors_for_category(category: SourceCategory) -> frozenset[str]:
    if category is SourceCategory.WORK_TRACKER:
        return frozenset({"base_url", "projects", "label"})
    if category is SourceCategory.FIXTURE:
        return frozenset({"fixture_path", "repos", "label", "ttl_seconds"})
    return frozenset({"repos", "label", "base_url"})


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


def _bool_selector(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _ttl_seconds(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        ttl = int(str(value))
    except ValueError:
        return None
    return ttl if ttl >= 0 else None
