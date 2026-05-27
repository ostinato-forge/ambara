from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jurati.core.context_compiler import (
    AvailabilityStatus,
    Constraint,
    ConstraintEffect,
    ConstraintKind,
    CoordinationStatus,
    EntryHandle,
    PacketVerdict,
    PlanningAction,
    compile_context_packet,
    constraints_from_context_payload,
    derive_freshness,
    derive_planning_state,
    planning_signature,
)

NOW = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)


def _freshness(age_seconds: int = 0):
    return derive_freshness(
        now=NOW,
        last_success=NOW - timedelta(seconds=age_seconds),
        warning_threshold_seconds=300,
        stale_threshold_seconds=900,
    )


def _constraint(
    effect: ConstraintEffect,
    *,
    kind: ConstraintKind = ConstraintKind.COORDINATION,
    source_ref: str | None = "signal:https://github.com/org/api/pull/42",
    entry_ref: str | None = None,
    read_hint: str | None = "context(mode='full') for full coordination evidence",
) -> Constraint:
    return Constraint(
        kind=kind,
        effect=effect,
        summary=f"{effect} constraint",
        source_ref=source_ref,
        entry_ref=entry_ref,
        read_hint=read_hint,
    )


class TestFreshness:
    def test_freshness_axes(self) -> None:
        assert _freshness(0).status == AvailabilityStatus.FRESH
        assert _freshness(300).status == AvailabilityStatus.ACCEPTABLE
        assert _freshness(900).status == AvailabilityStatus.STALE

    def test_missing_baseline_is_unavailable(self) -> None:
        freshness = derive_freshness(
            now=NOW,
            last_success=None,
            warning_threshold_seconds=300,
            stale_threshold_seconds=900,
            last_failure=NOW,
            last_error="Repository unavailable",
            consecutive_failures=2,
        )

        state = derive_planning_state(freshness, ())

        assert freshness.status == AvailabilityStatus.UNAVAILABLE
        assert state.verdict == PacketVerdict.CONTEXT_UNAVAILABLE
        assert state.action == PlanningAction.STOP_CONTEXT_UNAVAILABLE

    def test_invalid_thresholds_fail_closed(self) -> None:
        with pytest.raises(ValueError, match="stale_threshold_seconds"):
            derive_freshness(
                now=NOW,
                last_success=NOW,
                warning_threshold_seconds=300,
                stale_threshold_seconds=300,
            )


class TestPlanningActions:
    def test_no_constraints_proceeds(self) -> None:
        state = derive_planning_state(_freshness(), ())

        assert state.coordination == CoordinationStatus.CLEAR
        assert state.verdict == PacketVerdict.CLEAR
        assert state.action == PlanningAction.PROCEED

    def test_notice_constraint_proceeds_with_caution(self) -> None:
        state = derive_planning_state(
            _freshness(),
            (_constraint(ConstraintEffect.NOTICE),),
        )

        assert state.coordination == CoordinationStatus.CAUTION
        assert state.verdict == PacketVerdict.CAUTION
        assert state.action == PlanningAction.PROCEED_WITH_CAUTION

    def test_verify_constraint_requires_read_or_verify(self) -> None:
        state = derive_planning_state(
            _freshness(),
            (
                _constraint(
                    ConstraintEffect.VERIFY_BEFORE_RELYING,
                    kind=ConstraintKind.CURATION,
                    source_ref=None,
                    entry_ref="entry:token-decision",
                    read_hint="read(id='token-decision') for full body",
                ),
            ),
        )

        assert state.action == PlanningAction.READ_OR_VERIFY_BEFORE_ACTING
        assert state.read_handles == ("read(id='token-decision') for full body",)

    def test_revise_constraint_revises_plan(self) -> None:
        state = derive_planning_state(
            _freshness(),
            (_constraint(ConstraintEffect.REVISE),),
        )

        assert state.action == PlanningAction.REVISE_PLAN_BEFORE_ACTING

    def test_pause_constraint_blocks_even_when_not_stale(self) -> None:
        state = derive_planning_state(
            _freshness(),
            (_constraint(ConstraintEffect.PAUSE),),
        )

        assert state.coordination == CoordinationStatus.BLOCKED
        assert state.verdict == PacketVerdict.BLOCKED
        assert state.action == PlanningAction.PAUSE

    def test_stale_preserves_blocked_axis_but_public_verdict_is_stale(self) -> None:
        state = derive_planning_state(
            _freshness(age_seconds=1200),
            (_constraint(ConstraintEffect.PAUSE),),
        )

        assert state.coordination == CoordinationStatus.BLOCKED
        assert state.verdict == PacketVerdict.STALE
        assert state.action == PlanningAction.STOP_OR_REQUEST_REFRESH
        assert len(state.blocking_constraints) == 1


