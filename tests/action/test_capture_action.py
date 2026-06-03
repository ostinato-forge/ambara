# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for ambara action capture — batching, merge strategies, auto-merge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from ambara.action.capture import (
    _authenticated_remote,
    _prepare_knowledge_repo,
    _source_context,
    collect_ambara_messages,
    derive_batch_branch,
    extract_ambara_lines_from_body,
    main,
    message_dedup_key,
)
from ambara.capture.pipeline import CaptureOutcome
from ambara.core.schema import EscalationLevel
from ambara.git.repo import repo_cache_path


class TestCollectMessages:
    def test_filters_ambara_commits(self) -> None:
        commits = [
            {"sha": "a1", "message": "ambara: pool limit", "author": "dev@co.com"},
            {"sha": "a2", "message": "feat: other work", "author": "dev@co.com"},
            {"sha": "a3", "message": "ambara(decision): switch to gRPC", "author": "dev@co.com"},
        ]
        results = collect_ambara_messages(commits)
        assert len(results) == 2
        assert results[0]["sha"] == "a1"
        assert results[1]["sha"] == "a3"


class TestBatchBranch:
    def test_batch_branch_name(self) -> None:
        branch = derive_batch_branch("api-service", "abc123def456")
        assert branch == "ambara/api-service/batch-abc123"

    def test_single_entry_uses_normal_branch(self) -> None:
        branch = derive_batch_branch("api-service", "abc123def456", count=1)
        assert branch is None


class TestSquashMergeSupport:
    def test_extracts_ambara_lines_from_pr_body(self) -> None:
        body = (
            "## Summary\n\n"
            "ambara: pool limit changed\n"
            "ambara(decision): switch to gRPC\n"
            "Other text.\n"
        )
        lines = extract_ambara_lines_from_body(body)
        assert len(lines) == 2
        assert lines[0] == "ambara: pool limit changed"
        assert lines[1] == "ambara(decision): switch to gRPC"

    def test_empty_body_returns_empty(self) -> None:
        assert extract_ambara_lines_from_body("") == []
        assert extract_ambara_lines_from_body(None) == []


class TestMessageDedupKey:
    def test_deterministic(self) -> None:
        k1 = message_dedup_key("ambara: pool limit")
        k2 = message_dedup_key("ambara: pool limit")
        assert k1 == k2

    def test_different_messages_different_keys(self) -> None:
        k1 = message_dedup_key("ambara: pool limit")
        k2 = message_dedup_key("ambara: cache TTL")
        assert k1 != k2


class TestAuthenticatedRemote:
    def test_https_remote_uses_token(self) -> None:
        remote = _authenticated_remote("https://github.com/org/knowledge.git", "tok")
        assert remote == "https://x-access-token:tok@github.com/org/knowledge.git"

    def test_ssh_remote_converts_to_https(self) -> None:
        remote = _authenticated_remote("git@github.com:org/knowledge.git", "tok")
        assert remote == "https://x-access-token:tok@github.com/org/knowledge.git"

    def test_non_github_remote_left_alone(self) -> None:
        remote = _authenticated_remote("https://example.com/org/knowledge.git", "tok")
        assert remote == "https://example.com/org/knowledge.git"

    def test_gitlab_remote_uses_token(self) -> None:
        remote = _authenticated_remote("https://gitlab.com/group/knowledge.git", "tok")
        assert remote == "https://oauth2:tok@gitlab.com/group/knowledge.git"


class TestSourceContext:
    def test_prefers_manual_override(self, monkeypatch) -> None:
        monkeypatch.setenv("AMBARA_SOURCE_REPOSITORY", "team/platform")
        monkeypatch.setenv("AMBARA_SOURCE_SHA", "abc123")
        monkeypatch.setenv("AMBARA_SOURCE_BEFORE", "def456")
        monkeypatch.setenv("AMBARA_CALLER_SOURCE", "gitlab_ci")

        assert _source_context() == ("team/platform", "abc123", "def456", "gitlab_ci")

    def test_gitlab_context(self, monkeypatch) -> None:
        monkeypatch.delenv("AMBARA_SOURCE_REPOSITORY", raising=False)
        monkeypatch.delenv("AMBARA_SOURCE_SHA", raising=False)
        monkeypatch.setenv("CI_PROJECT_PATH", "group/api-service")
        monkeypatch.setenv("CI_COMMIT_SHA", "abc123")
        monkeypatch.setenv("CI_COMMIT_BEFORE_SHA", "def456")

        assert _source_context() == ("group/api-service", "abc123", "def456", "gitlab_ci")


