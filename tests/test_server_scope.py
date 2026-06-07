# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for server-side scope filtering helpers."""

from __future__ import annotations

from ambara.core.scope_policy import ScopeMutePolicy
from ambara.git.config import PRSignalsConfig
from ambara.server_scope import signal_config_for_mute, source_config_for_mute


class TestSourceConfigForMute:
    def test_signal_config_for_mute_preserves_compatibility_alias(self) -> None:
        config = PRSignalsConfig(repos=("org/api", "org/web"))
        policy = ScopeMutePolicy(repos=("org/api",))

        assert signal_config_for_mute(config, policy) == source_config_for_mute(config, policy)

    def test_provider_mute_removes_all_signal_sources(self) -> None:
        config = PRSignalsConfig(
            provider="github",
            repos=("org/api",),
            jira_base_url="https://jira.example",
            jira_projects=("OPS",),
        )
        policy = ScopeMutePolicy(signal_sources=("github",))

        muted = source_config_for_mute(config, policy)

        assert muted.repos == ()
        assert muted.fixture_path is None
        assert muted.jira_projects == ()

    def test_repo_and_project_mutes_filter_configured_sources(self) -> None:
        config = PRSignalsConfig(
            repos=("org/api", "org/web"),
            jira_base_url="https://jira.example",
            jira_projects=("OPS", "AUTH"),
        )
        policy = ScopeMutePolicy(repos=("org/api",), projects=("auth",))

        muted = source_config_for_mute(config, policy)

        assert muted.repos == ("org/web",)
        assert muted.jira_projects == ("OPS",)
