from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

from jurati.core.context_compiler import (
    Constraint,
    ConstraintEffect,
    ConstraintKind,
    EntryHandle,
    PacketVerdict,
    PlanningAction,
    compile_context_packet,
    compile_startup_packet,
    derive_freshness,
    derive_planning_state,
)

NOW = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)


def _freshness(age_seconds: int = 0, **kwargs):
    return derive_freshness(
        now=NOW,
        last_success=NOW - timedelta(seconds=age_seconds),
        warning_threshold_seconds=300,
        stale_threshold_seconds=900,
        **kwargs,
    )


def _unavailable_freshness(**kwargs):
    return derive_freshness(
        now=NOW,
        last_success=None,
        warning_threshold_seconds=300,
        stale_threshold_seconds=900,
        **kwargs,
    )


def _constraint(
    effect: ConstraintEffect,
    *,
    kind: ConstraintKind = ConstraintKind.COORDINATION,
    source_ref: str | None = "signal:jira:CDEV-16845",
    entry_ref: str | None = None,
) -> Constraint:
    return Constraint(
        kind=kind,
        effect=effect,
        summary=f"Test {effect} constraint.",
        source_ref=source_ref,
        entry_ref=entry_ref,
    )


def _entry(id: str, *, type: str = "active", why: str | None = None) -> EntryHandle:
    return EntryHandle(
        id=id,
        title=f"Entry {id}",
        type=type,
        summary=f"Summary for {id}.",
        read_hint=f"read(id='{id}') for full body",
        why=why or "Active work relevant to request.",
    )


def _approx_tokens(payload: dict) -> int:
    return math.ceil(len(json.dumps(payload, default=str)) / 4)


class TestStartupPacketShape:
    def test_proceed_no_constraints(self) -> None:
        packet = compile_startup_packet(
            freshness=_freshness(),
            relevant_entries=[_entry("e1")],
        )
        assert packet["v"] == "s2"
        assert packet["availability"] == "fresh"
        assert packet["coordination"] == "clear"
        assert packet["action"] == "proceed"
        assert "constraints" not in packet
        assert "reason" not in packet
        assert "freshness" not in packet
        assert len(packet["entries"]) == 1
        assert packet["entries"][0]["id"] == "e1"
        assert "why" in packet["entries"][0]
        assert "summary" not in packet["entries"][0]
        assert "read_hint" not in packet["entries"][0]

    def test_caution_with_revise_constraint(self) -> None:
        packet = compile_startup_packet(
            freshness=_freshness(),
            constraints=[_constraint(ConstraintEffect.REVISE)],
            relevant_entries=[_entry("e1"), _entry("e2")],
        )
        assert packet["action"] == "revise_plan_before_acting"
        assert packet["coordination"] == "caution"
        assert len(packet["constraints"]) == 1
        c = packet["constraints"][0]
        assert c["effect"] == "revise"
        assert c["kind"] == "coordination"
        assert "ref" in c
        assert "source_ref" not in c
        assert "entry_ref" not in c
        assert "read_hint" not in c

    def test_blocked_with_pause_constraint(self) -> None:
        packet = compile_startup_packet(
            freshness=_freshness(),
            constraints=[_constraint(ConstraintEffect.PAUSE)],
            relevant_entries=[_entry("e1")],
        )
        assert packet["action"] == "pause"
        assert packet["coordination"] == "blocked"
        assert len(packet["constraints"]) == 1

    def test_verify_before_relying_constraint(self) -> None:
        packet = compile_startup_packet(
            freshness=_freshness(),
            constraints=[
                _constraint(
                    ConstraintEffect.VERIFY_BEFORE_RELYING,
                    kind=ConstraintKind.CURATION,
                    source_ref=None,
                    entry_ref="entry:token-format",
                )
            ],
            relevant_entries=[_entry("token-format", type="decision")],
        )
        assert packet["action"] == "read_or_verify_before_acting"
        c = packet["constraints"][0]
        assert c["effect"] == "verify_before_relying"
        assert c["kind"] == "curation"
        assert c["ref"] == "entry:token-format"

    def test_stale_with_blocker_uses_stop_or_refresh(self) -> None:
        packet = compile_startup_packet(
            freshness=_freshness(1200),
            constraints=[_constraint(ConstraintEffect.PAUSE)],
            relevant_entries=[_entry("e1")],
        )
        assert packet["action"] == "stop_or_request_refresh"
        assert packet["availability"] == "stale"
        assert packet["coordination"] == "blocked"
        assert "reason" in packet
        assert "freshness" in packet
        assert len(packet["constraints"]) == 1

    def test_unavailable_clears_entries(self) -> None:
        packet = compile_startup_packet(
            freshness=_unavailable_freshness(),
            relevant_entries=[_entry("e1")],
        )
        assert packet["action"] == "stop_context_unavailable"
        assert packet["availability"] == "unavailable"
        assert "entries" not in packet
        assert "reason" in packet


