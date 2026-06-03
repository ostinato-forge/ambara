from __future__ import annotations

import frontmatter
import pytest

from ambara.core.changes import plan_capture, plan_expire, plan_propose, plan_record
from ambara.core.events import EventType
from ambara.core.schema import EntryStatus, EntryType, EscalationLevel, SourceMeta, Visibility

from .conftest import BASE_NOW, make_entry, minutes_after


def test_plan_record_creates_l0_active_ref_intent() -> None:
    intent = plan_record(
        EntryType.ACTIVE,
        "Current Focus",
        "Working on Ambara tests.",
        entry_id="current-focus",
        now=BASE_NOW,
        expires_at=minutes_after(30),
        client="codex",
        projects=["ambara"],
        tags=["testing"],
    )

    assert intent.path == "active/current-focus.md"
    assert intent.branch == "ambara/active/codex/current-focus"
    assert intent.write_mode == "active_ref"
    metadata = frontmatter.loads(intent.content).metadata
    assert metadata["status"] == "active"
    assert metadata["expires_at"] == "2026-05-02T12:30:00Z"
    assert "Working on Ambara tests." in intent.content


def test_plan_record_rejects_active_without_expiry() -> None:
    with pytest.raises(ValueError, match="active records require expires_at"):
        plan_record(
            EntryType.ACTIVE,
            "Current Focus",
            "Working on Ambara tests.",
            entry_id="current-focus",
            now=BASE_NOW,
            client="codex",
        )


def test_plan_record_rejects_active_without_client() -> None:
    with pytest.raises(ValueError, match="L0 active records require a client slug"):
        plan_record(
            EntryType.ACTIVE,
            "Current Focus",
            "Working on Ambara tests.",
            entry_id="current-focus",
            now=BASE_NOW,
            expires_at=minutes_after(30),
        )


def test_plan_record_creates_l1_project_pr_intent() -> None:
    intent = plan_record(
        EntryType.PROJECT,
        "Ambara Test Baseline",
        "Core tests are in place.",
        entry_id="ambara-test-baseline",
        now=BASE_NOW,
    )

    assert intent.path == "projects/ambara-test-baseline.md"
    assert intent.branch == "ambara/ambara-test-baseline"
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
            "Ambara Status",
            "Status.",
            entry_id="ambara-status",
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
    assert intent.branch == "ambara/deterministic-core"
    assert intent.write_mode == "review_pr"
    assert intent.level == EscalationLevel.L3
    assert frontmatter.loads(intent.content).metadata["created_at"] == "2026-05-02T12:00:00Z"


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

    intent = plan_expire(entry, now=BASE_NOW)

    assert intent.entry_id == "current-focus"
    assert intent.branch is None
    assert intent.write_mode == "active_ref"
    assert intent.new_status == EntryStatus.EXPIRED


def test_plan_expire_uses_branch_for_reviewed_content() -> None:
    entry = make_entry(entry_id="project-status")

    intent = plan_expire(entry, now=BASE_NOW)

    assert intent.branch == "ambara/expire-project-status"
    assert intent.write_mode == "lightweight_pr"


def test_plan_capture_creates_l1_project_intent() -> None:
    intent = plan_capture(
        entry_type=EntryType.PROJECT,
        title="postgres pool at 20 max",
        body="We hit OOM on staging.",
        entry_id="api-service-postgres-pool-at-20-max",
        level=EscalationLevel.L1,
        now=BASE_NOW,
        source=SourceMeta(repo="api-service", commit="abc123", author="dev@co.com"),
    )

    assert intent.path == "projects/api-service-postgres-pool-at-20-max.md"
    assert intent.branch == "ambara/api-service/postgres-pool-at-20-max"
    assert intent.write_mode == "lightweight_pr"
    assert intent.level == EscalationLevel.L1
    assert intent.event is not None
    assert intent.event.event_type == EventType.ENTRY_PROPOSED
    assert intent.event.entry_id == "api-service-postgres-pool-at-20-max"
    assert "source:" in intent.content
    assert "repo: api-service" in intent.content
    assert "We hit OOM on staging." in intent.content


def test_plan_capture_creates_l2_decision_intent() -> None:
    intent = plan_capture(
        entry_type=EntryType.DECISION,
        title="switch to gRPC",
        body="Faster inter-service calls.",
        entry_id="api-service-switch-to-grpc",
        level=EscalationLevel.L2,
        now=BASE_NOW,
        source=SourceMeta(repo="api-service", commit="def456", author="dev@co.com"),
    )

    assert intent.path == "decisions/api-service-switch-to-grpc.md"
    assert intent.write_mode == "review_pr"
    assert intent.level == EscalationLevel.L2
    assert intent.event is not None
    assert intent.event.event_type == EventType.ENTRY_PROPOSED


