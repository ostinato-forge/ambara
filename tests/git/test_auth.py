"""Tests for jurati.git.auth."""

from __future__ import annotations

from jurati.git.auth import parse_github_remote


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
