# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Server-side helpers for local scope mute policy."""

from __future__ import annotations

from dataclasses import replace

from ambara.core.scope_policy import ScopeMutePolicy
from ambara.sources.config import SourceInputsConfig


def source_config_for_mute(
    config: SourceInputsConfig, policy: ScopeMutePolicy
) -> SourceInputsConfig:
    if policy.is_empty():
        return config
    if config.provider.lower() in policy.source_inputs:
        return replace(config, repos=(), fixture_path=None, jira_projects=())
    muted_sources = set(policy.repos).union(policy.source_inputs)
    muted_projects = set(policy.projects).union(policy.source_inputs)
    return replace(
        config,
        repos=tuple(repo for repo in config.repos if repo.lower() not in muted_sources),
        jira_projects=tuple(
            project for project in config.jira_projects if project.lower() not in muted_projects
        ),
    )


def signal_config_for_mute(
    config: SourceInputsConfig, policy: ScopeMutePolicy
) -> SourceInputsConfig:
    return source_config_for_mute(config, policy)
