# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for DX-layer MCP tools: context and search."""

from __future__ import annotations

from datetime import UTC, datetime

from ambara.core.index import Index
from ambara.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
)
from ambara.core.search import query as core_query
from ambara.server import _build_search_results, _explain_payload, build_context_payload


def _make_fm(**overrides: object) -> Frontmatter:
    defaults = dict(
        id="test-entry",
        title="Test Entry",
        type=EntryType.PROJECT,
        level=EscalationLevel.L1,
        status=EntryStatus.ACTIVE,
        created_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 2, 12, 0, tzinfo=UTC),
        review=ReviewMeta(required=True),
    )
    defaults.update(overrides)
    return Frontmatter(**defaults)


def _make_entry(**overrides: object) -> Entry:
    fm_kwargs = {k: v for k, v in overrides.items() if k not in ("body", "path")}
    return Entry(
        path=overrides.get("path", f"projects/{overrides.get('id', 'test-entry')}.md"),
        frontmatter=_make_fm(**fm_kwargs),
        body=overrides.get("body", "Body text"),
    )


class TestBuildContextPayload:
    def test_includes_active_entries(self) -> None:
        index = Index()
        active = _make_entry(
            id="active-1",
            title="Working on auth",
            type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            path="active/active-1.md",
            expires_at=datetime(2026, 5, 3, 12, 0, tzinfo=UTC),
        )
        index.add(active)

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        result = build_context_payload(index, now=now)
        assert len(result["active"]) == 1
        assert result["active"][0]["id"] == "active-1"

    def test_includes_recent_decisions(self) -> None:
        index = Index()
        decision = _make_entry(
            id="dec-1",
            title="Switch to gRPC",
            type=EntryType.DECISION,
            level=EscalationLevel.L2,
            path="decisions/dec-1.md",
        )
        index.add(decision)

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        result = build_context_payload(index, now=now)
        assert len(result["recent"]) == 1

    def test_excludes_expired_active(self) -> None:
        index = Index()
        expired = _make_entry(
            id="expired-1",
            title="Old task",
            type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            path="active/expired-1.md",
            expires_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
        index.add(expired)

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        result = build_context_payload(index, now=now)
        assert len(result["active"]) == 0

    def test_coordination_omitted_when_none(self) -> None:
        index = Index()
        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        result = build_context_payload(index, now=now)
        assert "coordination" not in result

    def test_coordination_included_when_provided(self) -> None:
        index = Index()
        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        coord = {"status": "ok", "summary": "No signals", "guidance": []}
        result = build_context_payload(index, now=now, coordination=coord)
        assert result["coordination"]["status"] == "ok"
        assert result["coordination"]["privacy_ref"] == "standard"

    def test_curation_omitted_when_none(self) -> None:
        index = Index()
        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        result = build_context_payload(index, now=now)
        assert "curation" not in result

    def test_curation_included_when_provided(self) -> None:
        index = Index()
        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        curation = {
            "status": "ok",
            "summary": "No advisories",
            "total_advisories": 0,
            "shown_advisories": 0,
            "expired_active": [],
            "revalidation_due": [],
            "completed_artifact_revalidation": [],
        }
        result = build_context_payload(index, now=now, curation=curation)
        assert result["curation"]["status"] == "ok"
        assert result["curation"]["policy_ref"] == "lifecycle-standard"

    def test_goal_ranks_relevant_entries_first(self) -> None:
        index = Index()
        index.add(
            _make_entry(
                id="grpc-decision",
                title="Use gRPC for internal services",
                type=EntryType.DECISION,
                level=EscalationLevel.L2,
                body="All internal service communication uses gRPC.",
                projects=["api-service"],
            )
        )
        index.add(
            _make_entry(
                id="frontend-css",
                title="Use Tailwind CSS for styling",
                type=EntryType.DECISION,
                level=EscalationLevel.L2,
                body="Adopt Tailwind for all new frontend components.",
                projects=["web-app"],
            )
        )

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        result = build_context_payload(
            index, now=now, repo="api-service", goal="add a gRPC endpoint"
        )
        ids = [e["id"] for e in result["recent"]]
        assert ids[0] == "grpc-decision"

    def test_goal_preserves_project_matched_entries(self) -> None:
        index = Index()
        index.add(
            _make_entry(
                id="relevant-by-project",
                title="Unrelated title about nothing",
                type=EntryType.WORKFLOW,
                level=EscalationLevel.L2,
                body="Unrelated body text with no keyword overlap.",
                projects=["my-service"],
            )
        )
        index.add(
            _make_entry(
                id="keyword-match",
                title="Deploy checklist for canary rollout",
                type=EntryType.WORKFLOW,
                level=EscalationLevel.L2,
                body="Canary deploys require 5% traffic for 30 minutes.",
                projects=["platform"],
            )
        )

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        result = build_context_payload(index, now=now, repo="my-service", goal="deploy canary")
        ids = [e["id"] for e in result["recent"]]
        assert "keyword-match" in ids
        assert "relevant-by-project" in ids

    def test_no_goal_preserves_original_behavior(self) -> None:
        index = Index()
        for i in range(3):
            index.add(
                _make_entry(
                    id=f"entry-{i}",
                    title=f"Entry {i}",
                    updated_at=datetime(2026, 5, 2, 12 + i, 0, tzinfo=UTC),
                )
            )

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        result = build_context_payload(index, now=now)
        ids = [e["id"] for e in result["recent"]]
        assert ids == ["entry-2", "entry-1", "entry-0"]


class TestBuildSearchResults:
    def test_returns_ranked_results(self) -> None:
        index = Index()
        e1 = _make_entry(id="e-1", title="postgres pool limit")
        e2 = _make_entry(id="e-2", title="redis cache strategy")
        index.add(e1)
        index.add(e2)

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        results = _build_search_results(index, "postgres pool", now=now)
        assert len(results) >= 1
        assert results[0]["id"] == "e-1"

    def test_honest_zero(self) -> None:
        index = Index()
        e1 = _make_entry(id="e-1", title="postgres pool limit")
        index.add(e1)

        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)
        results = _build_search_results(index, "kubernetes helm chart", now=now)
        assert len(results) == 0


