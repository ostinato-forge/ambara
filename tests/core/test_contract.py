# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for integration contract — AccessMode filtering and constraint checks."""

from __future__ import annotations

import pytest

from ambara.core.contract import (
    AccessMode,
    KnowledgeQuery,
    check_constraints,
    query_knowledge,
)
from ambara.core.index import Index
from ambara.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Sensitivity,
    Visibility,
)

from .conftest import BASE_NOW, make_entry, minutes_after


def _index_with(*entries: Entry) -> Index:
    idx = Index()
    for e in entries:
        idx.add(e)
    return idx


def _expired_active(entry_id: str, **overrides: object) -> Entry:
    return make_entry(
        entry_id=entry_id,
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        created_at=BASE_NOW,
        expires_at=minutes_after(5),
        review_required=False,
        **overrides,
    )


class TestAccessModeFiltering:
    def test_context_mode_excludes_restricted(self) -> None:
        normal = make_entry(entry_id="normal-contract", visibility=Visibility.INTERNAL)
        restricted = make_entry(
            entry_id="restricted-contract",
            sensitivity=Sensitivity.RESTRICTED,
        )
        idx = _index_with(normal, restricted)
        result = query_knowledge(idx, KnowledgeQuery(access_mode=AccessMode.CONTEXT), now=BASE_NOW)
        ids = [e["id"] for e in result.entries]
        assert "normal-contract" in ids
        assert "restricted-contract" not in ids

    def test_external_context_only_external_visibility(self) -> None:
        internal = make_entry(entry_id="internal-only", visibility=Visibility.INTERNAL)
        external = make_entry(entry_id="external-viz", visibility=Visibility.EXTERNAL)
        idx = _index_with(internal, external)
        result = query_knowledge(
            idx,
            KnowledgeQuery(access_mode=AccessMode.EXTERNAL_CONTEXT, system_id="sys-a"),
            now=BASE_NOW,
        )
        ids = [e["id"] for e in result.entries]
        assert "external-viz" in ids
        assert "internal-only" not in ids

    def test_gate_evidence_requires_external_and_source_branch(self) -> None:
        on_main = make_entry(
            entry_id="on-main",
            visibility=Visibility.EXTERNAL,
            on_source_branch=True,
        )
        off_main = make_entry(
            entry_id="off-main",
            visibility=Visibility.EXTERNAL,
            on_source_branch=False,
        )
        idx = _index_with(on_main, off_main)
        result = query_knowledge(
            idx,
            KnowledgeQuery(access_mode=AccessMode.GATE_EVIDENCE, system_id="gate"),
            now=BASE_NOW,
        )
        ids = [e["id"] for e in result.entries]
        assert "on-main" in ids
        assert "off-main" not in ids

    def test_durable_source_all_visibility_source_branch_only(self) -> None:
        on_main_int = make_entry(
            entry_id="durable-int",
            visibility=Visibility.INTERNAL,
            on_source_branch=True,
        )
        off_main = make_entry(
            entry_id="not-durable",
            on_source_branch=False,
        )
        idx = _index_with(on_main_int, off_main)
        result = query_knowledge(
            idx,
            KnowledgeQuery(access_mode=AccessMode.DURABLE_SOURCE, system_id="audit"),
            now=BASE_NOW,
        )
        ids = [e["id"] for e in result.entries]
        assert "durable-int" in ids
        assert "not-durable" not in ids

    def test_non_context_mode_requires_system_id(self) -> None:
        idx = Index()
        with pytest.raises(ValueError, match="system_id"):
            query_knowledge(
                idx,
                KnowledgeQuery(access_mode=AccessMode.EXTERNAL_CONTEXT),
                now=BASE_NOW,
            )

    def test_restricted_excluded_from_all_modes(self) -> None:
        restricted = make_entry(
            entry_id="restricted-ext",
            sensitivity=Sensitivity.RESTRICTED,
            visibility=Visibility.EXTERNAL,
            on_source_branch=True,
        )
        idx = _index_with(restricted)
        for mode in AccessMode:
            system_id = "sys" if mode != AccessMode.CONTEXT else None
            result = query_knowledge(
                idx,
                KnowledgeQuery(access_mode=mode, system_id=system_id),
                now=BASE_NOW,
            )
            assert len(result.entries) == 0, f"restricted entry visible in {mode}"