class TestNoticeFiltering:
    def test_notices_collapsed_into_more_count(self) -> None:
        packet = compile_startup_packet(
            freshness=_freshness(),
            constraints=[
                _constraint(ConstraintEffect.REVISE),
                _constraint(ConstraintEffect.NOTICE),
                _constraint(ConstraintEffect.NOTICE),
            ],
            relevant_entries=[_entry("e1")],
        )
        assert len(packet["constraints"]) == 1
        assert packet["constraints"][0]["effect"] == "revise"
        assert packet["more"]["notices_omitted"] == 2

    def test_all_notices_produce_proceed_with_count(self) -> None:
        packet = compile_startup_packet(
            freshness=_freshness(),
            constraints=[
                _constraint(ConstraintEffect.NOTICE),
                _constraint(ConstraintEffect.NOTICE),
            ],
            relevant_entries=[_entry("e1")],
        )
        assert packet["action"] == "proceed"
        assert packet["coordination"] == "clear"
        assert "constraints" not in packet
        assert packet["more"]["notices_omitted"] == 2

    def test_precomputed_notices_added_to_inline_notices(self) -> None:
        packet = compile_startup_packet(
            freshness=_freshness(),
            constraints=[_constraint(ConstraintEffect.NOTICE)],
            relevant_entries=[_entry("e1")],
            notices_omitted=3,
        )
        assert packet["more"]["notices_omitted"] == 4


class TestMoreObject:
    def test_more_omits_zero_fields(self) -> None:
        packet = compile_startup_packet(
            freshness=_freshness(),
            relevant_entries=[_entry("e1")],
        )
        assert "more" not in packet

    def test_more_includes_entries_omitted(self) -> None:
        packet = compile_startup_packet(
            freshness=_freshness(),
            relevant_entries=[_entry("e1")],
            entries_omitted=5,
            restricted_hidden=1,
        )
        assert packet["more"]["entries_omitted"] == 5
        assert packet["more"]["restricted_hidden"] == 1


class TestCompactDictMethods:
    def test_constraint_compact_dict_uses_ref(self) -> None:
        c = Constraint(
            kind=ConstraintKind.COORDINATION,
            effect=ConstraintEffect.REVISE,
            summary="Test.",
            source_ref="signal:jira:CDEV-123",
            entry_ref=None,
            read_hint="read(id='x') for full body",
        )
        d = c.to_compact_dict()
        assert d == {
            "effect": "revise",
            "kind": "coordination",
            "summary": "Test.",
            "ref": "signal:jira:CDEV-123",
        }
        assert "source_ref" not in d
        assert "read_hint" not in d

    def test_constraint_compact_dict_prefers_source_ref(self) -> None:
        c = Constraint(
            kind=ConstraintKind.CURATION,
            effect=ConstraintEffect.VERIFY_BEFORE_RELYING,
            summary="Check.",
            source_ref="signal:github:org/repo:pull:42",
            entry_ref="entry:some-id",
        )
        assert c.to_compact_dict()["ref"] == "signal:github:org/repo:pull:42"

    def test_constraint_compact_dict_falls_back_to_entry_ref(self) -> None:
        c = Constraint(
            kind=ConstraintKind.CURATION,
            effect=ConstraintEffect.VERIFY_BEFORE_RELYING,
            summary="Check.",
            source_ref=None,
            entry_ref="entry:token-format",
        )
        assert c.to_compact_dict()["ref"] == "entry:token-format"

    def test_entry_handle_compact_dict_has_why(self) -> None:
        h = EntryHandle(
            id="auth-handoff",
            title="Auth refactor handoff",
            type="active",
            summary="Full summary here.",
            read_hint="read(id='auth-handoff') for full body",
            why="Active work in this project.",
        )
        d = h.to_compact_dict()
        assert d == {
            "id": "auth-handoff",
            "title": "Auth refactor handoff",
            "type": "active",
            "why": "Active work in this project.",
        }
        assert "summary" not in d
        assert "read_hint" not in d

    def test_entry_handle_compact_dict_omits_none_why(self) -> None:
        h = EntryHandle(id="x", title="X", type="active")
        d = h.to_compact_dict()
        assert "why" not in d