def test_plan_capture_branch_uses_repo_slug_namespace() -> None:
    intent = plan_capture(
        entry_type=EntryType.PROJECT,
        title="fix auth timeout",
        entry_id="frontend-fix-auth-timeout",
        level=EscalationLevel.L1,
        now=BASE_NOW,
        source=SourceMeta(repo="frontend", commit="ghi789", author="dev@co.com"),
    )

    assert intent.branch == "ambara/frontend/fix-auth-timeout"


def test_plan_capture_without_source() -> None:
    intent = plan_capture(
        entry_type=EntryType.PROJECT,
        title="manual note",
        entry_id="manual-note",
        level=EscalationLevel.L1,
        now=BASE_NOW,
    )

    assert "source:" not in intent.content


def test_rendered_frontmatter_round_trips_edge_values() -> None:
    title = 'Quote: "pool:20"'
    body = 'Line 1\nLine: 2\nQuoted: "value"'
    intent = plan_capture(
        entry_type=EntryType.PROJECT,
        title=title,
        body=body,
        entry_id="api-service-quote-pool-20",
        level=EscalationLevel.L1,
        now=BASE_NOW,
        source=SourceMeta(repo="api:service", commit="abc:def", author="dev+test@co.com"),
    )

    post = frontmatter.loads(intent.content)

    assert post.metadata["title"] == title
    assert post.metadata["source"] == {
        "repo": "api:service",
        "commit": "abc:def",
    }
    assert post.content == body


def test_rendered_frontmatter_round_trips_multiline_metadata() -> None:
    title = "Line one\nLine: two"
    intent = plan_capture(
        entry_type=EntryType.PROJECT,
        title=title,
        body="Body.",
        entry_id="api-service-multiline-title",
        level=EscalationLevel.L1,
        now=BASE_NOW,
    )

    post = frontmatter.loads(intent.content)

    assert post.metadata["title"] == title


def test_plan_record_l0_intent_carries_entry() -> None:
    intent = plan_record(
        EntryType.ACTIVE,
        "Sprint goal",
        "Ship v1 by Friday.",
        entry_id="sprint-goal",
        now=BASE_NOW,
        expires_at=minutes_after(1440),
        client="test-client",
    )

    assert intent.entry is not None
    assert intent.entry.frontmatter.id == "sprint-goal"
    assert intent.entry.frontmatter.title == "Sprint goal"
    assert intent.entry.frontmatter.type == EntryType.ACTIVE
    assert intent.entry.frontmatter.level == EscalationLevel.L0
    assert intent.entry.frontmatter.status == EntryStatus.ACTIVE
    assert intent.entry.body == "Ship v1 by Friday."
    assert intent.entry.path == "active/sprint-goal.md"


def test_plan_record_l1_intent_carries_entry() -> None:
    intent = plan_record(
        EntryType.PROJECT,
        "New project",
        "Project body.",
        entry_id="new-project",
        now=BASE_NOW,
    )

    assert intent.entry is not None
    assert intent.entry.frontmatter.id == "new-project"
    assert intent.entry.frontmatter.status == EntryStatus.PROPOSED
    assert intent.entry.frontmatter.level == EscalationLevel.L1


def test_plan_propose_intent_carries_entry() -> None:
    intent = plan_propose(
        EntryType.DECISION,
        "Use git for KB",
        "Git-backed storage.",
        entry_id="use-git-for-kb",
        now=BASE_NOW,
    )

    assert intent.entry is not None
    assert intent.entry.frontmatter.id == "use-git-for-kb"
    assert intent.entry.frontmatter.status == EntryStatus.PROPOSED
    assert intent.entry.frontmatter.level == EscalationLevel.L2


class TestVisibilityInWriteIntents:
    def test_plan_record_l0_forces_visibility_internal(self) -> None:
        intent = plan_record(
            EntryType.ACTIVE,
            "Focus",
            "Working.",
            entry_id="focus-test",
            now=BASE_NOW,
            expires_at=minutes_after(30),
            client="codex",
            visibility=Visibility.EXTERNAL,
        )
        assert intent.entry is not None
        assert intent.entry.frontmatter.visibility == Visibility.INTERNAL

    def test_plan_record_l1_defaults_visibility_to_internal(self) -> None:
        intent = plan_record(
            EntryType.PROJECT,
            "Project",
            "Status.",
            entry_id="project-viz-test",
            now=BASE_NOW,
        )
        assert intent.entry is not None
        assert intent.entry.frontmatter.visibility == Visibility.INTERNAL

    def test_plan_record_l1_accepts_explicit_external(self) -> None:
        intent = plan_record(
            EntryType.PROJECT,
            "Public Project",
            "Status.",
            entry_id="public-project",
            now=BASE_NOW,
            visibility=Visibility.EXTERNAL,
        )
        assert intent.entry is not None
        assert intent.entry.frontmatter.visibility == Visibility.EXTERNAL

    def test_plan_propose_defaults_visibility_to_external(self) -> None:
        intent = plan_propose(
            EntryType.DECISION,
            "Team Decision",
            "We decided.",
            entry_id="team-decision-viz",
            now=BASE_NOW,
        )
        assert intent.entry is not None
        assert intent.entry.frontmatter.visibility == Visibility.EXTERNAL

    def test_plan_propose_accepts_explicit_internal(self) -> None:
        intent = plan_propose(
            EntryType.DECISION,
            "Internal Decision",
            "Private.",
            entry_id="internal-decision",
            now=BASE_NOW,
            visibility=Visibility.INTERNAL,
        )
        assert intent.entry is not None
        assert intent.entry.frontmatter.visibility == Visibility.INTERNAL


