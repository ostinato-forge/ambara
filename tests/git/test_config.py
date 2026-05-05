"""Tests for jurati.git.config."""

from __future__ import annotations

import pytest

from jurati.git.config import JuratiConfig, PRSignalsConfig, load_config_from_env


class TestJuratiConfig:
    def test_defaults(self) -> None:
        config = JuratiConfig(remote_url="https://github.com/org/repo.git")
        assert config.remote_url == "https://github.com/org/repo.git"
        assert config.main_branch == "main"
        assert config.branch_prefix == "jurati"
        assert config.active_ref_prefix == "jurati/active"
        assert config.sync_interval == 300
        assert config.client_slug == "claude-code"
        assert config.active_refs_enabled is False

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


class TestPRSignalsConfig:
    def test_defaults(self) -> None:
        cfg = PRSignalsConfig()
        assert cfg.provider == "github"
        assert cfg.label == "jurati"
        assert cfg.recency_days == 30
        assert cfg.repos == ()
        assert cfg.include_body_excerpt is True
        assert cfg.include_changed_paths is True

    def test_custom_values(self) -> None:
        cfg = PRSignalsConfig(
            label="team-signal",
            recency_days=14,
            repos=("org/api", "org/web"),
        )
        assert cfg.label == "team-signal"
        assert cfg.recency_days == 14
        assert cfg.repos == ("org/api", "org/web")

    def test_frozen(self) -> None:
        cfg = PRSignalsConfig()
        with pytest.raises(AttributeError):
            cfg.label = "other"  # type: ignore[misc]

    def test_jurati_config_default_pr_signals(self) -> None:
        config = JuratiConfig(remote_url="https://example.com/repo.git")
        assert config.pr_signals == PRSignalsConfig()
        assert config.pr_signals.repos == ()

    def test_jurati_config_custom_pr_signals(self) -> None:
        config = JuratiConfig(
            remote_url="https://example.com/repo.git",
            pr_signals=PRSignalsConfig(repos=("org/api",), recency_days=7),
        )
        assert config.pr_signals.repos == ("org/api",)
        assert config.pr_signals.recency_days == 7


class TestPRSignalReposEnv:
    def test_empty_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.delenv("JURATI_PR_SIGNAL_REPOS", raising=False)
        config = load_config_from_env()
        assert config.pr_signals.repos == ()

    def test_multiple_repos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_PR_SIGNAL_REPOS", "org/repo-a,org/repo-b")
        config = load_config_from_env()
        assert config.pr_signals.repos == ("org/repo-a", "org/repo-b")

    def test_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_PR_SIGNAL_REPOS", " org/a , org/b , ")
        config = load_config_from_env()
        assert config.pr_signals.repos == ("org/a", "org/b")


class TestActiveRefsConfig:
    def test_defaults_to_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.delenv("JURATI_ACTIVE_REFS_ENABLED", raising=False)
        config = load_config_from_env()
        assert config.active_refs_enabled is False

    def test_enabled_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_ACTIVE_REFS_ENABLED", "true")
        config = load_config_from_env()
        assert config.active_refs_enabled is True

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_ACTIVE_REFS_ENABLED", "True")
        config = load_config_from_env()
        assert config.active_refs_enabled is True

    def test_non_true_stays_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_ACTIVE_REFS_ENABLED", "yes")
        config = load_config_from_env()
        assert config.active_refs_enabled is False
