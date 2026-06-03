# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Pure context compiler algebra.

This module contains deterministic planning semantics only. It does not fetch,
parse, or persist source artifacts; callers pass already-derived context data in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class AvailabilityStatus(StrEnum):
    FRESH = "fresh"
    ACCEPTABLE = "acceptable"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class CoordinationStatus(StrEnum):
    CLEAR = "clear"
    CAUTION = "caution"
    BLOCKED = "blocked"


class PacketVerdict(StrEnum):
    CLEAR = "clear"
    CAUTION = "caution"
    BLOCKED = "blocked"
    STALE = "stale"
    CONTEXT_UNAVAILABLE = "context_unavailable"


class ConstraintKind(StrEnum):
    COORDINATION = "coordination"
    CURATION = "curation"
    FRESHNESS = "freshness"


class ConstraintEffect(StrEnum):
    PAUSE = "pause"
    REVISE = "revise"
    VERIFY_BEFORE_RELYING = "verify_before_relying"
    NOTICE = "notice"


class PlanningAction(StrEnum):
    PROCEED = "proceed"
    PROCEED_WITH_CAUTION = "proceed_with_caution"
    READ_OR_VERIFY_BEFORE_ACTING = "read_or_verify_before_acting"
    REVISE_PLAN_BEFORE_ACTING = "revise_plan_before_acting"
    PAUSE = "pause"
    STOP_OR_REQUEST_REFRESH = "stop_or_request_refresh"
    STOP_CONTEXT_UNAVAILABLE = "stop_context_unavailable"


@dataclass(frozen=True)
class FreshnessState:
    status: AvailabilityStatus
    last_success: datetime | None
    age_seconds: int | None
    warning_threshold_seconds: int
    stale_threshold_seconds: int
    last_failure: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": str(self.status),
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "age_seconds": self.age_seconds,
            "warning_threshold_seconds": self.warning_threshold_seconds,
            "stale_threshold_seconds": self.stale_threshold_seconds,
        }
        if self.last_failure is not None:
            payload["last_failure"] = self.last_failure.isoformat()
        if self.last_error is not None:
            payload["last_error"] = self.last_error
        if self.consecutive_failures:
            payload["consecutive_failures"] = self.consecutive_failures
        return payload


@dataclass(frozen=True)
class Constraint:
    kind: ConstraintKind
    effect: ConstraintEffect
    summary: str
    source_ref: str | None = None
    entry_ref: str | None = None
    read_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": str(self.kind),
            "effect": str(self.effect),
            "summary": self.summary,
        }
        if self.source_ref is not None:
            payload["source_ref"] = self.source_ref
        if self.entry_ref is not None:
            payload["entry_ref"] = self.entry_ref
        if self.read_hint is not None:
            payload["read_hint"] = self.read_hint
        return payload

    def to_compact_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "effect": str(self.effect),
            "kind": str(self.kind),
            "summary": self.summary,
        }
        ref = self.source_ref or self.entry_ref
        if ref is not None:
            payload["ref"] = ref
        return payload


@dataclass(frozen=True)
class EntryHandle:
    id: str
    title: str
    type: str
    summary: str | None = None
    read_hint: str | None = None
    why: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "type": self.type,
        }
        if self.summary is not None:
            payload["summary"] = self.summary
        if self.read_hint is not None:
            payload["read_hint"] = self.read_hint
        return payload

    def to_compact_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "type": self.type,
        }
        if self.why is not None:
            payload["why"] = self.why
        return payload


@dataclass(frozen=True)
class PlanningState:
    availability: AvailabilityStatus
    coordination: CoordinationStatus
    verdict: PacketVerdict
    action: PlanningAction
    blocking_constraints: tuple[Constraint, ...]
    caution_constraints: tuple[Constraint, ...]
    read_handles: tuple[str, ...]


def derive_freshness(
    *,
    now: datetime,
    last_success: datetime | None,
    warning_threshold_seconds: int,
    stale_threshold_seconds: int,
    last_failure: datetime | None = None,
    last_error: str | None = None,
    consecutive_failures: int = 0,
) -> FreshnessState:
    _validate_freshness_thresholds(warning_threshold_seconds, stale_threshold_seconds)

    if last_success is None:
        return FreshnessState(
            status=AvailabilityStatus.UNAVAILABLE,
            last_success=None,
            age_seconds=None,
            warning_threshold_seconds=warning_threshold_seconds,
            stale_threshold_seconds=stale_threshold_seconds,
            last_failure=last_failure,
            last_error=last_error,
            consecutive_failures=consecutive_failures,
        )

    age_seconds = max(0, int((now - last_success).total_seconds()))
    if age_seconds >= stale_threshold_seconds:
        status = AvailabilityStatus.STALE
    elif age_seconds >= warning_threshold_seconds:
        status = AvailabilityStatus.ACCEPTABLE
    else:
        status = AvailabilityStatus.FRESH

    return FreshnessState(
        status=status,
        last_success=last_success,
        age_seconds=age_seconds,
        warning_threshold_seconds=warning_threshold_seconds,
        stale_threshold_seconds=stale_threshold_seconds,
        last_failure=last_failure,
        last_error=last_error,
        consecutive_failures=consecutive_failures,
    )


