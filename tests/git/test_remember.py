# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti
"""Tests for git/remember.materialize_remember (idempotent review-branch writer)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from ambara.core.content_policy import WritePolicy
from ambara.core.content_policy_config import default_config
from ambara.core.remember import RememberCandidate, RememberPlan, plan_remember
from ambara.core.schema import EntryType, EscalationLevel
from ambara.git.remember import materialize_remember

NOW = datetime(2026, 6, 13, tzinfo=UTC)


def _create_plan() -> RememberPlan:
    cand = RememberCandidate(
        kind="promote",
        entry_id="github-7",
        title="Adopt gRPC",
        body="We will use gRPC for internal services.",
        entry_type=EntryType.PROJECT,
        requested_level=EscalationLevel.L1,
        branch_prefix="ambara/promote",
    )
    return plan_remember(
        cand, index_entries=[], content_policy=WritePolicy(default_config()), now=NOW
    )


@patch("ambara.git.remember.push_branch_with_retry")
@patch("ambara.git.remember.materialize_write", return_value="sha1")
@patch("ambara.git.remember.create_branch")
@patch("ambara.git.remember.branch_exists_remote", return_value=False)
@patch("ambara.git.remember.entry_exists_on_main", return_value=False)
def test_create_opens_branch_and_pushes(
    m_entry: object, m_branch: object, m_create: object, m_write: object, m_push: object
) -> None:
    outcome = materialize_remember("/kb", _create_plan(), main_branch="main")
    assert outcome.reused_existing is False
    assert outcome.sha == "sha1"
    assert outcome.branch == "ambara/promote/github-7"
    m_create.assert_called_once()  # type: ignore[attr-defined]
    m_write.assert_called_once()  # type: ignore[attr-defined]
    m_push.assert_called_once()  # type: ignore[attr-defined]
    assert outcome.receipt["sha"] == "sha1"
    assert outcome.receipt["branch"] == "ambara/promote/github-7"


@patch("ambara.git.remember.materialize_write")
@patch("ambara.git.remember.create_branch")
@patch("ambara.git.remember.branch_exists_remote", return_value=False)
@patch("ambara.git.remember.entry_exists_on_main", return_value=True)
def test_reused_when_entry_on_main(
    m_entry: object, m_branch: object, m_create: object, m_write: object
) -> None:
    outcome = materialize_remember("/kb", _create_plan(), main_branch="main")
    assert outcome.reused_existing is True
    assert outcome.sha is None
    m_create.assert_not_called()  # type: ignore[attr-defined]
    m_write.assert_not_called()  # type: ignore[attr-defined]


@patch("ambara.git.remember.materialize_write")
@patch("ambara.git.remember.create_branch")
@patch("ambara.git.remember.branch_exists_remote", return_value=True)
@patch("ambara.git.remember.entry_exists_on_main", return_value=False)
def test_reused_when_branch_exists(
    m_entry: object, m_branch: object, m_create: object, m_write: object
) -> None:
    outcome = materialize_remember("/kb", _create_plan(), main_branch="main")
    assert outcome.reused_existing is True
    m_create.assert_not_called()  # type: ignore[attr-defined]


def test_reject_plan_raises() -> None:
    cand = RememberCandidate(
        kind="promote",
        entry_id="github-8",
        title="leaky",
        body="-----BEGIN PRIVATE KEY-----",  # gitleaks:allow
        entry_type=EntryType.PROJECT,
        requested_level=EscalationLevel.L1,
        branch_prefix="ambara/promote",
    )
    plan = plan_remember(
        cand, index_entries=[], content_policy=WritePolicy(default_config()), now=NOW
    )
    assert plan.action == "reject"
    with pytest.raises(ValueError, match="create plan"):
        materialize_remember("/kb", plan, main_branch="main")
