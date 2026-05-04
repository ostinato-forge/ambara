"""Tests for jurati.server write orchestration."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from jurati.core.changes import ExpireIntent, WriteIntent
from jurati.core.schema import EntryStatus, EscalationLevel
from jurati.server import _do_active_record, _finish_pr_write


class TestPlanRecord:
    def test_l0_uses_active_ref(self) -> None:
        from jurati.core.changes import plan_record
        from jurati.core.schema import EntryType

        intent = plan_record(
            EntryType.ACTIVE,
            "Sprint goal",
            "Ship v1",
            entry_id="sprint-goal",
            level=EscalationLevel.L0,
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            expires_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            client="test-client",
        )
        assert intent.write_mode == "active_ref"
        assert "jurati/active/test-client/sprint-goal" in intent.branch

    def test_l1_uses_lightweight_pr(self) -> None:
        from jurati.core.changes import plan_record
        from jurati.core.schema import EntryType

        intent = plan_record(
            EntryType.PROJECT,
            "New project",
            "Project body",
            entry_id="new-project",
            level=EscalationLevel.L1,
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        )
        assert intent.write_mode == "lightweight_pr"

    def test_l2_rejected(self) -> None:
        from jurati.core.changes import plan_record
        from jurati.core.schema import EntryType

        with pytest.raises(ValueError, match="cannot create L2"):
            plan_record(
                EntryType.DECISION,
                "Decision",
                "Body",
                entry_id="dec-1",
                level=EscalationLevel.L2,
                now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            )


class TestPlanPropose:
    def test_l2_uses_review_pr(self) -> None:
        from jurati.core.changes import plan_propose
        from jurati.core.schema import EntryType

        intent = plan_propose(
            EntryType.DECISION,
            "Decision",
            "Body",
            entry_id="dec-1",
            level=EscalationLevel.L2,
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        )
        assert intent.write_mode == "review_pr"

    def test_l0_rejected(self) -> None:
        from jurati.core.changes import plan_propose
        from jurati.core.schema import EntryType

        with pytest.raises(ValueError, match="cannot create L0"):
            plan_propose(
                EntryType.ACTIVE,
                "Active",
                "Body",
                entry_id="active-1",
                level=EscalationLevel.L0,
                now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            )


class TestDoActiveRecord:
    @patch("jurati.server.cleanup_branch")
    @patch("jurati.server.push_active_ref")
    @patch("jurati.server.materialize_write", return_value="abc123")
    @patch("jurati.server.create_branch")
    def test_sequence(self, mock_create, mock_write, mock_push, mock_cleanup) -> None:
        intent = WriteIntent(
            path="active/sprint.md",
            content="content",
            branch="jurati/active/client/sprint",
            write_mode="active_ref",
            entry_id="sprint",
            level=EscalationLevel.L0,
        )
        lock = threading.Lock()
        sha = _do_active_record(lock, "/repo", intent, "main")
        assert sha == "abc123"
        mock_create.assert_called_once()
        mock_write.assert_called_once()
        mock_push.assert_called_once_with("/repo", "jurati/active/client/sprint", "abc123")
        mock_cleanup.assert_called_once()


class TestFinishPrWrite:
    @patch("jurati.server.create_pr")
    @patch("jurati.server.push_branch")
    @patch("jurati.server.materialize_write", return_value="sha123")
    @patch("jurati.server.create_branch")
    @patch("jurati.server.cleanup_branch")
    def test_serialized_lifecycle(
        self, mock_cleanup, mock_create_branch, mock_write, mock_push, mock_create_pr
    ) -> None:
        from jurati.git.auth import AuthCandidate
        from jurati.git.pr import PRResult

        winning = AuthCandidate(
            method="api_token",
            source="env_jurati",
            owner="owner",
            repo="repo",
        )
        mock_create_pr.return_value = (
            PRResult(
                url="https://github.com/o/r/pull/1",
                number=1,
                branch="jurati/proj",
                kind="pr",
            ),
            winning,
        )
        intent = WriteIntent(
            path="projects/proj.md",
            content="content",
            branch="jurati/proj",
            write_mode="lightweight_pr",
            entry_id="proj",
            level=EscalationLevel.L1,
        )
        lock = threading.Lock()
        sha, pr_result, cached = _finish_pr_write(
            lock,
            "/repo",
            intent,
            title="feat(kb): add proj",
            body="Add project entry: Proj",
            labels=["jurati", "low-ceremony"],
            base="main",
            remote_url="git@github.com:owner/repo.git",
            cached_candidate=None,
        )
        assert sha == "sha123"
        assert pr_result.kind == "pr"
        assert cached is winning
        mock_create_branch.assert_called_once()
        mock_write.assert_called_once()
        mock_push.assert_called_once()
        mock_create_pr.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch("jurati.server.create_pr")
    @patch("jurati.server.push_branch")
    @patch("jurati.server.materialize_write", return_value="sha456")
    @patch("jurati.server.create_branch")
    @patch("jurati.server.cleanup_branch")
    def test_cleanup_runs_on_pr_failure(
        self, mock_cleanup, mock_create_branch, mock_write, mock_push, mock_create_pr
    ) -> None:
        from jurati.git.pr import PRResult

        mock_create_pr.return_value = (
            PRResult(
                url=None,
                number=None,
                branch="jurati/proj",
                kind="branch",
            ),
            None,
        )
        intent = WriteIntent(
            path="projects/proj.md",
            content="content",
            branch="jurati/proj",
            write_mode="lightweight_pr",
            entry_id="proj",
            level=EscalationLevel.L1,
        )
        lock = threading.Lock()
        sha, pr_result, cached = _finish_pr_write(
            lock,
            "/repo",
            intent,
            title="t",
            body="b",
            labels=[],
            base="main",
            remote_url="git@github.com:owner/repo.git",
            cached_candidate=None,
        )
        assert pr_result.kind == "branch"
        assert cached is None
        mock_cleanup.assert_called_once()

    @patch("jurati.server.create_pr")
    @patch("jurati.server.push_branch")
    @patch("jurati.server.materialize_expire", return_value="sha789")
    @patch("jurati.server.create_branch")
    @patch("jurati.server.cleanup_branch")
    def test_expire_intent_uses_materialize_expire(
        self, mock_cleanup, mock_create_branch, mock_expire, mock_push, mock_create_pr
    ) -> None:
        from jurati.git.pr import PRResult

        mock_create_pr.return_value = (
            PRResult(
                url="https://github.com/o/r/pull/3",
                number=3,
                branch="jurati/expire-old",
                kind="pr",
            ),
            None,
        )
        intent = ExpireIntent(
            entry_id="old-dec",
            path="decisions/old-dec.md",
            write_mode="review_pr",
            branch="jurati/expire-old",
            new_status=EntryStatus.EXPIRED,
        )
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        lock = threading.Lock()
        sha, pr_result, _ = _finish_pr_write(
            lock,
            "/repo",
            intent,
            title="chore(kb): expire old-dec",
            body="Expire entry",
            labels=["jurati", "review-required"],
            base="main",
            remote_url="git@github.com:owner/repo.git",
            cached_candidate=None,
            now=now,
        )
        assert sha == "sha789"
        mock_expire.assert_called_once_with("/repo", intent, now)

    @patch("jurati.server.create_pr")
    @patch("jurati.server.push_branch")
    @patch("jurati.server.materialize_write", return_value="sha000")
    @patch("jurati.server.create_branch")
    @patch("jurati.server.cleanup_branch")
    def test_non_github_remote_goes_branch_only(
        self, mock_cleanup, mock_create_branch, mock_write, mock_push, mock_create_pr
    ) -> None:
        from jurati.git.pr import PRResult

        mock_create_pr.return_value = (
            PRResult(
                url=None,
                number=None,
                branch="jurati/proj",
                kind="branch",
            ),
            None,
        )
        intent = WriteIntent(
            path="projects/proj.md",
            content="content",
            branch="jurati/proj",
            write_mode="lightweight_pr",
            entry_id="proj",
            level=EscalationLevel.L1,
        )
        lock = threading.Lock()
        sha, pr_result, _ = _finish_pr_write(
            lock,
            "/repo",
            intent,
            title="t",
            body="b",
            labels=[],
            base="main",
            remote_url="git@gitlab.com:owner/repo.git",
            cached_candidate=None,
        )
        assert pr_result.kind == "branch"
        mock_create_pr.assert_called_once()
        args = mock_create_pr.call_args
        assert args.kwargs["candidates"] == []
