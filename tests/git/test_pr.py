"""Tests for jurati.git.pr."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from jurati.git.auth import AuthCandidate
from jurati.git.pr import PRResult, StalePR, create_pr, list_open_prs


def _api_candidate(owner: str = "org", repo: str = "repo") -> AuthCandidate:
    return AuthCandidate(
        method="api_token",
        source="env_jurati",
        owner=owner,
        repo=repo,
    )


def _gh_user_candidate(user: str = "alice") -> AuthCandidate:
    return AuthCandidate(
        method="api_token",
        source="gh_user_token",
        owner="org",
        repo="repo",
        gh_user=user,
    )


def _cli_candidate(owner: str = "org", repo: str = "repo") -> AuthCandidate:
    return AuthCandidate(
        method="gh_cli",
        source="gh_cli_pr",
        owner=owner,
        repo=repo,
    )


class TestPRResult:
    def test_pr_kind(self) -> None:
        r = PRResult(url="https://github.com/o/r/pull/1", number=1, branch="b", kind="pr")
        assert r.kind == "pr"
        assert r.number == 1

    def test_branch_kind(self) -> None:
        r = PRResult(url=None, number=None, branch="b", kind="branch")
        assert r.kind == "branch"
        assert r.number is None
        assert r.url is None


class TestCreatePrApiStrategy:
    @patch("jurati.git.pr.read_token", return_value="tok_abc")
    @patch("jurati.git.pr.httpx")
    def test_creates_pr_via_api(self, mock_httpx, mock_read_token) -> None:
        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "html_url": "https://github.com/org/repo/pull/42",
            "number": 42,
        }
        label_response = MagicMock()
        label_response.status_code = 200
        mock_httpx.post.side_effect = [pr_response, label_response]

        pr_result, winning = create_pr(
            "/repo",
            "feat/test",
            "Title",
            "Body",
            labels=["jurati", "low-ceremony"],
            base="main",
            candidates=[_api_candidate()],
        )
        assert pr_result.kind == "pr"
        assert pr_result.number == 42
        assert pr_result.url == "https://github.com/org/repo/pull/42"
        assert winning is not None
        assert winning.source == "env_jurati"

    @patch("jurati.git.pr.read_token", return_value="tok_abc")
    @patch("jurati.git.pr.httpx")
    def test_api_sets_timeout(self, mock_httpx, mock_read_token) -> None:
        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "html_url": "https://github.com/org/repo/pull/1",
            "number": 1,
        }
        label_response = MagicMock()
        label_response.status_code = 200
        mock_httpx.post.side_effect = [pr_response, label_response]

        create_pr(
            "/repo",
            "feat/test",
            "Title",
            "Body",
            labels=["jurati"],
            base="main",
            candidates=[_api_candidate()],
        )
        call_kwargs = mock_httpx.post.call_args_list[0]
        assert call_kwargs.kwargs.get("timeout") == 30

    @patch("jurati.git.pr.read_token", return_value="tok_abc")
    @patch("jurati.git.pr.httpx")
    def test_label_failure_is_nonfatal(self, mock_httpx, mock_read_token) -> None:
        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "html_url": "https://github.com/org/repo/pull/5",
            "number": 5,
        }
        mock_httpx.post.side_effect = [pr_response, Exception("label failed")]

        pr_result, _ = create_pr(
            "/repo",
            "feat/test",
            "Title",
            "Body",
            labels=["jurati"],
            base="main",
            candidates=[_api_candidate()],
        )
        assert pr_result.kind == "pr"
        assert pr_result.number == 5

    @patch("jurati.git.pr.read_token", return_value="tok_abc")
    @patch("jurati.git.pr.httpx")
    def test_malformed_api_response_falls_through(self, mock_httpx, mock_read_token) -> None:
        bad_response = MagicMock()
        bad_response.status_code = 201
        bad_response.json.side_effect = Exception("not json")
        mock_httpx.post.return_value = bad_response

        pr_result, winning = create_pr(
            "/repo",
            "feat/test",
            "Title",
            "Body",
            labels=[],
            base="main",
            candidates=[_api_candidate()],
        )
        assert pr_result.kind == "branch"
        assert winning is None


class TestCreatePrCandidateIteration:
    @patch("jurati.git.pr.read_token", return_value="tok_abc")
    @patch("jurati.git.pr.httpx")
    def test_first_failing_candidate_tries_next(self, mock_httpx, mock_read_token) -> None:
        fail_response = MagicMock()
        fail_response.status_code = 401
        fail_response.text = "Bad credentials"
        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "html_url": "https://github.com/org/repo/pull/7",
            "number": 7,
        }
        mock_httpx.post.side_effect = [fail_response, pr_response]

        bob = _gh_user_candidate("bob")
        candidates = [_api_candidate(), bob]
        pr_result, winning = create_pr(
            "/repo",
            "feat/test",
            "Title",
            "Body",
            labels=[],
            base="main",
            candidates=candidates,
        )
        assert pr_result.kind == "pr"
        assert pr_result.number == 7
        assert winning is bob

    @patch("jurati.git.pr.read_token", return_value=None)
    def test_no_token_skips_api_candidate(self, mock_read_token) -> None:
        pr_result, winning = create_pr(
            "/repo",
            "feat/test",
            "Title",
            "Body",
            labels=[],
            base="main",
            candidates=[_api_candidate()],
        )
        assert pr_result.kind == "branch"
        assert winning is None


class TestCreatePrGhCliStrategy:
    @patch("jurati.git.pr.subprocess.run")
    def test_gh_cli_with_repo_flag(self, mock_run) -> None:
        result_mock = MagicMock()
        result_mock.returncode = 0
        result_mock.stdout = "https://github.com/org/repo/pull/10\n"
        mock_run.return_value = result_mock

        pr_result, winning = create_pr(
            "/repo",
            "feat/test",
            "Title",
            "Body",
            labels=["jurati"],
            base="main",
            candidates=[_cli_candidate()],
        )
        assert pr_result.kind == "pr"
        assert pr_result.number == 10
        assert winning is not None
        assert winning.source == "gh_cli_pr"

        cmd = mock_run.call_args[0][0]
        assert "--repo" in cmd
        assert "org/repo" in cmd
        assert mock_run.call_args.kwargs.get("timeout") == 30
        assert mock_run.call_args.kwargs.get("stdin") == subprocess.DEVNULL

    @patch("jurati.git.pr.subprocess.run")
    def test_gh_cli_failure_falls_to_branch_only(self, mock_run) -> None:
        result_mock = MagicMock()
        result_mock.returncode = 1
        result_mock.stdout = ""
        mock_run.return_value = result_mock

        pr_result, winning = create_pr(
            "/repo",
            "feat/test",
            "Title",
            "Body",
            labels=[],
            base="main",
            candidates=[_cli_candidate()],
        )
        assert pr_result.kind == "branch"
        assert winning is None


class TestCreatePrBranchOnly:
    def test_empty_candidates_returns_branch_only(self) -> None:
        pr_result, winning = create_pr(
            "/repo",
            "feat/test",
            "Title",
            "Body",
            labels=[],
            base="main",
            candidates=[],
        )
        assert pr_result.kind == "branch"
        assert pr_result.number is None
        assert pr_result.url is None
        assert winning is None

    def test_branch_only_with_owner_repo_has_compare_url(self) -> None:
        candidate = AuthCandidate(
            method="branch_only",
            source="none",
            owner="org",
            repo="repo",
        )
        pr_result, winning = create_pr(
            "/repo",
            "feat/test",
            "Title",
            "Body",
            labels=[],
            base="main",
            candidates=[candidate],
        )
        assert pr_result.kind == "branch"
        assert pr_result.url is not None
        assert "compare/main...feat/test" in pr_result.url
        assert "expand=1" in pr_result.url
        assert winning is None

    def test_branch_only_without_owner_repo_has_no_url(self) -> None:
        candidate = AuthCandidate(
            method="branch_only",
            source="none",
        )
        pr_result, winning = create_pr(
            "/repo",
            "feat/test",
            "Title",
            "Body",
            labels=[],
            base="main",
            candidates=[candidate],
        )
        assert pr_result.kind == "branch"
        assert pr_result.url is None
        assert winning is None


class TestListOpenPrs:
    GH_OUTPUT = (
        '[{"number":3,"title":"feat(kb): add old-entry",'
        '"url":"https://github.com/o/r/pull/3",'
        '"createdAt":"2026-03-01T10:00:00Z","headRefName":"jurati/old-entry"},'
        '{"number":5,"title":"feat(kb): add recent-entry",'
        '"url":"https://github.com/o/r/pull/5",'
        '"createdAt":"2026-05-03T10:00:00Z","headRefName":"jurati/recent-entry"}]'
    )

    @patch("jurati.git.pr.subprocess.run")
    def test_filters_by_age(self, mock_run: MagicMock) -> None:
        result_mock = MagicMock()
        result_mock.returncode = 0
        result_mock.stdout = self.GH_OUTPUT
        mock_run.return_value = result_mock

        stale = list_open_prs("/repo", older_than_days=30)
        assert len(stale) == 1
        assert stale[0].number == 3
        assert stale[0].branch == "jurati/old-entry"
        assert isinstance(stale[0], StalePR)

    @patch("jurati.git.pr.subprocess.run", side_effect=FileNotFoundError)
    def test_gh_not_found_returns_empty(self, mock_run: MagicMock) -> None:
        assert list_open_prs("/repo") == []

    @patch("jurati.git.pr.subprocess.run")
    def test_bad_json_returns_empty(self, mock_run: MagicMock) -> None:
        result_mock = MagicMock()
        result_mock.returncode = 0
        result_mock.stdout = "not json"
        mock_run.return_value = result_mock
        assert list_open_prs("/repo") == []

    @patch(
        "jurati.git.pr.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=30),
    )
    def test_timeout_returns_empty(self, mock_run: MagicMock) -> None:
        assert list_open_prs("/repo") == []

    @patch("jurati.git.pr.subprocess.run")
    def test_nonzero_exit_returns_empty(self, mock_run: MagicMock) -> None:
        result_mock = MagicMock()
        result_mock.returncode = 1
        result_mock.stdout = ""
        mock_run.return_value = result_mock
        assert list_open_prs("/repo") == []
