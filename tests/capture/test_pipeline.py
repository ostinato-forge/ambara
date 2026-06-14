# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for ambara.capture.pipeline — end-to-end capture orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from ambara.capture import pipeline as cap
from ambara.capture.pipeline import run_capture
from ambara.core.schema import EscalationLevel
from ambara.git.remember import RememberOutcome


def _remember_outcome(*, sha: str, branch: str, entry_id: str) -> RememberOutcome:
    """Helper: RememberOutcome for the non-reuse (new write) path."""
    return RememberOutcome(
        entry_id=entry_id,
        branch=branch,
        sha=sha,
        reused_existing=False,
        receipt={"branch": branch, "sha": sha},
    )


def _reused_outcome(*, branch: str, entry_id: str) -> RememberOutcome:
    """Helper: RememberOutcome for the reuse (idempotent skip) path."""
    return RememberOutcome(
        entry_id=entry_id,
        branch=branch,
        sha=None,
        reused_existing=True,
        receipt={"reused_existing": True},
    )


class TestRunCapture:
    @patch(
        "ambara.capture.pipeline.materialize_remember",
        return_value=_remember_outcome(
            sha="abc123",
            branch="ambara/api-service/postgres-pool-at-20-max",
            entry_id="api-service-postgres-pool-at-20-max",
        ),
    )
    def test_l1_capture_creates_branch_and_pushes(self, mock_remember) -> None:
        outcome = run_capture(
            message="ambara: postgres pool at 20 max",
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
        mock_remember.assert_called_once()

    @patch(
        "ambara.capture.pipeline.materialize_remember",
        return_value=_reused_outcome(
            branch="ambara/api-service/postgres-pool-at-20-max",
            entry_id="api-service-postgres-pool-at-20-max",
        ),
    )
    def test_dedup_skips_when_entry_on_main(self, mock_remember) -> None:
        outcome = run_capture(
            message="ambara: postgres pool at 20 max",
            repo_slug="api-service",
            knowledge_repo_path="/knowledge",
            main_branch="main",
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            source_commit="abc123",
            source_author="dev@co.com",
        )
        assert outcome is None

    @patch(
        "ambara.capture.pipeline.materialize_remember",
        return_value=_reused_outcome(
            branch="ambara/api-service/postgres-pool-at-20-max",
            entry_id="api-service-postgres-pool-at-20-max",
        ),
    )
    def test_dedup_skips_when_branch_exists(self, mock_remember) -> None:
        outcome = run_capture(
            message="ambara: postgres pool at 20 max",
            repo_slug="api-service",
            knowledge_repo_path="/knowledge",
            main_branch="main",
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            source_commit="abc123",
            source_author="dev@co.com",
        )
        assert outcome is None

    def test_non_ambara_message_returns_none(self) -> None:
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

    @patch(
        "ambara.capture.pipeline.materialize_remember",
        return_value=_remember_outcome(
            sha="abc123",
            branch="ambara/api-service/reach-jane-example-com-for-deploy-access",
            entry_id="api-service-reach-jane-example-com-for-deploy-access",
        ),
    )
    def test_review_policy_escalates_l1_capture_to_l2(self, mock_remember) -> None:
        outcome = run_capture(
            message="ambara: reach jane@example.com for deploy access",
            repo_slug="api-service",
            knowledge_repo_path="/knowledge",
            main_branch="main",
            now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
            source_commit="abc123",
            source_author="dev@co.com",
        )
        assert outcome is not None
        assert outcome.level == EscalationLevel.L2
        assert outcome.content_policy_action == "require_review"
        assert "pii.email" in outcome.content_policy_rules

    def test_block_policy_rejects_capture(self) -> None:
        with pytest.raises(ValueError, match="Content blocked by policy"):
            run_capture(
                message="ambara: token ghp_abcdefghijklmnopqrstuvwxyz123456 leaked",
                repo_slug="api-service",
                knowledge_repo_path="/knowledge",
                main_branch="main",
                now=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
                source_commit="abc123",
                source_author="dev@co.com",
            )


def test_run_capture_returns_none_when_remember_reuses(monkeypatch) -> None:
    monkeypatch.setattr(cap, "_load_index_entries", lambda *a, **k: [])
    monkeypatch.setattr(
        cap,
        "materialize_remember",
        lambda *a, **k: RememberOutcome(
            entry_id="repo-x-use-grpc",
            branch="ambara/repo/use-grpc",
            sha=None,
            reused_existing=True,
            receipt={},
        ),
    )
    out = cap.run_capture(
        message="ambara(decision): Use gRPC\n\nbody",
        repo_slug="repo",
        knowledge_repo_path="/k",
        main_branch="main",
        now=datetime(2026, 6, 1, tzinfo=UTC),
        source_commit="a" * 40,
        source_author="dev",
    )
    assert out is None  # reuse => skip, same as old entry_exists/branch_exists path
