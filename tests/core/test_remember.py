# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti
"""Tests for the pure remember decision core."""

from __future__ import annotations

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from ambara.core.content_policy import WritePolicy
from ambara.core.content_policy_config import default_config
from ambara.core.remember import (
    RememberCandidate,
    RememberProvenance,
    plan_remember,
)
from ambara.core.schema import (
    Entry,
    EntryType,
    EscalationLevel,
    Frontmatter,
)

NOW = datetime(2026, 6, 13, tzinfo=UTC)


def _policy() -> WritePolicy:
    return WritePolicy(default_config())


def _candidate(**kw: object) -> RememberCandidate:
    base: dict[str, object] = dict(
        kind="promote",
        entry_id="github-42",
        title="Use gRPC internally",
        body="We will use gRPC for internal services.",
        entry_type=EntryType.PROJECT,
        requested_level=EscalationLevel.L1,
        branch_prefix="ambara/promote",
    )
    base.update(kw)
    return RememberCandidate(**base)  # type: ignore[arg-type]


def _existing(entry_id: str, title: str, etype: EntryType = EntryType.PROJECT) -> Entry:
    fm = Frontmatter(
        id=entry_id,
        title=title,
        type=etype,
        level=EscalationLevel.L1,
        created_at=NOW,
        updated_at=NOW,
    )
    return Entry(path=f"context/{entry_id}.md", frontmatter=fm, body="prior body")


def test_clean_candidate_creates_intent() -> None:
    plan = plan_remember(_candidate(), index_entries=[], content_policy=_policy(), now=NOW)
    assert plan.action == "create"
    assert plan.intent is not None
    assert plan.intent.entry_id == "github-42"
    assert plan.intent.branch == "ambara/promote/github-42"
    assert plan.level == EscalationLevel.L1
    assert plan.requires_pr is False


def test_block_content_rejects() -> None:
    cand = _candidate(body="key: -----BEGIN PRIVATE KEY-----")  # gitleaks:allow
    plan = plan_remember(cand, index_entries=[], content_policy=_policy(), now=NOW)
    assert plan.action == "reject"
    assert plan.intent is None
    assert plan.reject_reasons


def test_confidential_escalates_l1_to_l2() -> None:
    cand = _candidate(body="This decision is confidential and internal.")
    plan = plan_remember(cand, index_entries=[], content_policy=_policy(), now=NOW)
    assert plan.action == "create"
    assert plan.level == EscalationLevel.L2
    assert plan.requires_pr is True


def test_secret_present_escalates_to_l2() -> None:
    plan = plan_remember(
        _candidate(secrets_present=True), index_entries=[], content_policy=_policy(), now=NOW
    )
    assert plan.action == "create"
    assert plan.level == EscalationLevel.L2


def test_promote_candidate_appends_provenance_footer() -> None:
    prov = RememberProvenance(
        provider="github",
        external_id="42",
        url="https://github.com/o/r/pull/42",
        captured_at=NOW,
    )
    plan = plan_remember(
        _candidate(provenance=prov), index_entries=[], content_policy=_policy(), now=NOW
    )
    assert plan.intent is not None
    assert "<!-- ambara:provenance:v1 -->" in plan.intent.content
    assert "github/42" in plan.intent.content
    assert "https://github.com/o/r/pull/42" in plan.intent.content


def test_capture_candidate_has_no_footer() -> None:
    plan = plan_remember(
        _candidate(kind="capture", provenance=None),
        index_entries=[],
        content_policy=_policy(),
        now=NOW,
    )
    assert plan.intent is not None
    assert "ambara:provenance" not in plan.intent.content


def test_determinism_same_inputs_same_plan() -> None:
    p1 = plan_remember(_candidate(), index_entries=[], content_policy=_policy(), now=NOW)
    p2 = plan_remember(_candidate(), index_entries=[], content_policy=_policy(), now=NOW)
    assert p1.intent is not None and p2.intent is not None
    assert p1.intent.content == p2.intent.content
    assert p1.intent.branch == p2.intent.branch
    assert p1.receipt == p2.receipt


def test_contradiction_ids_surfaced() -> None:
    existing = [_existing("grpc-prior", "Use gRPC internally")]
    plan = plan_remember(_candidate(), index_entries=existing, content_policy=_policy(), now=NOW)
    assert "grpc-prior" in plan.contradiction_ids
    assert "grpc-prior" in plan.receipt.get("contradiction_ids", [])


@given(
    title=st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=3, max_size=40
    ),
    body=st.text(max_size=200),
)
def test_plan_remember_is_deterministic(title: str, body: str) -> None:
    """core/ promises same-in/same-out: identical candidates yield identical plans."""
    cand = _candidate(title=title, body=body)
    p1 = plan_remember(cand, index_entries=[], content_policy=_policy(), now=NOW)
    p2 = plan_remember(cand, index_entries=[], content_policy=_policy(), now=NOW)
    assert p1.action == p2.action
    assert (p1.intent is None) == (p2.intent is None)
    if p1.intent is not None and p2.intent is not None:
        assert p1.intent.content == p2.intent.content
        assert p1.intent.branch == p2.intent.branch
    assert p1.receipt == p2.receipt
