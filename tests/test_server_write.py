"""Tests for ambara.server write orchestration."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from ambara.core.changes import ExpireIntent, WriteIntent
from ambara.core.schema import EntryStatus, EscalationLevel
from ambara.server import _do_active_record, _finish_pr_write


class TestExpiresAtParsing:
    def test_bare_date_defaults_to_utc(self) -> None:
        from ambara.core.changes import plan_record
        from ambara.core.schema import EntryType

        intent = plan_record(
            EntryType.ACTIVE,
            "Test",
            "Body",
            entry_id="bare-date-test",
            level=EscalationLevel.L0,
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            expires_at=datetime.fromisoformat("2026-05-20").replace(tzinfo=UTC),
            client="test-client",
        )
        assert "2026-05-20T00:00:00Z" in intent.content

    def test_full_iso_datetime_preserved(self) -> None:
        from ambara.core.changes import plan_record
        from ambara.core.schema import EntryType

        intent = plan_record(
            EntryType.ACTIVE,
            "Test",
            "Body",
            entry_id="full-iso-test",
            level=EscalationLevel.L0,
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            expires_at=datetime(2026, 5, 20, 14, 30, tzinfo=UTC),
            client="test-client",
        )
        assert "2026-05-20T14:30:00Z" in intent.content

    def test_naive_datetime_coerced_to_utc_in_server_parsing(self) -> None:
        raw = "2026-05-20"
        exp = datetime.fromisoformat(raw)
        assert exp.tzinfo is None
        exp = exp.replace(tzinfo=UTC)
        assert exp.tzinfo is UTC


class TestPlanRecord:
    def test_l0_uses_active_ref(self) -> None:
        from ambara.core.changes import plan_record
        from ambara.core.schema import EntryType

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
        assert "ambara/active/test-client/sprint-goal" in intent.branch

    def test_l1_uses_lightweight_pr(self) -> None:
        from ambara.core.changes import plan_record
        from ambara.core.schema import EntryType

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
        from ambara.core.changes import plan_record
        from ambara.core.schema import EntryType

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
        from ambara.core.changes import plan_propose
        from ambara.core.schema import EntryType

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
        from ambara.core.changes import plan_propose
        from ambara.core.schema import EntryType

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
    @patch("ambara.server.cleanup_branch")
    @patch("ambara.server.push_active_ref")
    @patch("ambara.server.materialize_write", return_value="abc123")
    @patch("ambara.server.create_branch")
    def test_sequence(self, mock_create, mock_write, mock_push, mock_cleanup) -> None:
        intent = WriteIntent(
            path="active/sprint.md",
            content="content",
            branch="ambara/active/client/sprint",
            write_mode="active_ref",
            entry_id="sprint",
            level=EscalationLevel.L0,
        )
        lock = threading.Lock()
        sha = _do_active_record(lock, "/repo", intent, "main")
        assert sha == "abc123"
        mock_create.assert_called_once()
        mock_write.assert_called_once()
        mock_push.assert_called_once_with("/repo", "ambara/active/client/sprint", "abc123")
        mock_cleanup.assert_called_once()

    @patch("ambara.server.cleanup_branch")
    @patch("ambara.server.push_active_ref", side_effect=RuntimeError("push failed"))
    @patch("ambara.server.materialize_write", return_value="abc123")
    @patch("ambara.server.create_branch")
    def test_cleanup_runs_when_active_push_fails(
        self, mock_create, mock_write, mock_push, mock_cleanup
    ) -> None:
        intent = WriteIntent(
            path="active/sprint.md",
            content="content",
            branch="ambara/active/client/sprint",
            write_mode="active_ref",
            entry_id="sprint",
            level=EscalationLevel.L0,
        )
        lock = threading.Lock()

        with pytest.raises(RuntimeError, match="push failed"):
            _do_active_record(lock, "/repo", intent, "main")

        mock_create.assert_called_once()
        mock_write.assert_called_once()
        mock_push.assert_called_once_with("/repo", "ambara/active/client/sprint", "abc123")
        mock_cleanup.assert_called_once_with("/repo", "ambara/active/client/sprint", "main")


class TestFinishPrWrite:
    @patch("ambara.server.create_pr")
    @patch("ambara.server.push_branch")
    @patch("ambara.server.materialize_write", return_value="sha123")
    @patch("ambara.server.create_branch")
    @patch("ambara.server.cleanup_branch")
    def test_serialized_lifecycle(
        self, mock_cleanup, mock_create_branch, mock_write, mock_push, mock_create_pr
    ) -> None:
        from ambara.git.auth import AuthCandidate
        from ambara.git.pr import PRResult

        winning = AuthCandidate(
            method="api_token",
            source="env_ambara",
            owner="owner",
            repo="repo",
        )
        mock_create_pr.return_value = (
            PRResult(
                url="https://github.com/o/r/pull/1",
                number=1,
                branch="ambara/proj",
                kind="pr",
            ),
            winning,
        )
        intent = WriteIntent(
            path="projects/proj.md",
            content="content",
            branch="ambara/proj",
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
            labels=["ambara", "low-ceremony"],
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

    @patch("ambara.server.create_pr")
    @patch("ambara.server.push_branch")
    @patch("ambara.server.materialize_write", return_value="sha456")
    @patch("ambara.server.create_branch")
    @patch("ambara.server.cleanup_branch")
    def test_cleanup_runs_on_pr_failure(
        self, mock_cleanup, mock_create_branch, mock_write, mock_push, mock_create_pr
    ) -> None:
        from ambara.git.pr import PRResult

        mock_create_pr.return_value = (
            PRResult(
                url=None,
                number=None,
                branch="ambara/proj",
                kind="branch",
            ),
            None,
        )
        intent = WriteIntent(
            path="projects/proj.md",
            content="content",
            branch="ambara/proj",
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

    @patch("ambara.server.create_pr")
    @patch("ambara.server.push_branch")
    @patch("ambara.server.materialize_expire", return_value="sha789")
    @patch("ambara.server.create_branch")
    @patch("ambara.server.cleanup_branch")
    def test_expire_intent_uses_materialize_expire(
        self, mock_cleanup, mock_create_branch, mock_expire, mock_push, mock_create_pr
    ) -> None:
        from ambara.git.pr import PRResult

        mock_create_pr.return_value = (
            PRResult(
                url="https://github.com/o/r/pull/3",
                number=3,
                branch="ambara/expire-old",
                kind="pr",
            ),
            None,
        )
        intent = ExpireIntent(
            entry_id="old-dec",
            path="decisions/old-dec.md",
            write_mode="review_pr",
            branch="ambara/expire-old",
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
            labels=["ambara", "review-required"],
            base="main",
            remote_url="git@github.com:owner/repo.git",
            cached_candidate=None,
            now=now,
        )
        assert sha == "sha789"
        mock_expire.assert_called_once_with("/repo", intent, now)

    @patch("ambara.server.create_pr")
    @patch("ambara.server.push_branch")
    @patch("ambara.server.materialize_write", return_value="sha000")
    @patch("ambara.server.create_branch")
    @patch("ambara.server.cleanup_branch")
    def test_non_github_remote_goes_branch_only(
        self, mock_cleanup, mock_create_branch, mock_write, mock_push, mock_create_pr
    ) -> None:
        from ambara.git.pr import PRResult

        mock_create_pr.return_value = (
            PRResult(
                url=None,
                number=None,
                branch="ambara/proj",
                kind="branch",
            ),
            None,
        )
        intent = WriteIntent(
            path="projects/proj.md",
            content="content",
            branch="ambara/proj",
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
