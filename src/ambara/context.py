# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Public Ambara context API.

This module is the first stable import surface for the future
``ambara-context`` package. It intentionally exposes pure context models and
functions only.
"""

from ambara.core.context_compiler import (
    AvailabilityStatus,
    Constraint,
    ConstraintEffect,
    ConstraintKind,
    CoordinationStatus,
    EntryHandle,
    FreshnessState,
    PacketVerdict,
    PlanningAction,
    PlanningState,
    compile_context_packet,
    constraints_from_context_payload,
    constraints_from_coordination_payload,
    constraints_from_curation_payload,
    derive_coordination_status,
    derive_freshness,
    derive_planning_action,
    derive_planning_state,
    derive_public_verdict,
    planning_signature,
)
from ambara.core.contract import (
    AccessMode,
    KnowledgeQuery,
    KnowledgeResult,
    check_constraints,
    query_knowledge,
)
from ambara.core.index import Index
from ambara.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    Sensitivity,
    Visibility,
)

__all__ = [
    "AccessMode",
    "AvailabilityStatus",
    "Constraint",
    "ConstraintEffect",
    "ConstraintKind",
    "CoordinationStatus",
    "Entry",
    "EntryHandle",
    "EntryStatus",
    "EntryType",
    "EscalationLevel",
    "FreshnessState",
    "Frontmatter",
    "Index",
    "KnowledgeQuery",
    "KnowledgeResult",
    "PacketVerdict",
    "PlanningAction",
    "PlanningState",
    "Sensitivity",
    "Visibility",
    "check_constraints",
    "compile_context_packet",
    "constraints_from_context_payload",
    "constraints_from_coordination_payload",
    "constraints_from_curation_payload",
    "derive_coordination_status",
    "derive_freshness",
    "derive_planning_action",
    "derive_planning_state",
    "derive_public_verdict",
    "planning_signature",
    "query_knowledge",
]