class TestQueryFilters:
    def test_filter_by_project(self) -> None:
        match = make_entry(entry_id="match-proj", projects=["api-service"])
        miss = make_entry(entry_id="miss-proj", projects=["web-app"])
        idx = _index_with(match, miss)
        result = query_knowledge(
            idx,
            KnowledgeQuery(project="api-service"),
            now=BASE_NOW,
        )
        ids = [e["id"] for e in result.entries]
        assert "match-proj" in ids
        assert "miss-proj" not in ids

    def test_filter_by_entry_type(self) -> None:
        decision = make_entry(
            entry_id="decision-filter",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            review_required=True,
        )
        project = make_entry(entry_id="project-filter", entry_type=EntryType.PROJECT)
        idx = _index_with(decision, project)
        result = query_knowledge(
            idx,
            KnowledgeQuery(entry_type="decision"),
            now=BASE_NOW,
        )
        ids = [e["id"] for e in result.entries]
        assert "decision-filter" in ids
        assert "project-filter" not in ids

    def test_max_results(self) -> None:
        entries = [make_entry(entry_id=f"entry-{i}") for i in range(20)]
        idx = _index_with(*entries)
        result = query_knowledge(
            idx,
            KnowledgeQuery(max_results=5),
            now=BASE_NOW,
        )
        assert len(result.entries) == 5

    def test_topic_filters_and_ranks_results(self) -> None:
        auth = make_entry(
            entry_id="auth-token-contract",
            title="Auth token contract",
            body="Use rotation grace windows for login tokens.",
        )
        release = make_entry(
            entry_id="release-contract",
            title="Release contract",
            body="Run validation before publishing.",
        )
        idx = _index_with(release, auth)
        result = query_knowledge(idx, KnowledgeQuery(topic="rotation tokens"), now=BASE_NOW)
        ids = [e["id"] for e in result.entries]
        assert ids == ["auth-token-contract"]

    def test_expired_entries_are_excluded_from_query(self) -> None:
        expired = _expired_active("expired-active")
        idx = _index_with(expired)

        after_expiry = minutes_after(10)
        result = query_knowledge(idx, KnowledgeQuery(), now=after_expiry)

        assert result.entries == []

    def test_unknown_entry_type_filter_matches_nothing(self) -> None:
        entry = make_entry(entry_id="some-project")
        idx = _index_with(entry)

        result = query_knowledge(idx, KnowledgeQuery(entry_type="not-a-real-type"), now=BASE_NOW)

        assert result.entries == []

    def test_result_contains_entry_metadata(self) -> None:
        entry = make_entry(
            entry_id="meta-test",
            title="Meta Entry",
            entry_type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            status=EntryStatus.PROPOSED,
        )
        idx = _index_with(entry)
        result = query_knowledge(idx, KnowledgeQuery(), now=BASE_NOW)
        assert len(result.entries) == 1
        e = result.entries[0]
        assert e["id"] == "meta-test"
        assert e["title"] == "Meta Entry"
        assert e["type"] == "project"
        assert e["level"] == "L1"
        assert e["status"] == "proposed"


class TestCheckConstraints:
    def test_returns_relevant_decisions(self) -> None:
        decision = make_entry(
            entry_id="auth-constraint",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            projects=["api-service"],
            status=EntryStatus.ACTIVE,
            review_required=True,
            review_pr="https://github.com/org/kb/pull/5",
        )
        idx = _index_with(decision)
        results = check_constraints(idx, "api-service", now=BASE_NOW)
        assert len(results) == 1
        assert results[0].frontmatter.id == "auth-constraint"

    def test_excludes_restricted_constraints(self) -> None:
        restricted = make_entry(
            entry_id="restricted-constraint",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            projects=["api-service"],
            sensitivity=Sensitivity.RESTRICTED,
        )
        idx = _index_with(restricted)
        results = check_constraints(idx, "api-service", now=BASE_NOW)
        assert results == []

    def test_ignores_irrelevant_project(self) -> None:
        decision = make_entry(
            entry_id="other-constraint",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            projects=["other-service"],
        )
        idx = _index_with(decision)
        results = check_constraints(idx, "api-service", now=BASE_NOW)
        assert len(results) == 0

    def test_ignores_non_constraint_types(self) -> None:
        project = make_entry(
            entry_id="project-not-constraint",
            entry_type=EntryType.PROJECT,
            projects=["api-service"],
        )
        idx = _index_with(project)
        results = check_constraints(idx, "api-service", now=BASE_NOW)
        assert len(results) == 0

    def test_custom_constraint_types(self) -> None:
        workflow = make_entry(
            entry_id="wf-constraint",
            entry_type=EntryType.WORKFLOW,
            level=EscalationLevel.L2,
            projects=["api-service"],
        )
        idx = _index_with(workflow)
        results = check_constraints(
            idx,
            "api-service",
            now=BASE_NOW,
            constraint_types=(EntryType.WORKFLOW,),
        )
        assert len(results) == 1

    def test_includes_principles(self) -> None:
        principle = make_entry(
            entry_id="principle-constraint",
            entry_type=EntryType.PRINCIPLE,
            level=EscalationLevel.L3,
            projects=["api-service"],
        )
        idx = _index_with(principle)
        results = check_constraints(idx, "api-service", now=BASE_NOW)
        assert len(results) == 1

    def test_excludes_expired_constraints(self) -> None:
        # A constraint-type decision that matches the project on every axis except
        # expiry: only the is_expired check removes it from the results.
        expired_decision = make_entry(
            entry_id="expired-decision",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            projects=["api-service"],
            created_at=BASE_NOW,
            expires_at=minutes_after(5),
        )
        idx = _index_with(expired_decision)

        before_expiry = minutes_after(4)
        after_expiry = minutes_after(10)

        still_active = check_constraints(idx, "api-service", now=before_expiry)
        assert [entry.frontmatter.id for entry in still_active] == ["expired-decision"]
        assert check_constraints(idx, "api-service", now=after_expiry) == []