class TestPrepareKnowledgeRepo:
    @patch("ambara.action.capture.fetch_all")
    @patch("ambara.action.capture.git.Repo")
    @patch("ambara.action.capture.os.path.isdir", return_value=True)
    def test_reuses_existing_repo_and_updates_origin(
        self, mock_isdir, mock_repo_cls, mock_fetch
    ) -> None:
        repo = MagicMock()
        mock_repo_cls.return_value = repo

        path = _prepare_knowledge_repo(
            remote="https://github.com/org/knowledge.git",
            cache_dir="/tmp/cache",
            main_branch="main",
            token="tok",
        )

        assert path == repo_cache_path("https://github.com/org/knowledge.git", "/tmp/cache")
        repo.remotes.origin.set_url.assert_called_once_with(
            "https://x-access-token:tok@github.com/org/knowledge.git"
        )
        mock_fetch.assert_called_once_with(path, "main")


class TestMain:
    @patch("ambara.action.capture._prepare_knowledge_repo", return_value="/knowledge")
    @patch("ambara.action.capture._git")
    def test_main_bootstraps_repo_and_passes_caller_source(
        self, mock_git, mock_prepare, monkeypatch, capsys
    ) -> None:
        mock_git.side_effect = [
            "abc123",
            "ambara: pool limit changed",
            "dev@co.com",
        ]
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/api-service")
        monkeypatch.setenv("GITHUB_SHA", "abc123")
        monkeypatch.setenv("GITHUB_EVENT_BEFORE", "")
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://github.com/org/knowledge.git")
        monkeypatch.setenv("AMBARA_KNOWLEDGE_TOKEN", "tok")
        monkeypatch.setenv("AMBARA_MAIN_BRANCH", "main")
        monkeypatch.setenv("AMBARA_CACHE_DIR", "/tmp/ambara-action-main")

        with patch(
            "ambara.capture.pipeline.run_capture",
            return_value=CaptureOutcome(
                entry_id="api-service-pool-limit-changed",
                level=EscalationLevel.L1,
                sha="abc123",
                branch="ambara/api-service/pool-limit-changed",
                secret_detected=False,
            ),
        ) as mock_run_capture:
            main()

        mock_prepare.assert_called_once_with(
            remote="https://github.com/org/knowledge.git",
            cache_dir="/tmp/ambara-action-main",
            main_branch="main",
            token="tok",
        )
        assert mock_run_capture.call_args.kwargs["knowledge_repo_path"] == "/knowledge"
        assert mock_run_capture.call_args.kwargs["caller_source"] == "github_actions"
        out = capsys.readouterr().out
        assert "captured" in out
        assert "auto-merge eligible" in out

    @patch("ambara.action.capture._prepare_knowledge_repo", return_value="/knowledge")
    @patch("ambara.action.capture._git")
    def test_main_supports_gitlab_ci(
        self, mock_git, mock_prepare, monkeypatch, capsys
    ) -> None:
        mock_git.side_effect = [
            "abc123",
            "ambara: pool limit changed",
            "dev@co.com",
        ]
        monkeypatch.setenv("CI_PROJECT_PATH", "group/api-service")
        monkeypatch.setenv("CI_COMMIT_SHA", "abc123")
        monkeypatch.setenv("CI_COMMIT_BEFORE_SHA", "")
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://gitlab.com/group/knowledge.git")
        monkeypatch.setenv("AMBARA_KNOWLEDGE_TOKEN", "tok")
        monkeypatch.setenv("AMBARA_MAIN_BRANCH", "main")
        monkeypatch.setenv("AMBARA_CACHE_DIR", "/tmp/ambara-gitlab-main")

        with patch(
            "ambara.capture.pipeline.run_capture",
            return_value=CaptureOutcome(
                entry_id="api-service-pool-limit-changed",
                level=EscalationLevel.L1,
                sha="abc123",
                branch="ambara/api-service/pool-limit-changed",
                secret_detected=False,
            ),
        ) as mock_run_capture:
            main()

        mock_prepare.assert_called_once_with(
            remote="https://gitlab.com/group/knowledge.git",
            cache_dir="/tmp/ambara-gitlab-main",
            main_branch="main",
            token="tok",
        )
        assert mock_run_capture.call_args.kwargs["knowledge_repo_path"] == "/knowledge"
        assert mock_run_capture.call_args.kwargs["caller_source"] == "gitlab_ci"
        out = capsys.readouterr().out
        assert "Captured 1 entries from api-service" in out

    @patch("ambara.action.capture._prepare_knowledge_repo", return_value="/knowledge")
    @patch("ambara.action.capture._git")
    def test_main_reports_review_required_and_warning(
        self, mock_git, mock_prepare, monkeypatch, capsys
    ) -> None:
        mock_git.side_effect = [
            "abc123",
            "ambara: reach jane@example.com for deploy access",
            "dev@co.com",
        ]
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/api-service")
        monkeypatch.setenv("GITHUB_SHA", "abc123")
        monkeypatch.setenv("GITHUB_EVENT_BEFORE", "")
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://github.com/org/knowledge.git")

        with patch(
            "ambara.capture.pipeline.run_capture",
            return_value=CaptureOutcome(
                entry_id="api-service-reach-jane",
                level=EscalationLevel.L2,
                sha="abc123",
                branch="ambara/api-service/reach-jane",
                secret_detected=False,
                content_policy_action="require_review",
                content_policy_rules=("pii.email",),
                content_policy_warning="Content allowed with warning (risk_phrase).",
            ),
        ):
            main()

        out = capsys.readouterr().out
        assert "content review required: pii.email" in out
        assert "warning: Content allowed with warning (risk_phrase)." in out

    @patch("ambara.action.capture.fetch_all")
    @patch("ambara.action.capture.git.Repo.clone_from")
    @patch("ambara.action.capture.os.path.isdir", return_value=False)
    def test_clones_missing_repo_with_authenticated_remote(
        self, mock_isdir, mock_clone, mock_fetch, tmp_path: Path
    ) -> None:
        cache_dir = str(tmp_path / "cache")
        path = _prepare_knowledge_repo(
            remote="git@github.com:org/knowledge.git",
            cache_dir=cache_dir,
            main_branch="main",
            token="tok",
        )

        assert path == repo_cache_path("git@github.com:org/knowledge.git", cache_dir)
        mock_clone.assert_called_once_with(
            "https://x-access-token:tok@github.com/org/knowledge.git",
            path,
        )
        mock_fetch.assert_called_once_with(path, "main")

    @patch("ambara.action.capture.fetch_all")
    @patch("ambara.action.capture.git.Repo.clone_from")
    @patch("ambara.action.capture.os.path.isdir", return_value=False)
    def test_clones_missing_gitlab_repo_with_authenticated_remote(
        self, mock_isdir, mock_clone, mock_fetch, tmp_path: Path
    ) -> None:
        cache_dir = str(tmp_path / "cache")
        path = _prepare_knowledge_repo(
            remote="git@gitlab.com:group/knowledge.git",
            cache_dir=cache_dir,
            main_branch="main",
            token="tok",
        )

        assert path == repo_cache_path("git@gitlab.com:group/knowledge.git", cache_dir)
        mock_clone.assert_called_once_with(
            "https://oauth2:tok@gitlab.com/group/knowledge.git",
            path,
        )
        mock_fetch.assert_called_once_with(path, "main")
