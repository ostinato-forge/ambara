# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Network-free retrieval quality fixtures for context, query, and search."""

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
    Sensitivity,
)
from ambara.core.search import query as core_query
from ambara.server import _build_search_results, build_context_payload

NOW = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)


def _entry(
    *,
    entry_id: str,
    title: str,
    entry_type: EntryType,
    level: EscalationLevel,
    body: str,
    path: str,
    updated_at: datetime,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    expires_at: datetime | None = None,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    status: EntryStatus = EntryStatus.ACTIVE,
) -> Entry:
    return Entry(
        path=path,
        frontmatter=Frontmatter(
            id=entry_id,
            title=title,
            type=entry_type,
            level=level,
            status=status,
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            updated_at=updated_at,
            expires_at=expires_at,
            projects=projects or [],
            tags=tags or [],
            sensitivity=sensitivity,
            review=ReviewMeta(required=level != EscalationLevel.L0),
        ),
        body=body,
    )


def _evaluation_index() -> Index:
    entries = [
        _entry(
            entry_id="api-token-format",
            title="Token Format Decision",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            body="Use rotation_id and grace periods for login tokens.",
            path="decisions/api-token-format.md",
            updated_at=datetime(2026, 5, 18, 12, 0, tzinfo=UTC),
            projects=["api-service", "web-app"],
            tags=["auth", "tokens"],
        ),
        _entry(
            entry_id="release-validation-workflow",
            title="Release Validation Workflow",
            entry_type=EntryType.WORKFLOW,
            level=EscalationLevel.L2,
            body="Run pytest and ruff before review.",
            path="workflows/release-validation-workflow.md",
            updated_at=datetime(2026, 5, 17, 12, 0, tzinfo=UTC),
            projects=["api-service"],
            tags=["release", "validation"],
        ),
        _entry(
            entry_id="auth-refactor-status",
            title="Auth Refactor Status",
            entry_type=EntryType.PROJECT,
            level=EscalationLevel.L1,
            body="API service auth refactor waits on token format decisions.",
            path="projects/auth-refactor-status.md",
            updated_at=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
            projects=["api-service"],
            tags=["auth"],
        ),
        _entry(
            entry_id="frontend-auth-handoff",
            title="Frontend Auth Handoff",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            body="Frontend waits for the token rotation decision before changing login.",
            path="active/frontend-auth-handoff.md",
            updated_at=datetime(2026, 5, 19, 10, 0, tzinfo=UTC),
            expires_at=datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
            projects=["web-app"],
            tags=["auth"],
        ),
        _entry(
            entry_id="expired-auth-handoff",
            title="Expired Auth Handoff",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            body="Old auth handoff that should not appear by default.",
            path="active/expired-auth-handoff.md",
            updated_at=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
            expires_at=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
            projects=["web-app"],
            tags=["auth"],
        ),
        _entry(
            entry_id="restricted-token-vendor",
            title="Token Vendor Secret",
            entry_type=EntryType.DECISION,
            level=EscalationLevel.L2,
            body="Restricted vendor token details must never appear in broad retrieval.",
            path="decisions/restricted-token-vendor.md",
            updated_at=datetime(2026, 5, 18, 13, 0, tzinfo=UTC),
            projects=["api-service"],
            tags=["auth", "tokens"],
            sensitivity=Sensitivity.RESTRICTED,
        ),
    ]
    return Index(entries={entry.frontmatter.id: entry for entry in entries})


def _ids(items: list[dict[str, object]]) -> list[str]:
    return [str(item["id"]) for item in items]


def test_context_baseline_expected_hits_and_exclusions() -> None:
    payload = build_context_payload(_evaluation_index(), now=NOW, repo="api-service")

    active_ids = _ids(payload["active"])
    recent_ids = _ids(payload["recent"])
    all_ids = set(active_ids + recent_ids)

    assert "frontend-auth-handoff" in active_ids
    assert {"api-token-format", "release-validation-workflow", "auth-refactor-status"}.issubset(
        recent_ids
    )
    assert "restricted-token-vendor" not in all_ids
    assert "expired-auth-handoff" not in all_ids


def test_query_baseline_expected_hits_and_exclusions() -> None:
    index = _evaluation_index()

    rotation = core_query(index, "rotation_id", now=NOW)
    assert [result.entry.frontmatter.id for result in rotation] == ["api-token-format"]

    restricted = core_query(index, "vendor token", now=NOW, include_expired=True)
    assert [result.entry.frontmatter.id for result in restricted] == []

    expired = core_query(index, "old auth handoff", now=NOW)
    assert [result.entry.frontmatter.id for result in expired] == []

    with_expired = core_query(index, "old auth handoff", now=NOW, include_expired=True)
    assert [result.entry.frontmatter.id for result in with_expired] == ["expired-auth-handoff"]


def test_search_baseline_expected_hits_and_exclusions() -> None:
    results = _build_search_results(_evaluation_index(), "token rotation grace", now=NOW)
    ids = _ids(results)

    assert ids[0] == "api-token-format"
    assert "restricted-token-vendor" not in ids
    assert "expired-auth-handoff" not in ids


def test_search_filters_by_tags() -> None:
    results = _build_search_results(_evaluation_index(), "validation", now=NOW, tags="release")
    assert _ids(results) == ["release-validation-workflow"]


def test_context_with_goal_ranks_by_relevance() -> None:
    payload = build_context_payload(
        _evaluation_index(),
        now=NOW,
        repo="api-service",
        goal="token rotation grace period",
    )
    recent_ids = _ids(payload["recent"])
    assert recent_ids[0] == "api-token-format"
    assert "restricted-token-vendor" not in recent_ids
    assert "expired-auth-handoff" not in recent_ids


def test_context_with_goal_includes_project_matched_entries() -> None:
    payload = build_context_payload(
        _evaluation_index(),
        now=NOW,
        repo="api-service",
        goal="release validation",
    )
    recent_ids = _ids(payload["recent"])
    assert "release-validation-workflow" in recent_ids
    assert "auth-refactor-status" in recent_ids


def test_ambiguous_search_returns_shortlist_without_restricted_or_expired_entries() -> None:
    results = _build_search_results(_evaluation_index(), "auth", now=NOW, max_results=5)
    ids = set(_ids(results))

    assert {"api-token-format", "auth-refactor-status", "frontend-auth-handoff"}.issubset(ids)
    assert "restricted-token-vendor" not in ids
    assert "expired-auth-handoff" not in ids
