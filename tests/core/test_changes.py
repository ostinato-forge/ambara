from __future__ import annotations

import pytest

from jurati.core.changes import plan_expire, plan_propose, plan_record
from jurati.core.schema import EntryStatus, EntryType, EscalationLevel

from .conftest import BASE_NOW, make_entry, minutes_after


def test_plan_record_creates_l0_active_ref_intent() -> None:
    intent = plan_record(
        EntryType.ACTIVE,
        "Current Focus",
        "Working on Jurati tests.",
        entry_id="current-focus",
        now=BASE_NOW,
        expires_at=minutes_after(30),
        client="codex",
        projects=["jurati"],
        tags=["testing"],
    )

    assert intent.path == "active/current-focus.md"
    assert intent.branch == "jurati/active/codex/current-focus"
    assert intent.write_mode == "active_ref"
    assert "status: active" in intent.content
    assert "expires_at: 2026-05-02T12:30:00Z" in intent.content
    assert "Working on Jurati tests." in intent.content


def test_plan_record_rejects_active_without_expiry() -> None:
    with pytest.raises(ValueError, match="active records require expires_at"):
        plan_record(
            EntryType.ACTIVE,
            "Current Focus",
            "Working on Jurati tests.",
            entry_id="current-focus",
            now=BASE_NOW,
            client="codex",
        )


def test_plan_record_rejects_active_without_client() -> None:
    with pytest.raises(ValueError, match="L0 active records require a client slug"):
        plan_record(
            EntryType.ACTIVE,
            "Current Focus",
            "Working on Jurati tests.",
            entry_id="current-focus",
            now=BASE_NOW,
            expires_at=minutes_after(30),
        )


def test_plan_record_creates_l1_project_pr_intent() -> None:
    intent = plan_record(
        EntryType.PROJECT,
        "Jurati Test Baseline",
        "Core tests are in place.",
        entry_id="jurati-test-baseline",
        now=BASE_NOW,
    )

    assert intent.path == "projects/jurati-test-baseline.md"
    assert intent.branch == "jurati/jurati-test-baseline"
    assert intent.write_mode == "lightweight_pr"
    assert intent.level == EscalationLevel.L1
    assert "status: proposed" in intent.content
    assert "  required: true" in intent.content


def test_plan_record_rejects_high_stakes_content() -> None:
    with pytest.raises(ValueError, match=r"record\(\) cannot create L2 content"):
        plan_record(
            EntryType.WORKFLOW,
            "Review Workflow",
            "Do review.",
            entry_id="review-workflow",
            now=BASE_NOW,
        )


def test_plan_record_rejects_expiry_for_non_active_content() -> None:
    with pytest.raises(ValueError, match="only active records may set expires_at"):
        plan_record(
            EntryType.PROJECT,
            "Jurati Status",
            "Status.",
            entry_id="jurati-status",
            now=BASE_NOW,
            expires_at=minutes_after(30),
        )


def test_plan_propose_creates_review_pr_intent() -> None:
    intent = plan_propose(
        EntryType.PRINCIPLE,
        "Deterministic Core",
        "Core functions take explicit inputs.",
        entry_id="deterministic-core",
        now=BASE_NOW,
    )

    assert intent.path == "principles/deterministic-core.md"
    assert intent.branch == "jurati/deterministic-core"
    assert intent.write_mode == "review_pr"
    assert intent.level == EscalationLevel.L3
    assert "created_at: 2026-05-02T12:00:00Z" in intent.content


def test_plan_propose_rejects_low_stakes_content() -> None:
    with pytest.raises(ValueError, match=r"propose\(\) cannot create L1 content"):
        plan_propose(
            EntryType.PROJECT,
            "Project Status",
            "Status.",
            entry_id="project-status",
            now=BASE_NOW,
        )


def test_plan_expire_uses_active_ref_mode_for_l0() -> None:
    entry = make_entry(
        entry_id="current-focus",
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        expires_at=minutes_after(30),
        review_required=False,
    )

    intent = plan_expire(entry, now=minutes_after(31))

    assert intent.entry_id == "current-focus"
    assert intent.branch is None
    assert intent.write_mode == "active_ref"
    assert intent.new_status == EntryStatus.EXPIRED


def test_plan_expire_uses_branch_for_reviewed_content() -> None:
    entry = make_entry(entry_id="project-status")

    intent = plan_expire(entry, now=minutes_after(31))

    assert intent.branch == "jurati/expire-project-status"
    assert intent.write_mode == "lightweight_pr"
