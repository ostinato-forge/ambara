# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

from ambara.core.index import Index, parse_entry
from ambara.core.schema import EntryStatus, EntryType, EscalationLevel, Sensitivity
from ambara.core.search import query

from .conftest import BASE_NOW, make_entry, minutes_after


def test_index_add_get_remove_round_trip() -> None:
    index = Index()
    entry = make_entry(entry_id="project-status")

    index.add(entry)

    assert index.get("project-status") == entry
    assert index.remove("project-status") == entry
    assert index.get("project-status") is None


def test_list_entries_filters_and_sorts_by_updated_at() -> None:
    older = make_entry(entry_id="older", updated_at=minutes_after(1), projects=["alpha"])
    newer = make_entry(entry_id="newer", updated_at=minutes_after(2), projects=["alpha"])
    other = make_entry(entry_id="other", updated_at=minutes_after(3), projects=["beta"])
    index = Index(entries={e.frontmatter.id: e for e in [older, newer, other]})

    results = index.list_entries(now=BASE_NOW, project="alpha")

    assert [entry.frontmatter.id for entry in results] == ["newer", "older"]


def test_list_entries_excludes_expired_entries_by_default() -> None:
    active = make_entry(
        entry_id="active-now",
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        expires_at=minutes_after(10),
        review_required=False,
    )
    expired = make_entry(
        entry_id="expired-now",
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        expires_at=minutes_after(1),
        review_required=False,
    )
    index = Index(entries={e.frontmatter.id: e for e in [active, expired]})

    results = index.list_entries(now=minutes_after(2))

    assert [entry.frontmatter.id for entry in results] == ["active-now"]


def test_list_entries_can_include_expired_entries() -> None:
    expired = make_entry(
        entry_id="expired-now",
        entry_type=EntryType.ACTIVE,
        level=EscalationLevel.L0,
        status=EntryStatus.ACTIVE,
        expires_at=minutes_after(1),
        review_required=False,
    )
    index = Index(entries={expired.frontmatter.id: expired})

    results = index.list_entries(now=minutes_after(2), include_expired=True)

    assert [entry.frontmatter.id for entry in results] == ["expired-now"]


def test_list_entries_excludes_retired_statuses_by_default() -> None:
    active = make_entry(entry_id="active-context", status=EntryStatus.ACTIVE)
    expired = make_entry(entry_id="expired-context", status=EntryStatus.EXPIRED)
    superseded = make_entry(entry_id="superseded-context", status=EntryStatus.SUPERSEDED)
    index = Index(entries={e.frontmatter.id: e for e in [active, expired, superseded]})

    results = index.list_entries(now=BASE_NOW)
    with_expired = index.list_entries(now=BASE_NOW, include_expired=True)

    assert [entry.frontmatter.id for entry in results] == ["active-context"]
    assert {entry.frontmatter.id for entry in with_expired} == {
        "active-context",
        "expired-context",
        "superseded-context",
    }


def test_list_entries_excludes_restricted_entries() -> None:
    normal = make_entry(entry_id="normal-entry", title="Normal")
    restricted = make_entry(
        entry_id="restricted-entry",
        title="Restricted",
        sensitivity=Sensitivity.RESTRICTED,
    )
    index = Index(entries={e.frontmatter.id: e for e in [normal, restricted]})

    results = index.list_entries(now=BASE_NOW, include_expired=True)

    assert [entry.frontmatter.id for entry in results] == ["normal-entry"]


def test_query_scores_title_above_body_match() -> None:
    title_match = make_entry(entry_id="title-match", title="Cache Policy", body="Other")
    body_match = make_entry(entry_id="body-match", title="Other", body="Cache appears here")
    index = Index(entries={e.frontmatter.id: e for e in [body_match, title_match]})

    results = query(index, "cache", now=BASE_NOW)

    assert [result.entry.frontmatter.id for result in results] == ["title-match", "body-match"]
    assert results[0].relevance > results[1].relevance