def _validate_freshness_thresholds(
    warning_threshold_seconds: int, stale_threshold_seconds: int
) -> None:
    if warning_threshold_seconds < 0:
        raise ValueError("warning_threshold_seconds must be >= 0")
    if stale_threshold_seconds <= warning_threshold_seconds:
        raise ValueError("stale_threshold_seconds must be greater than warning threshold")


def derive_coordination_status(constraints: Iterable[Constraint]) -> CoordinationStatus:
    items = tuple(constraints)
    if any(item.effect == ConstraintEffect.PAUSE for item in items):
        return CoordinationStatus.BLOCKED
    if items:
        return CoordinationStatus.CAUTION
    return CoordinationStatus.CLEAR


def derive_public_verdict(
    availability: AvailabilityStatus, coordination: CoordinationStatus
) -> PacketVerdict:
    if availability == AvailabilityStatus.UNAVAILABLE:
        return PacketVerdict.CONTEXT_UNAVAILABLE
    if availability == AvailabilityStatus.STALE:
        return PacketVerdict.STALE
    if coordination == CoordinationStatus.BLOCKED:
        return PacketVerdict.BLOCKED
    if coordination == CoordinationStatus.CAUTION:
        return PacketVerdict.CAUTION
    return PacketVerdict.CLEAR


def derive_planning_action(
    verdict: PacketVerdict, constraints: Iterable[Constraint]
) -> PlanningAction:
    items = tuple(constraints)
    if verdict == PacketVerdict.CONTEXT_UNAVAILABLE:
        return PlanningAction.STOP_CONTEXT_UNAVAILABLE
    if verdict == PacketVerdict.STALE:
        return PlanningAction.STOP_OR_REQUEST_REFRESH
    if verdict == PacketVerdict.BLOCKED:
        return PlanningAction.PAUSE
    if any(item.effect == ConstraintEffect.VERIFY_BEFORE_RELYING for item in items):
        return PlanningAction.READ_OR_VERIFY_BEFORE_ACTING
    if any(item.effect == ConstraintEffect.REVISE for item in items):
        return PlanningAction.REVISE_PLAN_BEFORE_ACTING
    if items:
        return PlanningAction.PROCEED_WITH_CAUTION
    return PlanningAction.PROCEED


def derive_planning_state(
    freshness: FreshnessState,
    constraints: Iterable[Constraint],
    *,
    relevant_entries: Iterable[EntryHandle] = (),
) -> PlanningState:
    items = tuple(constraints)
    coordination = derive_coordination_status(items)
    verdict = derive_public_verdict(freshness.status, coordination)
    action = derive_planning_action(verdict, items)
    return PlanningState(
        availability=freshness.status,
        coordination=coordination,
        verdict=verdict,
        action=action,
        blocking_constraints=tuple(item for item in items if item.effect == ConstraintEffect.PAUSE),
        caution_constraints=tuple(item for item in items if item.effect != ConstraintEffect.PAUSE),
        read_handles=_read_handles(items, relevant_entries),
    )


