"""Tests for ambara.git.config."""

from __future__ import annotations

import pytest

from ambara.git.config import AmbaraConfig, PRSignalsConfig, load_config_from_env


class TestAmbaraConfig:
    def test_defaults(self) -> None:
        config = AmbaraConfig(remote_url="https://github.com/org/repo.git")
        assert config.remote_url == "https://github.com/org/repo.git"
        assert config.main_branch == "main"
        assert config.branch_prefix == "ambara"
        assert config.active_ref_prefix == "ambara/active"
        assert config.sync_interval == 300
        assert config.client_slug == "claude-code"
        assert config.active_refs_enabled is False
        assert config.active_ref_ttl_hours == 72
        assert config.context_freshness_warning_seconds == 300
        assert config.context_stale_after_seconds == 900
        assert config.context_default_mode == "manifest"
        assert config.context_budget_mode == "balanced"
        assert config.value_ledger_enabled is False
        assert config.value_ledger_path is None
        assert config.value_ledger_retention_days == 90

    def test_value_ledger_path_enables_ledger(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_VALUE_LEDGER_PATH", "/tmp/ambara-value.jsonl")

        config = load_config_from_env()

        assert config.value_ledger_enabled is True
        assert config.value_ledger_path == "/tmp/ambara-value.jsonl"

    def test_frozen(self) -> None:
        config = AmbaraConfig(remote_url="https://example.com/repo.git")
        with pytest.raises(AttributeError):
            config.remote_url = "other"  # type: ignore[misc]


class TestLoadConfigFromEnv:
    def test_minimal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        config = load_config_from_env()
        assert config.remote_url == "https://example.com/repo.git"
        assert config.main_branch == "main"

    def test_all_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "git@github.com:org/repo.git")
        monkeypatch.setenv("AMBARA_CACHE_DIR", "/tmp/custom-cache")
        monkeypatch.setenv("AMBARA_MAIN_BRANCH", "trunk")
        monkeypatch.setenv("AMBARA_BRANCH_PREFIX", "kb")
        monkeypatch.setenv("AMBARA_ACTIVE_REF_PREFIX", "kb/live")
        monkeypatch.setenv("AMBARA_ACTIVE_REF_TTL_HOURS", "12")
        monkeypatch.setenv("AMBARA_SYNC_INTERVAL", "60")
        monkeypatch.setenv("AMBARA_CLIENT_SLUG", "my-agent")
        monkeypatch.setenv("AMBARA_CONTEXT_FRESHNESS_WARNING_SECONDS", "120")
        monkeypatch.setenv("AMBARA_CONTEXT_STALE_AFTER_SECONDS", "480")
        monkeypatch.setenv("AMBARA_CONTEXT_DEFAULT_MODE", "compiler")
        monkeypatch.setenv("AMBARA_CONTEXT_BUDGET_MODE", "quiet")
        monkeypatch.setenv("AMBARA_VALUE_LEDGER_ENABLED", "false")
        monkeypatch.setenv("AMBARA_VALUE_LEDGER_PATH", "/tmp/ambara-value.jsonl")
        monkeypatch.setenv("AMBARA_VALUE_LEDGER_RETENTION_DAYS", "14")

        config = load_config_from_env()
        assert config.remote_url == "git@github.com:org/repo.git"
        assert config.cache_dir == "/tmp/custom-cache"
        assert config.main_branch == "trunk"
        assert config.branch_prefix == "kb"
        assert config.active_ref_prefix == "kb/live"
        assert config.active_ref_ttl_hours == 12
        assert config.sync_interval == 60
        assert config.client_slug == "my-agent"
        assert config.context_freshness_warning_seconds == 120
        assert config.context_stale_after_seconds == 480
        assert config.context_default_mode == "compiler"
        assert config.context_budget_mode == "quiet"
        assert config.value_ledger_enabled is False
        assert config.value_ledger_path == "/tmp/ambara-value.jsonl"
        assert config.value_ledger_retention_days == 14

    def test_invalid_budget_mode_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_CONTEXT_BUDGET_MODE", "expensive")

        with pytest.raises(ValueError, match="AMBARA_CONTEXT_BUDGET_MODE"):
            load_config_from_env()

    def test_invalid_value_ledger_retention_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_VALUE_LEDGER_RETENTION_DAYS", "0")

        with pytest.raises(ValueError, match="value_ledger_retention_days"):
            load_config_from_env()

    def test_missing_remote_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AMBARA_KNOWLEDGE_REMOTE", raising=False)
        with pytest.raises(ValueError, match="AMBARA_KNOWLEDGE_REMOTE"):
            load_config_from_env()

    def test_empty_remote_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "")
        with pytest.raises(ValueError, match="AMBARA_KNOWLEDGE_REMOTE"):
            load_config_from_env()

    def test_project_config_remote_is_env_fallback(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / ".ambara" / "config.yaml"
        config_file.parent.mkdir()
        config_file.write_text(
            "\n".join(
                [
                    "schema_version: 1",
                    "knowledge_remote: git@example.com:team/knowledge.git",
                    "main_branch: trunk",
                    "active_refs_enabled: true",
                    "expiry:",
                    "  active_ttl_hours: 24",
                    "",
                ]
            )
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("AMBARA_KNOWLEDGE_REMOTE", raising=False)
        monkeypatch.delenv("AMBARA_MAIN_BRANCH", raising=False)
        monkeypatch.delenv("AMBARA_ACTIVE_REFS_ENABLED", raising=False)
        monkeypatch.delenv("AMBARA_ACTIVE_REF_TTL_HOURS", raising=False)

        config = load_config_from_env()

        assert config.remote_url == "git@example.com:team/knowledge.git"
        assert config.main_branch == "trunk"
        assert config.active_refs_enabled is True
        assert config.active_ref_ttl_hours == 24

    def test_env_remote_overrides_project_config(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / ".ambara" / "config.yaml"
        config_file.parent.mkdir()
        config_file.write_text(
            "schema_version: 1\nknowledge_remote: git@example.com:team/knowledge.git\n"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/env.git")

        config = load_config_from_env()

        assert config.remote_url == "https://example.com/env.git"

    def test_disabled_env_allows_missing_remote(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AMBARA_KNOWLEDGE_REMOTE", raising=False)
        monkeypatch.setenv("AMBARA_DISABLED", "true")

        config = load_config_from_env()

        assert config.disabled is True
        assert config.remote_url == ""
        assert config.value_ledger_enabled is False

    def test_disabled_env_ignores_unrelated_invalid_runtime_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AMBARA_KNOWLEDGE_REMOTE", raising=False)
        monkeypatch.setenv("AMBARA_DISABLED", "true")
        monkeypatch.setenv("AMBARA_ACTIVE_REF_TTL_HOURS", "not-an-int")
        monkeypatch.setenv("AMBARA_CONTEXT_DEFAULT_MODE", "nonsense")

        config = load_config_from_env()

        assert config.disabled is True
        assert config.remote_url == ""

    def test_project_disabled_allows_missing_remote(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / ".ambara" / "config.yaml"
        config_file.parent.mkdir()
        config_file.write_text("schema_version: 1\nenabled: false\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("AMBARA_KNOWLEDGE_REMOTE", raising=False)

        config = load_config_from_env()

        assert config.disabled is True
        assert config.remote_url == ""

    def test_project_muted_scopes_load_from_local_config(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / ".ambara" / "config.yaml"
        config_file.parent.mkdir()
        config_file.write_text(
            "\n".join(
                [
                    "schema_version: 1",
                    "muted_scopes:",
                    "  projects:",
                    "    - LEGACY-PROJ",
                    "  repos:",
                    "    - Org/API",
                    "  signal_sources:",
                    "    - GitHub",
                    "  tags:",
                    "    - stale",
                    "",
                ]
            )
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")

        config = load_config_from_env()

        assert config.muted_scopes.projects == ("legacy-proj",)
        assert config.muted_scopes.repos == ("org/api",)
        assert config.muted_scopes.signal_sources == ("github",)
        assert config.muted_scopes.tags == ("stale",)

    def test_entry_feedback_loads_from_local_config(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / ".ambara" / "config.yaml"
        config_file.parent.mkdir()
        config_file.write_text(
            "\n".join(
                [
                    "schema_version: 1",
                    "entry_feedback:",
                    "  old-entry: not-useful",
                    "  pinned-entry: pin",
                    "  ignored-entry: nonsense",
                    "",
                ]
            )
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")

        config = load_config_from_env()

        assert config.entry_feedback == {
            "old-entry": "not_useful",
            "pinned-entry": "pin",
        }

    def test_malformed_project_config_raises(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / ".ambara" / "config.yaml"
        config_file.parent.mkdir()
        config_file.write_text("enabled: [\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")

        with pytest.raises(ValueError, match="Could not parse project config"):
            load_config_from_env()


class TestRepoGraph:
    def test_repo_graph_default_empty(self) -> None:
        config = AmbaraConfig(remote_url="https://example.com/repo.git")
        assert config.repo_graph == {}

    def test_repo_graph_with_deps(self) -> None:
        config = AmbaraConfig(
            remote_url="https://example.com/repo.git",
            repo_graph={"api-service": ["shared-libs", "auth-service"]},
        )
        assert config.repo_graph["api-service"] == ["shared-libs", "auth-service"]


class TestSecretPatterns:
    def test_secret_patterns_default_empty(self) -> None:
        config = AmbaraConfig(remote_url="https://example.com/repo.git")
        assert config.secret_patterns == []

    def test_secret_patterns_from_config(self) -> None:
        config = AmbaraConfig(
            remote_url="https://example.com/repo.git",
            secret_patterns=["CUSTOM_TOKEN_[A-Z0-9]+", "my-org-secret-\\w+"],
        )
        assert len(config.secret_patterns) == 2


class TestPRSignalsConfig:
    def test_defaults(self) -> None:
        cfg = PRSignalsConfig()
        assert cfg.provider == "github"
        assert cfg.label == "ambara"
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

    def test_ambara_config_default_pr_signals(self) -> None:
        config = AmbaraConfig(remote_url="https://example.com/repo.git")
        assert config.pr_signals == PRSignalsConfig()
        assert config.pr_signals.repos == ()

    def test_ambara_config_custom_pr_signals(self) -> None:
        config = AmbaraConfig(
            remote_url="https://example.com/repo.git",
            pr_signals=PRSignalsConfig(repos=("org/api",), recency_days=7),
        )
        assert config.pr_signals.repos == ("org/api",)
        assert config.pr_signals.recency_days == 7


class TestPRSignalReposEnv:
    def test_empty_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.delenv("AMBARA_PR_SIGNAL_REPOS", raising=False)
        config = load_config_from_env()
        assert config.pr_signals.repos == ()

    def test_multiple_repos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_PR_SIGNAL_REPOS", "org/repo-a,org/repo-b")
        config = load_config_from_env()
        assert config.pr_signals.repos == ("org/repo-a", "org/repo-b")
        assert config.pr_signals.fixture_path is None

    def test_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_PR_SIGNAL_REPOS", " org/a , org/b , ")
        config = load_config_from_env()
        assert config.pr_signals.repos == ("org/a", "org/b")

    def test_fixture_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_PR_SIGNAL_FIXTURE", "/tmp/signals.json")
        config = load_config_from_env()
        assert config.pr_signals.fixture_path == "/tmp/signals.json"


class TestActiveRefsConfig:
    def test_defaults_to_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.delenv("AMBARA_ACTIVE_REFS_ENABLED", raising=False)
        config = load_config_from_env()
        assert config.active_refs_enabled is False

    def test_enabled_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_ACTIVE_REFS_ENABLED", "true")
        config = load_config_from_env()
        assert config.active_refs_enabled is True

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_ACTIVE_REFS_ENABLED", "True")
        config = load_config_from_env()
        assert config.active_refs_enabled is True

    def test_non_true_stays_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_ACTIVE_REFS_ENABLED", "yes")
        config = load_config_from_env()
        assert config.active_refs_enabled is False

    def test_invalid_ttl_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_ACTIVE_REF_TTL_HOURS", "0")

        with pytest.raises(ValueError, match="active_ref_ttl_hours"):
            load_config_from_env()

    def test_ttl_must_not_exceed_validation_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_ACTIVE_REF_TTL_HOURS", "168")
        config = load_config_from_env()
        assert config.active_ref_ttl_hours == 168

        monkeypatch.setenv("AMBARA_ACTIVE_REF_TTL_HOURS", "169")
        with pytest.raises(ValueError, match="between 1 and 168"):
            load_config_from_env()


class TestKeywordConfig:
    def test_keyword_defaults_none(self) -> None:
        config = AmbaraConfig(remote_url="https://example.com/repo.git")
        assert config.revise_keywords is None
        assert config.handoff_keywords is None

    def test_revise_keywords_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_REVISE_KEYWORDS", "curriculum,module,lab")
        config = load_config_from_env()
        assert config.revise_keywords == ("curriculum", "module", "lab")

    def test_handoff_keywords_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_HANDOFF_KEYWORDS", "escalation,compliance")
        config = load_config_from_env()
        assert config.handoff_keywords == ("escalation", "compliance")

    def test_empty_keywords_give_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_REVISE_KEYWORDS", "")
        monkeypatch.setenv("AMBARA_HANDOFF_KEYWORDS", "")
        config = load_config_from_env()
        assert config.revise_keywords is None
        assert config.handoff_keywords is None

    def test_keyword_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_REVISE_KEYWORDS", " foo , bar , ")
        config = load_config_from_env()
        assert config.revise_keywords == ("foo", "bar")


class TestContextFreshnessConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")

        config = load_config_from_env()

        assert config.context_freshness_warning_seconds == 300
        assert config.context_stale_after_seconds == 900
        assert config.context_default_mode == "manifest"

    def test_invalid_warning_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_CONTEXT_FRESHNESS_WARNING_SECONDS", "-1")

        with pytest.raises(ValueError, match="context_freshness_warning_seconds"):
            load_config_from_env()

    def test_stale_must_exceed_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_CONTEXT_FRESHNESS_WARNING_SECONDS", "300")
        monkeypatch.setenv("AMBARA_CONTEXT_STALE_AFTER_SECONDS", "300")

        with pytest.raises(ValueError, match="context_stale_after_seconds"):
            load_config_from_env()

    def test_non_integer_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_CONTEXT_STALE_AFTER_SECONDS", "later")

        with pytest.raises(ValueError, match="AMBARA_CONTEXT_STALE_AFTER_SECONDS"):
            load_config_from_env()

    def test_default_mode_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_CONTEXT_DEFAULT_MODE", "compiler")

        config = load_config_from_env()

        assert config.context_default_mode == "compiler"

    def test_startup_v2_env_selects_startup_default_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_STARTUP_V2_ENABLED", "true")

        config = load_config_from_env()

        assert config.context_default_mode == "startup"

    def test_explicit_default_mode_overrides_startup_v2_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_STARTUP_V2_ENABLED", "true")
        monkeypatch.setenv("AMBARA_CONTEXT_DEFAULT_MODE", "compiler")

        config = load_config_from_env()

        assert config.context_default_mode == "compiler"

    def test_invalid_default_mode_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_CONTEXT_DEFAULT_MODE", "tiny")

        with pytest.raises(ValueError, match="AMBARA_CONTEXT_DEFAULT_MODE"):
            load_config_from_env()


class TestJiraConfig:
    def test_jira_defaults(self) -> None:
        config = PRSignalsConfig()
        assert config.jira_base_url is None
        assert config.jira_projects == ()

    def test_signal_provider_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_SIGNAL_PROVIDER", "jira")
        config = load_config_from_env()
        assert config.pr_signals.provider == "jira"

    def test_jira_base_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_JIRA_BASE_URL", "https://jira.example.com")
        config = load_config_from_env()
        assert config.pr_signals.jira_base_url == "https://jira.example.com"

    def test_jira_projects_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        monkeypatch.setenv("AMBARA_JIRA_PROJECTS", "PROJ, WEB, AUTH")
        config = load_config_from_env()
        assert config.pr_signals.jira_projects == ("PROJ", "WEB", "AUTH")

    def test_jira_projects_empty_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        config = load_config_from_env()
        assert config.pr_signals.jira_projects == ()

    def test_provider_defaults_to_github(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/repo.git")
        config = load_config_from_env()
        assert config.pr_signals.provider == "github"
