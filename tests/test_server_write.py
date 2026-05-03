"""Tests for jurati.server write tools (record, propose, expire)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from jurati.core.changes import WriteIntent
from jurati.core.schema import (
    EntryStatus,
    EntryType,
    EscalationLevel,
)
from jurati.server import (
    _do_active_record,
    _do_branch_record,
    _do_expire_branch,
)


class TestPlanRecord:
    def test_l0_uses_active_ref(self) -> None:
        from jurati.core.changes import plan_record

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


class TestDoBranchRecord:
    @patch("jurati.server.push_branch")
    @patch("jurati.server.materialize_write", return_value="def456")
    @patch("jurati.server.create_branch")
    def test_sequence(self, mock_create, mock_write, mock_push) -> None:
        intent = WriteIntent(
            path="projects/proj.md",
            content="content",
            branch="jurati/proj",
            write_mode="lightweight_pr",
            entry_id="proj",
            level=EscalationLevel.L1,
        )
        lock = threading.Lock()
        sha = _do_branch_record(lock, "/repo", intent, "main")
        assert sha == "def456"
        mock_create.assert_called_once()
        mock_write.assert_called_once()
        mock_push.assert_called_once_with("/repo", "jurati/proj")


class TestDoExpireBranch:
    @patch("jurati.server.push_branch")
    @patch("jurati.server.materialize_expire", return_value="ghi789")
    @patch("jurati.server.create_branch")
    def test_sequence(self, mock_create, mock_expire, mock_push) -> None:
        from jurati.core.changes import ExpireIntent

        intent = ExpireIntent(
            entry_id="old-dec",
            path="decisions/old-dec.md",
            write_mode="review_pr",
            branch="jurati/expire-old-dec",
            new_status=EntryStatus.EXPIRED,
        )
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        lock = threading.Lock()
        sha = _do_expire_branch(lock, "/repo", intent, now, "main")
        assert sha == "ghi789"
        mock_create.assert_called_once()
        mock_expire.assert_called_once()
        mock_push.assert_called_once()
