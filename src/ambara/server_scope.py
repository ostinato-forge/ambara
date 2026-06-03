"""Server-side helpers for local scope mute policy."""

from __future__ import annotations

from dataclasses import replace

from ambara.core.scope_policy import ScopeMutePolicy
from ambara.git.config import PRSignalsConfig


def signal_config_for_mute(
    config: PRSignalsConfig, policy: ScopeMutePolicy
) -> PRSignalsConfig:
    if policy.is_empty():
        return config
    if config.provider.lower() in policy.signal_sources:
        return replace(config, repos=(), fixture_path=None, jira_projects=())
    muted_sources = set(policy.repos).union(policy.signal_sources)
    muted_projects = set(policy.projects).union(policy.signal_sources)
    return replace(
        config,
        repos=tuple(repo for repo in config.repos if repo.lower() not in muted_sources),
        jira_projects=tuple(
            project for project in config.jira_projects if project.lower() not in muted_projects
        ),
    )
