"""Tests for jurati.git.config."""

from __future__ import annotations

import pytest

from jurati.git.config import JuratiConfig, load_config_from_env


class TestJuratiConfig:
    def test_defaults(self) -> None:
        config = JuratiConfig(remote_url="https://github.com/org/repo.git")
        assert config.remote_url == "https://github.com/org/repo.git"
        assert config.main_branch == "main"
        assert config.branch_prefix == "jurati"
        assert config.active_ref_prefix == "jurati/active"
        assert config.sync_interval == 300
        assert config.client_slug == "claude-code"

    def test_frozen(self) -> None:
        config = JuratiConfig(remote_url="https://example.com/repo.git")
        with pytest.raises(AttributeError):
            config.remote_url = "other"  # type: ignore[misc]


class TestLoadConfigFromEnv:
    def test_minimal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        config = load_config_from_env()
        assert config.remote_url == "https://example.com/repo.git"
        assert config.main_branch == "main"

    def test_all_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "git@github.com:org/repo.git")
        monkeypatch.setenv("JURATI_CACHE_DIR", "/tmp/custom-cache")
        monkeypatch.setenv("JURATI_MAIN_BRANCH", "trunk")
        monkeypatch.setenv("JURATI_BRANCH_PREFIX", "kb")
        monkeypatch.setenv("JURATI_ACTIVE_REF_PREFIX", "kb/live")
        monkeypatch.setenv("JURATI_SYNC_INTERVAL", "60")
        monkeypatch.setenv("JURATI_CLIENT_SLUG", "my-agent")

        config = load_config_from_env()
        assert config.remote_url == "git@github.com:org/repo.git"
        assert config.cache_dir == "/tmp/custom-cache"
        assert config.main_branch == "trunk"
        assert config.branch_prefix == "kb"
        assert config.active_ref_prefix == "kb/live"
        assert config.sync_interval == 60
        assert config.client_slug == "my-agent"

    def test_missing_remote_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JURATI_KNOWLEDGE_REMOTE", raising=False)
        with pytest.raises(ValueError, match="JURATI_KNOWLEDGE_REMOTE"):
            load_config_from_env()

    def test_empty_remote_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "")
        with pytest.raises(ValueError, match="JURATI_KNOWLEDGE_REMOTE"):
            load_config_from_env()


class TestRepoGraph:
    def test_repo_graph_default_empty(self) -> None:
        config = JuratiConfig(remote_url="https://example.com/repo.git")
        assert config.repo_graph == {}

    def test_repo_graph_with_deps(self) -> None:
        config = JuratiConfig(
            remote_url="https://example.com/repo.git",
            repo_graph={"api-service": ["shared-libs", "auth-service"]},
        )
        assert config.repo_graph["api-service"] == ["shared-libs", "auth-service"]


class TestSecretPatterns:
    def test_secret_patterns_default_empty(self) -> None:
        config = JuratiConfig(remote_url="https://example.com/repo.git")
        assert config.secret_patterns == []

    def test_secret_patterns_from_config(self) -> None:
        config = JuratiConfig(
            remote_url="https://example.com/repo.git",
            secret_patterns=["CUSTOM_TOKEN_[A-Z0-9]+", "my-org-secret-\\w+"],
        )
        assert len(config.secret_patterns) == 2
