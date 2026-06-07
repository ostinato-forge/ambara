# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Property-based tests for core domain invariants.

These assert properties that must hold for *all* inputs, not just the examples
in the sibling modules: token-accounting non-negativity and additivity,
content-policy severity monotonicity, and schema id validation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from ambara.core.content_policy import (
    CallerScope,
    PolicyAction,
    PolicySubject,
    WritePolicy,
    subject_content_hash,
)
from ambara.core.content_policy_config import default_config
from ambara.core.context_accounting import (
    AccountingInputs,
    compact_value_receipt,
    detailed_cost_accounting,
    estimate_text_tokens,
    estimate_tokens,
)
from ambara.core.schema import (
    DEFAULT_LEVEL_MAP,
    ID_PATTERN,
    EntryType,
    EscalationLevel,
    Frontmatter,
    requires_pr,
)

NOW = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)
_CALLER = CallerScope(actor="prop", actor_kind="human", trusted=False)
_POLICY = WritePolicy(default_config())

# A credential-shaped string the default block policy must reject, mirroring the
# example in tests/test_content_safety.py. Not a real secret; the inline marker
# tells the gitleaks pre-commit gate this fixture is intentional.
_KNOWN_BLOCKED = "ghp_ABC123DEF456GHI789JKL012MNO345PQR678STU9"  # gitleaks:allow


# --- token accounting -------------------------------------------------------


@given(st.text())
def test_token_estimate_is_nonnegative_and_zero_only_when_empty(text: str) -> None:
    est = estimate_text_tokens(text)
    assert est >= 0
    assert (est == 0) == (len(text) == 0)


@given(st.text(), st.text())
def test_token_estimate_is_monotonic_in_length(a: str, b: str) -> None:
    # The estimate depends only on length, so longer text never costs fewer tokens.
    if len(a) <= len(b):
        assert estimate_text_tokens(a) <= estimate_text_tokens(b)


def test_estimate_tokens_of_none_is_zero() -> None:
    assert estimate_tokens(None) == 0


@given(
    st.integers(min_value=0, max_value=10**9),
    st.integers(min_value=0, max_value=10**9),
)
def test_value_receipt_savings_never_go_negative(packet: int, full: int) -> None:
    receipt = compact_value_receipt(packet_tokens_est=packet, full_context_tokens_est=full)
    assert receipt["packet_tokens_est"] == packet
    assert receipt["saved_tokens_est"] == max(0, full - packet)
    assert receipt["saved_tokens_est"] >= 0


@given(
    st.integers(min_value=-1000, max_value=1000),
    st.integers(min_value=-1000, max_value=1000),
)
def test_cost_accounting_clamps_counts_and_stays_additive(omitted: int, restricted: int) -> None:
    inputs = AccountingInputs(
        tool_name="startup",
        context_schema="s2",
        request_payload={"q": "x"},
        response_payload={"r": [1, 2, 3]},
        receipt_payload={"v": 1},
        entries_omitted_count=omitted,
        restricted_hidden_count=restricted,
        full_context_tokens_est=10_000,
    )
    acct = detailed_cost_accounting(inputs)
    # Aggregate counts are clamped to non-negative regardless of input.
    assert acct["entries_omitted_count"] >= 0
    assert acct["restricted_hidden_count"] >= 0
    # Actual tokens are exactly the additive sum of the three payload estimates.
    expected = (
        estimate_tokens(inputs.request_payload)
        + estimate_tokens(inputs.response_payload)
        + estimate_tokens(inputs.receipt_payload)
    )
    assert acct["actual_ambara_tokens_est"] == expected
    assert acct["net_savings_tokens_est"] == acct["counterfactual_tokens_est"] - expected


# --- content policy ---------------------------------------------------------


@given(st.text(), st.text())
def test_block_is_absorbing(title: str, body: str) -> None:
    # Appending a credential-shaped token must force BLOCK regardless of the rest
    # of the content, because BLOCK is the highest-severity action.
    subject = PolicySubject(source="record", title=title, body=f"{body} {_KNOWN_BLOCKED}")
    verdict = _POLICY.evaluate(subject, _CALLER, now=NOW)
    assert verdict.action == PolicyAction.BLOCK


@given(st.text(), st.text())
def test_policy_verdict_is_deterministic(title: str, body: str) -> None:
    subject = PolicySubject(source="record", title=title, body=body)
    first = _POLICY.evaluate(subject, _CALLER, now=NOW)
    second = _POLICY.evaluate(subject, _CALLER, now=NOW)
    assert first.action == second.action
    assert first.rule_ids == second.rule_ids
    assert subject_content_hash(subject) == subject_content_hash(subject)


# --- schema -----------------------------------------------------------------


def _frontmatter(entry_id: str) -> Frontmatter:
    return Frontmatter(
        id=entry_id,
        title="t",
        type=EntryType.PROJECT,
        level=EscalationLevel.L1,
        created_at=NOW,
        updated_at=NOW,
    )


@given(st.from_regex(ID_PATTERN, fullmatch=True))
def test_pattern_matching_ids_are_accepted(entry_id: str) -> None:
    assert _frontmatter(entry_id).id == entry_id


@pytest.mark.parametrize(
    "bad_id",
    ["", "a", "ab", "-abc", "Abc", "ab_c", "ab c", "a" * 200, "ABC"],
)
def test_non_matching_ids_are_rejected(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        _frontmatter(bad_id)


@given(st.sampled_from(list(EscalationLevel)))
def test_requires_pr_exactly_for_l2_and_l3(level: EscalationLevel) -> None:
    assert requires_pr(level) == (level in (EscalationLevel.L2, EscalationLevel.L3))


@given(st.sampled_from(list(EntryType)))
def test_every_entry_type_has_a_default_level(entry_type: EntryType) -> None:
    assert DEFAULT_LEVEL_MAP[entry_type]