class TestRecordedByInWriteIntents:
    def test_plan_record_populates_recorded_by(self) -> None:
        intent = plan_record(
            EntryType.PROJECT,
            "Tracked",
            "Body.",
            entry_id="tracked-test",
            now=BASE_NOW,
            client="test-client",
        )
        assert intent.entry is not None
        assert intent.entry.frontmatter.recorded_by is not None
        assert intent.entry.frontmatter.recorded_by.client == "test-client"

    def test_plan_record_no_client_no_recorded_by(self) -> None:
        intent = plan_record(
            EntryType.PROJECT,
            "No client",
            "Body.",
            entry_id="no-client",
            now=BASE_NOW,
        )
        assert intent.entry is not None
        assert intent.entry.frontmatter.recorded_by is None

    def test_plan_propose_populates_recorded_by(self) -> None:
        intent = plan_propose(
            EntryType.DECISION,
            "Decision",
            "Body.",
            entry_id="propose-rb-test",
            now=BASE_NOW,
            client="cursor",
        )
        assert intent.entry is not None
        assert intent.entry.frontmatter.recorded_by is not None
        assert intent.entry.frontmatter.recorded_by.client == "cursor"


class TestRenderingNewFields:
    def test_plan_record_renders_visibility(self) -> None:
        intent = plan_record(
            EntryType.PROJECT,
            "Rendered",
            "Body.",
            entry_id="rendered-viz",
            now=BASE_NOW,
        )
        assert "visibility: internal" in intent.content

    def test_plan_record_renders_recorded_by(self) -> None:
        intent = plan_record(
            EntryType.PROJECT,
            "Rendered RB",
            "Body.",
            entry_id="rendered-rb",
            now=BASE_NOW,
            client="cursor",
        )
        assert "recorded_by:" in intent.content
        assert "client: cursor" in intent.content

    def test_plan_propose_renders_external_visibility(self) -> None:
        intent = plan_propose(
            EntryType.DECISION,
            "Rendered Propose",
            "Body.",
            entry_id="rendered-propose-viz",
            now=BASE_NOW,
        )
        assert "visibility: external" in intent.content


class TestEventOnWriteIntent:
    def test_plan_record_l1_produces_event(self) -> None:
        intent = plan_record(
            EntryType.PROJECT,
            "Event Test",
            "Body.",
            entry_id="event-test",
            now=BASE_NOW,
        )
        assert intent.event is not None
        assert intent.event.event_type == EventType.ENTRY_PROPOSED
        assert intent.event.entry_id == "event-test"
        assert intent.event.entry_type == "project"
        assert intent.event.level == "L1"

    def test_plan_record_l0_produces_no_event(self) -> None:
        intent = plan_record(
            EntryType.ACTIVE,
            "L0 No Event",
            "Body.",
            entry_id="l0-no-event",
            now=BASE_NOW,
            expires_at=minutes_after(30),
            client="test",
        )
        assert intent.event is None

    def test_plan_propose_produces_event(self) -> None:
        intent = plan_propose(
            EntryType.DECISION,
            "Propose Event",
            "Body.",
            entry_id="propose-event",
            now=BASE_NOW,
        )
        assert intent.event is not None
        assert intent.event.event_type == EventType.ENTRY_PROPOSED
        assert intent.event.level == "L2"
        assert intent.event.visibility == "external"


class TestEventOnExpireIntent:
    def test_plan_expire_produces_event_for_l1(self) -> None:
        entry = make_entry(entry_id="expire-event-test")
        intent = plan_expire(entry, now=BASE_NOW)
        assert intent.event is not None
        assert intent.event.event_type == EventType.ENTRY_EXPIRED
        assert intent.event.entry_id == "expire-event-test"
        assert intent.event.timestamp == BASE_NOW

    def test_plan_expire_produces_no_event_for_l0(self) -> None:
        entry = make_entry(
            entry_id="l0-expire",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            expires_at=minutes_after(30),
            review_required=False,
        )
        intent = plan_expire(entry, now=BASE_NOW)
        assert intent.event is None
