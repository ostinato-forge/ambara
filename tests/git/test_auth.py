"""Tests for jurati.git.auth."""

from __future__ import annotations

import json
import subprocess
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


class TestDiscoverGhUsers:
    GH_STATUS_TWO_USERS = json.dumps(
        {
            "hosts": {
                "github.com": [
                    {"login": "alice", "state": "success", "active": True},
                    {"login": "bob", "state": "success", "active": False},
                ],
            },
        }
    )

    @patch("jurati.git.auth.subprocess.run")
    def test_parses_users_from_status_json(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stdout = self.GH_STATUS_TWO_USERS
        mock_run.return_value = result

        from jurati.git.auth import discover_gh_users

        users = discover_gh_users()
        assert users == ["alice", "bob"]

    @patch("jurati.git.auth.subprocess.run")
    def test_filters_out_non_success_accounts(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps(
            {
                "hosts": {
                    "github.com": [
                        {"login": "alice", "state": "success", "active": True},
                        {"login": "bob", "state": "expired", "active": False},
                    ],
                },
            }
        )
        mock_run.return_value = result

        from jurati.git.auth import discover_gh_users

        users = discover_gh_users()
        assert users == ["alice"]

    @patch("jurati.git.auth.subprocess.run")
    def test_returns_empty_on_failure(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        mock_run.side_effect = subprocess.TimeoutExpired("gh", 15)
        from jurati.git.auth import discover_gh_users

        assert discover_gh_users() == []

    @patch("jurati.git.auth.subprocess.run")
    def test_returns_empty_on_nonzero_exit(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        mock_run.return_value = result

        from jurati.git.auth import discover_gh_users

        assert discover_gh_users() == []

    @patch("jurati.git.auth.subprocess.run")
    def test_returns_empty_on_bad_json(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stdout = "not json"
        mock_run.return_value = result

        from jurati.git.auth import discover_gh_users

        assert discover_gh_users() == []

    @patch("jurati.git.auth.subprocess.run")
    def test_uses_prompt_safe_env(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stdout = self.GH_STATUS_TWO_USERS
        mock_run.return_value = result

        from jurati.git.auth import discover_gh_users

        discover_gh_users()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("stdin") == subprocess.DEVNULL
        assert call_kwargs.kwargs.get("capture_output") is True
        assert call_kwargs.kwargs.get("timeout") == 15
        env = call_kwargs.kwargs.get("env", {})
        assert env.get("GH_PROMPT_DISABLED") == "1"


class TestReadToken:
    def test_env_jurati(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURATI_KNOWLEDGE_TOKEN", "my-jurati-token")
        candidate = AuthCandidate(
            method="api_token",
            source="env_jurati",
            owner="o",
            repo="r",
        )
        from jurati.git.auth import read_token

        assert read_token(candidate) == "my-jurati-token"

    def test_env_gh_prefers_gh_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GH_TOKEN", "gh-token-value")
        monkeypatch.setenv("GITHUB_TOKEN", "github-token-value")
        candidate = AuthCandidate(
            method="api_token",
            source="env_gh",
            owner="o",
            repo="r",
        )
        from jurati.git.auth import read_token

        assert read_token(candidate) == "gh-token-value"

    def test_env_gh_falls_back_to_github_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "github-token-value")
        candidate = AuthCandidate(
            method="api_token",
            source="env_gh",
            owner="o",
            repo="r",
        )
        from jurati.git.auth import read_token

        assert read_token(candidate) == "github-token-value"

    @patch("jurati.git.auth.subprocess.run")
    def test_gh_user_token(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stdout = "gho_abc123\n"
        mock_run.return_value = result

        candidate = AuthCandidate(
            method="api_token",
            source="gh_user_token",
            owner="o",
            repo="r",
            gh_user="alice",
        )
        from jurati.git.auth import read_token

        assert read_token(candidate) == "gho_abc123"

    @patch("jurati.git.auth.subprocess.run")
    def test_gh_user_token_uses_user_flag(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        from unittest.mock import MagicMock

        result = MagicMock()
        result.returncode = 0
        result.stdout = "gho_abc123\n"
        mock_run.return_value = result

        candidate = AuthCandidate(
            method="api_token",
            source="gh_user_token",
            owner="o",
            repo="r",
            gh_user="alice",
        )
        from jurati.git.auth import read_token

        read_token(candidate)
        cmd = mock_run.call_args[0][0]
        assert "--user" in cmd
        assert "alice" in cmd

    @patch("jurati.git.auth.subprocess.run")
    def test_gh_user_token_timeout_returns_none(self, mock_run) -> None:  # type: ignore[no-untyped-def]
        mock_run.side_effect = subprocess.TimeoutExpired("gh", 15)
        candidate = AuthCandidate(
            method="api_token",
            source="gh_user_token",
            owner="o",
            repo="r",
            gh_user="alice",
        )
        from jurati.git.auth import read_token

        assert read_token(candidate) is None

    def test_non_token_candidate_returns_none(self) -> None:
        candidate = AuthCandidate(method="gh_cli", source="gh_cli_pr", owner="o", repo="r")
        from jurati.git.auth import read_token

        assert read_token(candidate) is None


class TestPromptSafeEnv:
    def test_includes_gh_prompt_disabled(self) -> None:
        from jurati.git.auth import _gh_subprocess_env

        env = _gh_subprocess_env()
        assert env["GH_PROMPT_DISABLED"] == "1"

    def test_inherits_path(self) -> None:
        from jurati.git.auth import _gh_subprocess_env

        env = _gh_subprocess_env()
        assert "PATH" in env