class TestPacketRendering:
    def test_compiler_packet_exposes_axes_and_handles(self) -> None:
        freshness = _freshness()
        constraints = (
            _constraint(
                ConstraintEffect.VERIFY_BEFORE_RELYING,
                kind=ConstraintKind.CURATION,
                source_ref=None,
                entry_ref="entry:token-decision",
                read_hint="read(id='token-decision') for full body",
            ),
        )
        entries = (
            EntryHandle(
                id="auth-handoff",
                title="Auth handoff",
                type="active",
                summary="Backend token work is in progress.",
                read_hint="read(id='auth-handoff') for full body",
            ),
        )

        packet = compile_context_packet(
            summary="Auth work needs verification before edits.",
            freshness=freshness,
            constraints=constraints,
            relevant_entries=entries,
            coverage={"entries_returned": 1, "bodies_omitted": 1},
        )

        assert packet["context_schema"] == "compiler-v1"
        assert packet["verdict"] == "caution"
        assert packet["planning_action"] == "read_or_verify_before_acting"
        assert packet["constraints"][0]["entry_ref"] == "entry:token-decision"
        assert packet["relevant_entries"][0]["read_hint"] == "read(id='auth-handoff') for full body"
        assert packet["freshness"]["status"] == "fresh"
        assert packet["coverage"]["bodies_omitted"] == 1


class TestStructuralEquivalence:
    def test_full_and_compact_payloads_have_same_planning_signature(self) -> None:
        full_payload = {
            "coordination": {
                "status": "ok",
                "summary": "A PR blocks token work.",
                "guidance": [
                    {
                        "effect": "pause",
                        "summary": "Auth PR blocks token work.",
                        "instruction": "Pause edits in src/auth.",
                        "evidence": [
                            {
                                "repo": "org/api",
                                "url": "https://github.com/org/api/pull/42",
                                "body_excerpt": "Long untrusted body excerpt.",
                            }
                        ],
                    }
                ],
            },
            "curation": {
                "status": "ok",
                "summary": "Two advisories need attention.",
                "expired_active": [
                    {
                        "id": "old-handoff",
                        "title": "Old handoff",
                        "reason": "Expired yesterday.",
                        "agent_instruction": "Treat this active context as expired.",
                    }
                ],
                "revalidation_due": [
                    {
                        "id": "token-decision",
                        "title": "Token decision",
                        "reason": "Past review_after.",
                        "agent_instruction": "Revalidate before relying on this.",
                    }
                ],
                "completed_artifact_revalidation": [],
            },
        }
        compact_payload = {
            "coordination": {
                "status": "ok",
                "summary": "A PR blocks token work.",
                "guidance": [
                    {
                        "effect": "pause",
                        "summary": "Auth PR blocks token work.",
                        "source": "org/api",
                        "evidence_urls": ["https://github.com/org/api/pull/42"],
                    }
                ],
            },
            "curation": {
                "status": "ok",
                "summary": "Two advisories need attention.",
                "expired_active": [
                    {
                        "id": "old-handoff",
                        "title": "Old handoff",
                        "reason": "Expired yesterday.",
                        "effect": "verify_before_relying",
                        "planning_constraint": "Do not rely unless current repo state confirms it.",
                        "read_hint": "read(id='old-handoff') for full body",
                    }
                ],
                "revalidation_due": [
                    {
                        "id": "token-decision",
                        "title": "Token decision",
                        "reason": "Past review_after.",
                        "effect": "verify_before_relying",
                        "planning_constraint": "Verify this entry before relying on it.",
                        "read_hint": "read(id='token-decision') for full body",
                    }
                ],
                "completed_artifact_revalidation": [],
            },
        }

        full_constraints = constraints_from_context_payload(full_payload)
        compact_constraints = constraints_from_context_payload(compact_payload)

        assert planning_signature(_freshness(), full_constraints) == planning_signature(
            _freshness(), compact_constraints
        )

    def test_unavailable_context_has_distinct_signature_from_empty_clear_context(self) -> None:
        unavailable = derive_freshness(
            now=NOW,
            last_success=None,
            warning_threshold_seconds=300,
            stale_threshold_seconds=900,
        )

        assert planning_signature(unavailable, ()) != planning_signature(_freshness(), ())
