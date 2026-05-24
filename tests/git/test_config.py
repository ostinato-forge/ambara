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
        assert config.active_ref_ttl_hours == 72

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
        monkeypatch.setenv("JURATI_ACTIVE_REF_TTL_HOURS", "12")
        monkeypatch.setenv("JURATI_SYNC_INTERVAL", "60")
        monkeypatch.setenv("JURATI_CLIENT_SLUG", "my-agent")

        config = load_config_from_env()
        assert config.remote_url == "git@github.com:org/repo.git"
        assert config.cache_dir == "/tmp/custom-cache"
        assert config.main_branch == "trunk"
        assert config.branch_prefix == "kb"
        assert config.active_ref_prefix == "kb/live"
        assert config.active_ref_ttl_hours == 12
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
        assert cfg.fixture_path is None
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
        assert config.pr_signals.fixture_path is None

    def test_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_PR_SIGNAL_REPOS", " org/a , org/b , ")
        config = load_config_from_env()
        assert config.pr_signals.repos == ("org/a", "org/b")

    def test_fixture_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_PR_SIGNAL_FIXTURE", "/tmp/signals.json")
        config = load_config_from_env()
        assert config.pr_signals.fixture_path == "/tmp/signals.json"


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

    def test_invalid_ttl_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_ACTIVE_REF_TTL_HOURS", "0")

        with pytest.raises(ValueError, match="active_ref_ttl_hours"):
            load_config_from_env()

    def test_ttl_must_not_exceed_validation_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_ACTIVE_REF_TTL_HOURS", "168")
        config = load_config_from_env()
        assert config.active_ref_ttl_hours == 168

        monkeypatch.setenv("JURATI_ACTIVE_REF_TTL_HOURS", "169")
        with pytest.raises(ValueError, match="between 1 and 168"):
            load_config_from_env()


class TestKeywordConfig:
    def test_keyword_defaults_none(self) -> None:
        config = JuratiConfig(remote_url="https://example.com/repo.git")
        assert config.revise_keywords is None
        assert config.handoff_keywords is None

    def test_revise_keywords_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_REVISE_KEYWORDS", "curriculum,module,lab")
        config = load_config_from_env()
        assert config.revise_keywords == ("curriculum", "module", "lab")

    def test_handoff_keywords_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_HANDOFF_KEYWORDS", "escalation,compliance")
        config = load_config_from_env()
        assert config.handoff_keywords == ("escalation", "compliance")

    def test_empty_keywords_give_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_REVISE_KEYWORDS", "")
        monkeypatch.setenv("JURATI_HANDOFF_KEYWORDS", "")
        config = load_config_from_env()
        assert config.revise_keywords is None
        assert config.handoff_keywords is None

    def test_keyword_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_REVISE_KEYWORDS", " foo , bar , ")
        config = load_config_from_env()
        assert config.revise_keywords == ("foo", "bar")


class TestJiraConfig:
    def test_jira_defaults(self) -> None:
        config = PRSignalsConfig()
        assert config.jira_base_url is None
        assert config.jira_projects == ()

    def test_signal_provider_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_SIGNAL_PROVIDER", "jira")
        config = load_config_from_env()
        assert config.pr_signals.provider == "jira"

    def test_jira_base_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_JIRA_BASE_URL", "https://jira.example.com")
        config = load_config_from_env()
        assert config.pr_signals.jira_base_url == "https://jira.example.com"

    def test_jira_projects_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("JURATI_JIRA_PROJECTS", "PROJ, WEB, AUTH")
        config = load_config_from_env()
        assert config.pr_signals.jira_projects == ("PROJ", "WEB", "AUTH")

    def test_jira_projects_empty_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        config = load_config_from_env()
        assert config.pr_signals.jira_projects == ()

    def test_provider_defaults_to_github(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        config = load_config_from_env()
        assert config.pr_signals.provider == "github"