def test_query_matches_exact_tag() -> None:
    tagged = make_entry(
        entry_id="tagged-entry",
        title="Unrelated heading",
        body="Unrelated body.",
        tags=["caching"],
    )
    index = Index(entries={tagged.frontmatter.id: tagged})

    results = query(index, "caching", now=BASE_NOW)

    assert len(results) == 1
    assert results[0].entry.frontmatter.id == "tagged-entry"
    assert "tag exactly matches the query topic" in results[0].match_reasons


def test_query_applies_type_project_status_and_since_filters() -> None:
    matching = make_entry(
        entry_id="matching-workflow",
        title="Review Workflow",
        entry_type=EntryType.WORKFLOW,
        level=EscalationLevel.L2,
        projects=["ambara"],
        status=EntryStatus.PROPOSED,
        updated_at=minutes_after(5),
        body="Review steps",
    )
    stale = make_entry(
        entry_id="stale-workflow",
        title="Review Workflow",
        entry_type=EntryType.WORKFLOW,
        level=EscalationLevel.L2,
        projects=["ambara"],
        status=EntryStatus.PROPOSED,
        updated_at=minutes_after(1),
    )
    wrong_project = make_entry(
        entry_id="wrong-project",
        title="Review Workflow",
        entry_type=EntryType.WORKFLOW,
        level=EscalationLevel.L2,
        projects=["other"],
        status=EntryStatus.PROPOSED,
        updated_at=minutes_after(5),
    )
    index = Index(
        entries={e.frontmatter.id: e for e in [matching, stale, wrong_project]},
    )

    results = query(
        index,
        "review",
        now=BASE_NOW,
        entry_type=EntryType.WORKFLOW,
        project="ambara",
        status=EntryStatus.PROPOSED,
        since=minutes_after(2),
    )

    assert [result.entry.frontmatter.id for result in results] == ["matching-workflow"]


def test_parse_entry_builds_frontmatter_model() -> None:
    entry = parse_entry(
        "projects/parsed-entry.md",
        {
            "id": "parsed-entry",
            "title": "Parsed Entry",
            "type": "project",
            "level": "L1",
            "status": "proposed",
            "created_at": "2026-05-02T12:00:00Z",
            "updated_at": "2026-05-02T12:05:00Z",
        },
        "Parsed body",
    )

    assert entry.frontmatter.id == "parsed-entry"
    assert entry.frontmatter.updated_at == minutes_after(5)


class TestSourceParsing:
    def test_parse_entry_with_source(self) -> None:
        raw_fm = {
            "schema_version": 1,
            "id": "test-source",
            "title": "Test",
            "type": "project",
            "level": "L1",
            "status": "proposed",
            "created_at": "2026-05-02T12:00:00Z",
            "updated_at": "2026-05-02T12:00:00Z",
            "expires_at": None,
            "projects": [],
            "tags": [],
            "supersedes": [],
            "superseded_by": None,
            "sensitivity": "normal",
            "review": {"required": True, "pr": None},
            "source": {
                "repo": "api-service",
                "commit": "abc123",
                "author": "dev@co.com",
            },
        }
        entry = parse_entry("projects/test-source.md", raw_fm, "Body")
        assert entry.frontmatter.source is not None
        assert entry.frontmatter.source.repo == "api-service"

    def test_parse_entry_without_source(self) -> None:
        raw_fm = {
            "schema_version": 1,
            "id": "test-no-source",
            "title": "Test",
            "type": "project",
            "level": "L1",
            "status": "proposed",
            "created_at": "2026-05-02T12:00:00Z",
            "updated_at": "2026-05-02T12:00:00Z",
            "expires_at": None,
            "projects": [],
            "tags": [],
            "supersedes": [],
            "superseded_by": None,
            "sensitivity": "normal",
            "review": {"required": True, "pr": None},
        }
        entry = parse_entry("projects/test-no-source.md", raw_fm, "Body")
        assert entry.frontmatter.source is None
