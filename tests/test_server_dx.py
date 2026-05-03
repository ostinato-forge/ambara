"""Tests for DX-layer MCP tools: context and search."""

from __future__ import annotations

from datetime import UTC, datetime

from jurati.core.index import Index
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
)
from jurati.server import _build_context_payload, _build_search_results


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
        result = _build_context_payload(index, now=now)
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
        result = _build_context_payload(index, now=now)
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
        result = _build_context_payload(index, now=now)
        assert len(result["active"]) == 0


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