class TestExplainPayload:
    def test_includes_retrieval_guidance(self) -> None:
        payload = _explain_payload()
        assert "retrieval" in payload
        r = payload["retrieval"]
        assert "query" in r
        assert "search" in r
        assert "recommendation" in r


class TestQueryFallback:
    def _build_index(self) -> Index:
        index = Index()
        index.add(
            _make_entry(
                id="team-knowledge-first",
                title="Team knowledge must be shared",
                body="Knowledge management practices for the whole team.",
                type=EntryType.PRINCIPLE,
                level=EscalationLevel.L3,
                path="principles/team-knowledge-first.md",
            )
        )
        return index

    def test_fallback_returns_bm25_results_with_hint(self) -> None:
        index = self._build_index()
        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)

        exact = core_query(index, "shared team practices", now=now)
        assert len(exact) == 0

        fallback = _build_search_results(index, "shared team practices", now=now)
        assert len(fallback) >= 1
        assert fallback[0]["id"] == "team-knowledge-first"

    def test_no_fallback_when_exact_matches_exist(self) -> None:
        index = self._build_index()
        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)

        exact = core_query(index, "knowledge", now=now)
        assert len(exact) >= 1

    def test_empty_when_both_exact_and_bm25_fail(self) -> None:
        index = self._build_index()
        now = datetime(2026, 5, 2, 14, 0, tzinfo=UTC)

        exact = core_query(index, "kubernetes helm chart", now=now)
        assert len(exact) == 0

        fallback = _build_search_results(index, "kubernetes helm chart", now=now)
        assert len(fallback) == 0
