"""Tests for jurati.capture.pipeline — end-to-end capture orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from jurati.capture.pipeline import (
    run_capture,
)
from jurati.core.schema import EscalationLevel


class TestRunCapture:
    @patch("jurati.capture.pipeline.push_branch_with_retry")
    @patch("jurati.capture.pipeline.materialize_write", return_value="abc123")
    @patch("jurati.capture.pipeline.create_branch")
    @patch("jurati.capture.pipeline.entry_exists_on_main", return_value=False)
    @patch("jurati.capture.pipeline.branch_exists_remote", return_value=False)
    def test_l1_capture_creates_branch_and_pushes(
        self,
        mock_branch_check,
        mock_entry_check,
        mock_create,
        mock_write,
        mock_push,
    ) -> None:
        outcome = run_capture(
            message="jurati: postgres pool at 20 max",
            repo_slug="api-service",
            knowledge_repo_path="/knowledge",
            main_branch="main",
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            source_commit="abc123",
            source_author="dev@co.com",
        )
        assert outcome is not None
        assert outcome.entry_id == "api-service-postgres-pool-at-20-max"
        assert outcome.level == EscalationLevel.L1
        assert outcome.sha == "abc123"
        assert outcome.contradiction_ids == []
        mock_create.assert_called_once()
        mock_write.assert_called_once()
        intent = mock_write.call_args.args[1]
        assert intent.event is not None
        assert intent.event.entry_id == "api-service-postgres-pool-at-20-max"
        mock_push.assert_called_once()

    @patch("jurati.capture.pipeline.entry_exists_on_main", return_value=True)
    def test_dedup_skips_when_entry_on_main(self, mock_check) -> None:
        outcome = run_capture(
            message="jurati: postgres pool at 20 max",
            repo_slug="api-service",
            knowledge_repo_path="/knowledge",
            main_branch="main",
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            source_commit="abc123",
            source_author="dev@co.com",
        )
        assert outcome is None

    @patch("jurati.capture.pipeline.entry_exists_on_main", return_value=False)
    @patch("jurati.capture.pipeline.branch_exists_remote", return_value=True)
    def test_dedup_skips_when_branch_exists(self, mock_branch, mock_entry) -> None:
        outcome = run_capture(
            message="jurati: postgres pool at 20 max",
            repo_slug="api-service",
            knowledge_repo_path="/knowledge",
            main_branch="main",
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            source_commit="abc123",
            source_author="dev@co.com",
        )
        assert outcome is None

    def test_non_jurati_message_returns_none(self) -> None:
        outcome = run_capture(
            message="feat: add new feature",
            repo_slug="api-service",
            knowledge_repo_path="/knowledge",
            main_branch="main",
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            source_commit="abc123",
            source_author="dev@co.com",
        )
        assert outcome is None
