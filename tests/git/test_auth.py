"""Tests for jurati.git.auth."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from jurati.git.auth import AuthCandidate, generate_candidates, parse_github_remote


class TestParseGithubRemote:
    def test_ssh_colon_syntax(self) -> None:
        assert parse_github_remote("git@github.com:owner/repo.git") == ("owner", "repo")

    def test_https_with_dot_git(self) -> None:
        assert parse_github_remote("https://github.com/owner/repo.git") == ("owner", "repo")

    def test_https_without_dot_git(self) -> None:
        assert parse_github_remote("https://github.com/owner/repo") == ("owner", "repo")

    def test_ssh_url_syntax(self) -> None:
        assert parse_github_remote("ssh://git@github.com/owner/repo.git") == ("owner", "repo")

    def test_ssh_url_without_dot_git(self) -> None:
        assert parse_github_remote("ssh://git@github.com/owner/repo") == ("owner", "repo")

    def test_gitlab_returns_none(self) -> None:
        assert parse_github_remote("git@gitlab.com:owner/repo.git") is None

    def test_bitbucket_returns_none(self) -> None:
        assert parse_github_remote("https://bitbucket.org/owner/repo.git") is None

    def test_ghe_custom_domain_returns_none(self) -> None:
        assert parse_github_remote("git@github.mycompany.com:org/repo.git") is None

    def test_malformed_url_returns_none(self) -> None:
        assert parse_github_remote("not-a-url") is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_github_remote("") is None

    def test_github_no_repo_returns_none(self) -> None:
        assert parse_github_remote("https://github.com/owner") is None


class TestAuthCandidate:
    def test_frozen(self) -> None:
        c = AuthCandidate(method="branch_only", source="none")
        with pytest.raises(AttributeError):
            c.method = "api_token"  # type: ignore[misc]

    def test_no_token_field(self) -> None:
        c = AuthCandidate(method="api_token", source="env_jurati", owner="o", repo="r")
        assert not hasattr(c, "token")


class TestGenerateCandidates:
    def test_env_jurati_token_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_TOKEN", "fake-token")
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        candidates = generate_candidates("owner", "repo")
        assert candidates[0].source == "env_jurati"
        assert candidates[0].method == "api_token"

    def test_env_gh_token_second(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JURATI_KNOWLEDGE_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "fake-gh-token")
        candidates = generate_candidates("owner", "repo")
        assert candidates[0].source == "env_gh"

    def test_no_env_tokens_skips_to_gh_candidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JURATI_KNOWLEDGE_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("jurati.git.auth.discover_gh_users", return_value=[]):
            candidates = generate_candidates("owner", "repo")
        assert all(c.source != "env_jurati" for c in candidates)
        assert all(c.source != "env_gh" for c in candidates)

    def test_gh_users_produce_per_user_candidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JURATI_KNOWLEDGE_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("jurati.git.auth.discover_gh_users", return_value=["alice", "bob"]):
            candidates = generate_candidates("owner", "repo")
        user_candidates = [c for c in candidates if c.source == "gh_user_token"]
        assert len(user_candidates) == 2
        assert user_candidates[0].gh_user == "alice"
        assert user_candidates[1].gh_user == "bob"

    def test_gh_cli_pr_always_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JURATI_KNOWLEDGE_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch("jurati.git.auth.discover_gh_users", return_value=[]):
            candidates = generate_candidates("owner", "repo")
        cli_candidates = [c for c in candidates if c.source == "gh_cli_pr"]
        assert len(cli_candidates) == 1

    def test_owner_repo_propagated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_TOKEN", "t")
        candidates = generate_candidates("myorg", "myrepo")
        for c in candidates:
            assert c.owner == "myorg"
            assert c.repo == "myrepo"

    def test_github_token_env_var_also_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JURATI_KNOWLEDGE_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "fake-github-token")
        candidates = generate_candidates("owner", "repo")
        assert candidates[0].source == "env_gh"