def compile_context_packet(
    *,
    summary: str,
    freshness: FreshnessState,
    constraints: Iterable[Constraint] = (),
    relevant_entries: Iterable[EntryHandle] = (),
    coverage: Mapping[str, Any] | None = None,
    cost_accounting: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    items = tuple(constraints)
    entries = tuple(relevant_entries)
    if freshness.status == AvailabilityStatus.UNAVAILABLE:
        entries = ()
    state = derive_planning_state(freshness, items, relevant_entries=entries)
    packet = {
        "context_schema": "compiler-v1",
        "verdict": str(state.verdict),
        "availability": str(state.availability),
        "coordination": str(state.coordination),
        "planning_action": str(state.action),
        "summary": summary,
        "constraints": [item.to_dict() for item in items],
        "relevant_entries": [entry.to_dict() for entry in entries],
        "coverage": dict(coverage or {}),
        "freshness": freshness.to_dict(),
    }
    if cost_accounting:
        packet["cost_accounting"] = dict(cost_accounting)
    return packet


_STARTUP_V2_SCHEMA = "s2"

_ACTIONABLE_EFFECTS = frozenset(
    {ConstraintEffect.PAUSE, ConstraintEffect.REVISE, ConstraintEffect.VERIFY_BEFORE_RELYING}
)


def compile_startup_packet(
    *,
    freshness: FreshnessState,
    constraints: Iterable[Constraint] = (),
    relevant_entries: Iterable[EntryHandle] = (),
    entries_omitted: int = 0,
    restricted_hidden: int = 0,
    notices_omitted: int = 0,
    already_seen_suppressed: int = 0,
    duplicates_suppressed: int = 0,
    user_muted_suppressed: int = 0,
    value: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    all_constraints = tuple(constraints)
    actionable = tuple(c for c in all_constraints if c.effect in _ACTIONABLE_EFFECTS)
    extra_notices = len(all_constraints) - len(actionable)
    total_notices = notices_omitted + extra_notices

    entries = tuple(relevant_entries)
    if freshness.status == AvailabilityStatus.UNAVAILABLE:
        entries = ()

    state = derive_planning_state(freshness, actionable, relevant_entries=entries)

    packet: dict[str, Any] = {
        "v": _STARTUP_V2_SCHEMA,
        "availability": str(state.availability),
        "coordination": str(state.coordination),
        "action": str(state.action),
    }

    if freshness.status not in (AvailabilityStatus.FRESH, AvailabilityStatus.ACCEPTABLE):
        packet["reason"] = _startup_reason(freshness)
        packet["freshness"] = _compact_freshness(freshness)

    if actionable:
        packet["constraints"] = [c.to_compact_dict() for c in actionable]

    if entries:
        packet["entries"] = [e.to_compact_dict() for e in entries]

    more: dict[str, int] = {}
    if entries_omitted > 0:
        more["entries_omitted"] = entries_omitted
    if restricted_hidden > 0:
        more["restricted_hidden"] = restricted_hidden
    if total_notices > 0:
        more["notices_omitted"] = total_notices
    if already_seen_suppressed > 0:
        more["already_seen_suppressed"] = already_seen_suppressed
    if duplicates_suppressed > 0:
        more["duplicates_suppressed"] = duplicates_suppressed
    if user_muted_suppressed > 0:
        more["user_muted_suppressed"] = user_muted_suppressed
    if more:
        packet["more"] = more

    if value:
        packet["value"] = dict(value)

    return packet


def _startup_reason(freshness: FreshnessState) -> str:
    parts: list[str] = []
    if freshness.status == AvailabilityStatus.UNAVAILABLE:
        parts.append("No successful sync baseline available.")
    elif freshness.status == AvailabilityStatus.STALE:
        age = freshness.age_seconds
        if age is not None:
            minutes = age // 60
            parts.append(f"Last sync {minutes} minutes ago.")
        else:
            parts.append("Context is stale.")
    if freshness.last_error:
        parts.append(freshness.last_error)
    return " ".join(parts) if parts else "Context state degraded."


def _compact_freshness(freshness: FreshnessState) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if freshness.age_seconds is not None:
        payload["age_seconds"] = freshness.age_seconds
    if freshness.last_error is not None:
        payload["last_error"] = freshness.last_error
    return payload


def planning_signature(
    freshness: FreshnessState,
    constraints: Iterable[Constraint],
    *,
    relevant_entries: Iterable[EntryHandle] = (),
) -> dict[str, Any]:
    items = tuple(constraints)
    entries = tuple(relevant_entries)
    state = derive_planning_state(freshness, items, relevant_entries=entries)
    return _signature_payload(
        availability=str(state.availability),
        coordination=str(state.coordination),
        verdict=str(state.verdict),
        action=str(state.action),
        constraints=items,
        read_handles=state.read_handles,
    )


def planning_signature_from_compiler_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    constraints = constraints_from_compiler_packet(packet)
    entries = entry_handles_from_compiler_packet(packet)
    return _signature_payload(
        availability=_string_or_none(packet.get("availability")) or "",
        coordination=_string_or_none(packet.get("coordination")) or "",
        verdict=_string_or_none(packet.get("verdict")) or "",
        action=_string_or_none(packet.get("planning_action")) or "",
        constraints=constraints,
        read_handles=_read_handles(constraints, entries),
    )


def constraints_from_context_payload(payload: Mapping[str, Any]) -> tuple[Constraint, ...]:
    constraints: list[Constraint] = []
    coordination = payload.get("coordination")
    if isinstance(coordination, Mapping):
        constraints.extend(constraints_from_coordination_payload(coordination))
    curation = payload.get("curation")
    if isinstance(curation, Mapping):
        constraints.extend(constraints_from_curation_payload(curation))
    return tuple(constraints)


def constraints_from_compiler_packet(packet: Mapping[str, Any]) -> tuple[Constraint, ...]:
    constraints: list[Constraint] = []
    for raw_item in _iter_mapping_items(packet.get("constraints", ())):
        kind = _constraint_kind(raw_item.get("kind"))
        effect = _constraint_effect(raw_item.get("effect"))
        summary = _string_or_none(raw_item.get("summary"))
        if kind is None or effect is None or summary is None:
            continue
        constraints.append(
            Constraint(
                kind=kind,
                effect=effect,
                summary=summary,
                source_ref=_string_or_none(raw_item.get("source_ref")),
                entry_ref=_string_or_none(raw_item.get("entry_ref")),
                read_hint=_string_or_none(raw_item.get("read_hint")),
            )
        )
    return tuple(constraints)


def entry_handles_from_context_payload(payload: Mapping[str, Any]) -> tuple[EntryHandle, ...]:
    handles: list[EntryHandle] = []
    for key in ("active", "recent"):
        handles.extend(_entry_handles_from_items(payload.get(key, ())))
    return tuple(handles)


def entry_handles_from_compiler_packet(packet: Mapping[str, Any]) -> tuple[EntryHandle, ...]:
    return tuple(_entry_handles_from_items(packet.get("relevant_entries", ())))


def constraints_from_coordination_payload(payload: Mapping[str, Any]) -> tuple[Constraint, ...]:
    if payload.get("status") == "unavailable":
        return (
            _unavailable_payload_constraint(
                payload,
                kind=ConstraintKind.COORDINATION,
                source_ref="coordination:unavailable",
                default="Configured coordination signals are unavailable.",
                read_hint=(
                    "Refresh or inspect configured signal sources before treating absent "
                    "signals as safe."
                ),
            ),
        )
    if payload.get("status") != "ok":
        return ()

    constraints: list[Constraint] = []
    guidance = payload.get("guidance", ())
    if not isinstance(guidance, Iterable) or isinstance(guidance, (str, bytes)):
        return ()

    for raw_item in guidance:
        if not isinstance(raw_item, Mapping):
            continue
        effect = _coordination_effect(raw_item.get("effect"))
        summary = _summary_from(raw_item, default="Coordination signal may affect this plan.")
        constraints.append(
            Constraint(
                kind=ConstraintKind.COORDINATION,
                effect=effect,
                summary=summary,
                source_ref=_coordination_source_ref(raw_item),
                read_hint=_coordination_read_hint(raw_item),
            )
        )
    return tuple(constraints)


def constraints_from_curation_payload(payload: Mapping[str, Any]) -> tuple[Constraint, ...]:
    if payload.get("status") == "unavailable":
        return (
            _unavailable_payload_constraint(
                payload,
                kind=ConstraintKind.CURATION,
                source_ref="curation:unavailable",
                default="Signal-derived curation checks are unavailable.",
                read_hint=(
                    "Refresh or inspect curation inputs before treating missing advisories "
                    "as clean."
                ),
            ),
        )
    if payload.get("status") != "ok":
        return ()

    constraints: list[Constraint] = []
    for raw_item in _iter_mapping_items(payload.get("expired_active", ())):
        entry_id = _string_or_none(raw_item.get("id"))
        if entry_id is None:
            continue
        constraints.append(
            _curation_constraint(
                raw_item,
                entry_id=entry_id,
                default_summary="Expired active context must be verified before relying on it.",
            )
        )

    for raw_item in _iter_mapping_items(payload.get("revalidation_due", ())):
        entry_id = _string_or_none(raw_item.get("id"))
        if entry_id is None:
            continue
        constraints.append(
            _curation_constraint(
                raw_item,
                entry_id=entry_id,
                default_summary="Entry is due for revalidation before relying on it.",
            )
        )

    for raw_item in _iter_mapping_items(payload.get("completed_artifact_revalidation", ())):
        entry_id = _string_or_none(raw_item.get("entry_id"))
        if entry_id is None:
            continue
        constraints.append(
            _curation_constraint(
                raw_item,
                entry_id=entry_id,
                default_summary="Completed artifact changed related context; revalidate first.",
            )
        )

    return tuple(constraints)


def _unavailable_payload_constraint(
    payload: Mapping[str, Any],
    *,
    kind: ConstraintKind,
    source_ref: str,
    default: str,
    read_hint: str,
) -> Constraint:
    summary = _summary_from(payload, default=default)
    instruction = _string_or_none(payload.get("agent_instruction"))
    if instruction and instruction not in summary:
        summary = f"{summary} {instruction}"
    return Constraint(
        kind=kind,
        effect=ConstraintEffect.VERIFY_BEFORE_RELYING,
        summary=summary,
        source_ref=source_ref,
        read_hint=read_hint,
    )


def _coordination_effect(value: object) -> ConstraintEffect:
    if value == "pause":
        return ConstraintEffect.PAUSE
    if value == "revise":
        return ConstraintEffect.REVISE
    return ConstraintEffect.NOTICE


def _constraint_kind(value: object) -> ConstraintKind | None:
    if not isinstance(value, str):
        return None
    try:
        return ConstraintKind(value)
    except ValueError:
        return None


def _constraint_effect(value: object) -> ConstraintEffect | None:
    if not isinstance(value, str):
        return None
    try:
        return ConstraintEffect(value)
    except ValueError:
        return None


def _curation_constraint(
    item: Mapping[str, Any], *, entry_id: str, default_summary: str
) -> Constraint:
    return Constraint(
        kind=ConstraintKind.CURATION,
        effect=ConstraintEffect.VERIFY_BEFORE_RELYING,
        summary=_summary_from(item, default=default_summary),
        entry_ref=f"entry:{entry_id}",
        read_hint=_string_or_none(item.get("read_hint")) or _entry_read_hint(entry_id),
    )


def _summary_from(item: Mapping[str, Any], *, default: str) -> str:
    for key in ("planning_constraint", "summary", "agent_instruction", "reason"):
        value = _string_or_none(item.get(key))
        if value is not None:
            return value
    return default


def _coordination_source_ref(item: Mapping[str, Any]) -> str | None:
    explicit = _string_or_none(item.get("source_ref"))
    if explicit is not None:
        return explicit

    evidence_urls = item.get("evidence_urls")
    if isinstance(evidence_urls, Iterable) and not isinstance(evidence_urls, (str, bytes)):
        for value in evidence_urls:
            url = _string_or_none(value)
            if url is not None:
                return f"signal:{url}"

    evidence = item.get("evidence")
    if isinstance(evidence, Iterable) and not isinstance(evidence, (str, bytes)):
        for raw_evidence in evidence:
            if isinstance(raw_evidence, Mapping):
                url = _string_or_none(raw_evidence.get("url"))
                if url is not None:
                    return f"signal:{url}"

    source = _string_or_none(item.get("source"))
    if source is not None:
        return f"signal:{source}"
    return None


def _coordination_read_hint(item: Mapping[str, Any]) -> str | None:
    explicit = _string_or_none(item.get("read_hint"))
    if explicit is not None:
        return explicit
    if item.get("evidence") or item.get("evidence_urls"):
        return "context(mode='full') for full coordination evidence"
    return None


def _iter_mapping_items(value: object) -> Iterable[Mapping[str, Any]]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        return ()
    return (item for item in value if isinstance(item, Mapping))


def _entry_handles_from_items(value: object) -> tuple[EntryHandle, ...]:
    handles: list[EntryHandle] = []
    for item in _iter_mapping_items(value):
        entry_id = _string_or_none(item.get("id"))
        title = _string_or_none(item.get("title"))
        entry_type = _string_or_none(item.get("type"))
        if entry_id is None or title is None or entry_type is None:
            continue
        handles.append(
            EntryHandle(
                id=entry_id,
                title=title,
                type=entry_type,
                summary=_string_or_none(item.get("summary")),
                read_hint=_string_or_none(item.get("read_hint")),
            )
        )
    return tuple(handles)


def _read_handles(
    constraints: Iterable[Constraint], entries: Iterable[EntryHandle]
) -> tuple[str, ...]:
    handles: list[str] = []
    for entry in entries:
        if entry.read_hint:
            handles.append(entry.read_hint)
    for item in constraints:
        if item.read_hint:
            handles.append(item.read_hint)
    return tuple(dict.fromkeys(handles))


def _entry_read_hint(entry_id: str) -> str:
    return f"read(id='{entry_id}') for full body"


def _signature_payload(
    *,
    availability: str,
    coordination: str,
    verdict: str,
    action: str,
    constraints: Iterable[Constraint],
    read_handles: Iterable[str],
) -> dict[str, Any]:
    items = tuple(constraints)
    return {
        "availability": availability,
        "coordination": coordination,
        "verdict": verdict,
        "planning_action": action,
        "constraints": tuple(
            sorted(
                (
                    str(item.kind),
                    str(item.effect),
                    item.source_ref or "",
                    item.entry_ref or "",
                )
                for item in items
            )
        ),
        "read_handles": tuple(sorted(read_handles)),
    }


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
