# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ambara.core.context_compiler import (
    AvailabilityStatus,
    Constraint,
    ConstraintEffect,
    ConstraintKind,
    CoordinationStatus,
    EntryHandle,
    PacketVerdict,
    PlanningAction,
    compile_context_packet,
    constraints_from_compiler_packet,
    constraints_from_context_payload,
    constraints_from_coordination_payload,
    constraints_from_curation_payload,
    derive_freshness,
    derive_planning_state,
    entry_handles_from_compiler_packet,
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

    def test_unavailable_coordination_payload_requires_verification(self) -> None:
        constraints = constraints_from_coordination_payload(
            {
                "status": "unavailable",
                "summary": "Configured source inputs are unavailable.",
                "agent_instruction": (
                    "Do not treat the absence of coordination source inputs as a green light."
                ),
            }
        )

        state = derive_planning_state(_freshness(), constraints)

        assert constraints[0].kind == ConstraintKind.COORDINATION
        assert constraints[0].effect == ConstraintEffect.VERIFY_BEFORE_RELYING
        assert state.coordination == CoordinationStatus.CAUTION
        assert state.verdict == PacketVerdict.CAUTION
        assert state.action == PlanningAction.READ_OR_VERIFY_BEFORE_ACTING

    def test_unavailable_curation_payload_requires_verification(self) -> None:
        constraints = constraints_from_curation_payload(
            {
                "status": "unavailable",
                "summary": "Configured signal sources are unavailable for curation checks.",
                "agent_instruction": (
                    "Do not treat missing signal-derived curation as a clean result."
                ),
            }
        )

        state = derive_planning_state(_freshness(), constraints)

        assert constraints[0].kind == ConstraintKind.CURATION
        assert constraints[0].effect == ConstraintEffect.VERIFY_BEFORE_RELYING
        assert state.action == PlanningAction.READ_OR_VERIFY_BEFORE_ACTING


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


class TestThresholdValidation:
    def test_negative_warning_threshold_rejected(self) -> None:
        with pytest.raises(ValueError, match="warning_threshold_seconds must be >= 0"):
            derive_freshness(
                now=NOW,
                last_success=NOW,
                warning_threshold_seconds=-1,
                stale_threshold_seconds=900,
            )


class TestCoordinationPayloadParsing:
    def test_status_other_than_ok_or_unavailable_yields_no_constraints(self) -> None:
        assert constraints_from_coordination_payload({"status": "degraded"}) == ()

    def test_non_iterable_guidance_yields_no_constraints(self) -> None:
        assert constraints_from_coordination_payload({"status": "ok", "guidance": 7}) == ()

    def test_string_guidance_is_not_treated_as_items(self) -> None:
        assert constraints_from_coordination_payload({"status": "ok", "guidance": "pause"}) == ()

    def test_non_mapping_guidance_items_are_skipped(self) -> None:
        constraints = constraints_from_coordination_payload(
            {
                "status": "ok",
                "guidance": [
                    "ignored-string",
                    {"effect": "pause", "summary": "Real coordination item.", "source": "org/api"},
                ],
            }
        )
        assert len(constraints) == 1
        assert constraints[0].effect == ConstraintEffect.PAUSE
        assert constraints[0].source_ref == "signal:org/api"

    def test_explicit_source_ref_and_read_hint_win_over_derivation(self) -> None:
        constraints = constraints_from_coordination_payload(
            {
                "status": "ok",
                "guidance": [
                    {
                        "effect": "revise",
                        "summary": "Plan-affecting change.",
                        "source_ref": "explicit:ref-1",
                        "read_hint": "explicit read hint",
                        "evidence_urls": ["https://github.com/org/api/pull/9"],
                    }
                ],
            }
        )
        assert constraints[0].source_ref == "explicit:ref-1"
        assert constraints[0].read_hint == "explicit read hint"

    def test_source_ref_is_none_when_no_source_signals_present(self) -> None:
        constraints = constraints_from_coordination_payload(
            {
                "status": "ok",
                "guidance": [{"effect": "notice", "summary": "Bare notice with no refs."}],
            }
        )
        assert constraints[0].source_ref is None
        assert constraints[0].read_hint is None

    def test_guidance_without_summary_keys_uses_default_summary(self) -> None:
        constraints = constraints_from_coordination_payload(
            {"status": "ok", "guidance": [{"effect": "notice"}]}
        )
        assert constraints[0].summary == "Coordination signal may affect this plan."

    def test_source_ref_derives_from_evidence_url_objects(self) -> None:
        constraints = constraints_from_coordination_payload(
            {
                "status": "ok",
                "guidance": [
                    {
                        "effect": "pause",
                        "summary": "Blocks token work.",
                        "evidence": [{"url": "https://github.com/org/api/pull/42"}],
                    }
                ],
            }
        )
        assert constraints[0].source_ref == "signal:https://github.com/org/api/pull/42"
        assert constraints[0].read_hint == "context(mode='full') for full coordination evidence"


class TestCurationPayloadParsing:
    def test_status_other_than_ok_or_unavailable_yields_no_constraints(self) -> None:
        assert constraints_from_curation_payload({"status": "degraded"}) == ()

    def test_expired_active_items_without_id_are_skipped(self) -> None:
        assert (
            constraints_from_curation_payload(
                {"status": "ok", "expired_active": [{"title": "missing id"}]}
            )
            == ()
        )

    def test_revalidation_due_items_without_id_are_skipped(self) -> None:
        assert (
            constraints_from_curation_payload(
                {"status": "ok", "revalidation_due": [{"title": "missing id"}]}
            )
            == ()
        )

    def test_completed_artifact_revalidation_builds_constraint(self) -> None:
        constraints = constraints_from_curation_payload(
            {
                "status": "ok",
                "completed_artifact_revalidation": [
                    {"entry_id": "token-decision", "reason": "Artifact landed."},
                    {"reason": "no entry id, skipped"},
                ],
            }
        )
        assert len(constraints) == 1
        constraint = constraints[0]
        assert constraint.kind == ConstraintKind.CURATION
        assert constraint.effect == ConstraintEffect.VERIFY_BEFORE_RELYING
        assert constraint.entry_ref == "entry:token-decision"
        assert constraint.read_hint == "read(id='token-decision') for full body"


class TestCompilerPacketParsing:
    def test_constraints_with_unknown_kind_or_effect_are_dropped(self) -> None:
        packet = {
            "constraints": [
                {"kind": "coordination", "effect": "pause", "summary": "kept"},
                {"kind": "not-a-kind", "effect": "pause", "summary": "dropped kind"},
                {"kind": "coordination", "effect": "not-an-effect", "summary": "dropped effect"},
                {"kind": "coordination", "effect": "pause"},
                {"kind": 5, "effect": "pause", "summary": "non-string kind"},
                {"kind": "coordination", "effect": 5, "summary": "non-string effect"},
            ]
        }
        constraints = constraints_from_compiler_packet(packet)
        assert len(constraints) == 1
        assert constraints[0].summary == "kept"

    def test_entry_handles_require_id_title_and_type(self) -> None:
        packet = {
            "relevant_entries": [
                {"id": "kept", "title": "Kept", "type": "decision"},
                {"id": "no-title", "type": "decision"},
                {"title": "No id", "type": "decision"},
                {"id": "no-type", "title": "No type"},
            ]
        }
        handles = entry_handles_from_compiler_packet(packet)
        assert [handle.id for handle in handles] == ["kept"]

    def test_non_iterable_constraints_field_is_ignored(self) -> None:
        assert constraints_from_compiler_packet({"constraints": 5}) == ()