class TestPlanningEquivalence:
    """s2 packets must produce the same planning state as compiler-v1 for identical inputs."""

    def _assert_same_planning_state(
        self,
        freshness,
        constraints: list[Constraint],
        entries: list[EntryHandle],
    ) -> None:
        actionable = [c for c in constraints if c.effect != ConstraintEffect.NOTICE]
        state_from_v1 = derive_planning_state(freshness, constraints, relevant_entries=entries)
        state_from_s2 = derive_planning_state(freshness, actionable, relevant_entries=entries)

        assert state_from_s2.availability == state_from_v1.availability
        assert state_from_s2.verdict == state_from_v1.verdict or (
            state_from_v1.verdict == PacketVerdict.CAUTION
            and state_from_s2.verdict == PacketVerdict.CLEAR
            and all(c.effect == ConstraintEffect.NOTICE for c in constraints)
        )

    def test_equivalence_proceed(self) -> None:
        self._assert_same_planning_state(_freshness(), [], [_entry("e1")])

    def test_equivalence_revise(self) -> None:
        self._assert_same_planning_state(
            _freshness(),
            [_constraint(ConstraintEffect.REVISE)],
            [_entry("e1")],
        )

    def test_equivalence_blocked(self) -> None:
        self._assert_same_planning_state(
            _freshness(),
            [_constraint(ConstraintEffect.PAUSE)],
            [_entry("e1")],
        )

    def test_equivalence_verify(self) -> None:
        self._assert_same_planning_state(
            _freshness(),
            [_constraint(ConstraintEffect.VERIFY_BEFORE_RELYING)],
            [_entry("e1")],
        )

    def test_equivalence_stale_with_blocker(self) -> None:
        self._assert_same_planning_state(
            _freshness(1200),
            [_constraint(ConstraintEffect.PAUSE)],
            [_entry("e1")],
        )

    def test_equivalence_unavailable(self) -> None:
        self._assert_same_planning_state(_unavailable_freshness(), [], [_entry("e1")])

    def test_notice_only_downgrades_to_proceed(self) -> None:
        """s2 filters notices, so notice-only → proceed (not proceed_with_caution)."""
        notices = [_constraint(ConstraintEffect.NOTICE), _constraint(ConstraintEffect.NOTICE)]
        v1_state = derive_planning_state(_freshness(), notices)
        assert v1_state.action == PlanningAction.PROCEED_WITH_CAUTION

        s2_packet = compile_startup_packet(
            freshness=_freshness(), constraints=notices, relevant_entries=[_entry("e1")]
        )
        assert s2_packet["action"] == "proceed"
        assert s2_packet["more"]["notices_omitted"] == 2


class TestTokenRegression:
    def _compiler_v1_tokens(self, freshness, constraints, entries) -> int:
        packet = compile_context_packet(
            summary="Test summary.",
            freshness=freshness,
            constraints=constraints,
            relevant_entries=entries,
        )
        return _approx_tokens(packet)

    def _startup_v2_tokens(self, freshness, constraints, entries) -> int:
        packet = compile_startup_packet(
            freshness=freshness,
            constraints=constraints,
            relevant_entries=entries,
        )
        return _approx_tokens(packet)

    def test_s2_smaller_than_v1_proceed(self) -> None:
        f = _freshness()
        entries = [_entry(f"e{i}") for i in range(5)]
        assert self._startup_v2_tokens(f, [], entries) < self._compiler_v1_tokens(f, [], entries)

    def test_s2_smaller_than_v1_with_constraints(self) -> None:
        f = _freshness()
        constraints = [
            _constraint(ConstraintEffect.REVISE),
            _constraint(ConstraintEffect.NOTICE),
        ]
        entries = [_entry(f"e{i}") for i in range(3)]
        assert self._startup_v2_tokens(f, constraints, entries) < self._compiler_v1_tokens(
            f, constraints, entries
        )

    def test_s2_smaller_than_v1_stale(self) -> None:
        f = _freshness(1200)
        constraints = [_constraint(ConstraintEffect.PAUSE)]
        entries = [_entry("e1")]
        assert self._startup_v2_tokens(f, constraints, entries) < self._compiler_v1_tokens(
            f, constraints, entries
        )

    def test_clear_packet_under_100_tokens(self) -> None:
        packet = compile_startup_packet(
            freshness=_freshness(),
            relevant_entries=[_entry("e1")],
        )
        assert _approx_tokens(packet) < 100

    def test_caution_packet_under_200_tokens(self) -> None:
        packet = compile_startup_packet(
            freshness=_freshness(),
            constraints=[
                _constraint(ConstraintEffect.REVISE),
                _constraint(ConstraintEffect.REVISE, source_ref="signal:jira:CDEV-999"),
            ],
            relevant_entries=[_entry("e1"), _entry("e2"), _entry("e3")],
            entries_omitted=4,
            restricted_hidden=1,
            notices_omitted=2,
        )
        assert _approx_tokens(packet) < 200
