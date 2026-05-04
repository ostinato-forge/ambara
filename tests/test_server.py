"""Tests for jurati.server read tools."""

from __future__ import annotations

from datetime import UTC, datetime

from jurati.core.hygiene import summarize_lifecycle
from jurati.core.index import Index
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
)
from jurati.core.search import SearchResult
from jurati.git.config import JuratiConfig
from jurati.server import (
    ServerState,
    SyncHealth,
    _entry_counts,
    _expire_receipt,
    _explain_payload,
    _format_entry,
    _format_hygiene_report,
    _format_result,
    _state_status_payload,
    _write_receipt,
)

NOW = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)


def _make_entry(
    *,
    entry_id: str = "test-entry",
    title: str = "Test entry",
    entry_type: EntryType = EntryType.DECISION,
    level: EscalationLevel = EscalationLevel.L2,
    status: EntryStatus = EntryStatus.ACTIVE,
    body: str = "Test body content.",
    tags: list[str] | None = None,
    projects: list[str] | None = None,
    updated_at: datetime | None = None,
    expires_at: datetime | None = None,
    supersedes: list[str] | None = None,
    superseded_by: str | None = None,
    pr: str | None = "https://github.com/org/repo/pull/1",
) -> Entry:
    return Entry(
        path=f"decisions/{entry_id}.md",
        frontmatter=Frontmatter(
            id=entry_id,
            title=title,
            type=entry_type,
            level=level,
            status=status,
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            updated_at=updated_at or datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            expires_at=expires_at,
            tags=tags or [],
            projects=projects or [],
            supersedes=supersedes or [],
            superseded_by=superseded_by,
            review=ReviewMeta(required=True, pr=pr),
        ),
        body=body,
    )


def _make_active_entry(
    *,
    entry_id: str = "sprint-goal",
    expires_at: datetime | None = None,
) -> Entry:
    if expires_at is None:
        expires_at = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    return Entry(
        path=f"active/{entry_id}.md",
        frontmatter=Frontmatter(
            id=entry_id,
            title="Current sprint goal",
            type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            updated_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            expires_at=expires_at,
            review=ReviewMeta(required=False),
        ),
        body="Ship jurati v1.",
    )


def _build_state(*entries: Entry) -> ServerState:
    index = Index()
    for entry in entries:
        index.add(entry)
    return ServerState(
        config=JuratiConfig(remote_url="https://example.com/repo.git"),
        repo_path="/fake/repo",
        index=index,
        last_sync=NOW,
        sync_health=SyncHealth(last_success=NOW),
    )


class TestFormatEntry:
    def test_includes_all_fields(self) -> None:
        entry = _make_entry()
        result = _format_entry(entry)
        assert result["id"] == "test-entry"
        assert result["title"] == "Test entry"
        assert result["type"] == "decision"
        assert result["level"] == "L2"
        assert result["body"] == "Test body content."
        assert result["path"] == "decisions/test-entry.md"

    def test_expires_at_none(self) -> None:
        entry = _make_entry(expires_at=None)
        result = _format_entry(entry)
        assert result["expires_at"] is None

    def test_expires_at_formatted(self) -> None:
        exp = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        entry = _make_entry(expires_at=exp)
        result = _format_entry(entry)
        assert "2026-06-01" in result["expires_at"]

    def test_format_result_includes_match_explanation(self) -> None:
        entry = _make_entry(entry_id="use-ruff", tags=["tooling"])
        result = _format_result(
            SearchResult(
                entry=entry,
                relevance=3.0,
                match_reasons=["title contains the query topic"],
            )
        )

        assert result["match"]["reasons"] == ["title contains the query topic"]
        assert result["match"]["source"]["path"] == "decisions/use-ruff.md"
        assert result["match"]["source"]["type"] == "decision"


class TestExplainTool:
    def test_explain_payload_names_boundaries(self) -> None:
        payload = _explain_payload()

        assert "shared team memory" in payload["summary"]
        assert any("local cache" in item for item in payload["reads"])
        assert any("pull request" in item for item in payload["writes"])
        assert "persist query text" in payload["does_not"]


class TestStatusPayload:
    def test_state_status_payload_shows_runtime_boundaries(self) -> None:
        state = _build_state(
            _make_entry(entry_id="dec-1"),
            _make_active_entry(entry_id="active-1"),
        )

        payload = _state_status_payload(state)

        assert payload["knowledge_remote"] == "https://example.com/repo.git"
        assert payload["local_cache"] == "/fake/repo"
        assert payload["entries_indexed"] == 2
        assert payload["entries_by_type"]["decision"] == 1
        assert payload["entries_by_type"]["active"] == 1
        assert "no query logging" in payload["privacy_boundary"]

    def test_entry_counts_includes_zero_counts(self) -> None:
        index = Index()
        index.add(_make_entry(entry_id="dec-1"))

        counts = _entry_counts(index)

        assert counts["decision"] == 1
        assert counts["active"] == 0


class TestHygienePayload:
    def test_hygiene_report_summarizes_lifecycle_work(self) -> None:
        expired_active = _make_active_entry(
            entry_id="expired-focus",
            expires_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
        stale_proposed = _make_entry(
            entry_id="old-proposal",
            status=EntryStatus.PROPOSED,
            updated_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
            pr=None,
        )
        replacement = _make_entry(
            entry_id="new-architecture-rule",
            supersedes=["old-architecture-rule"],
        )
        state = _build_state(expired_active, stale_proposed, replacement)

        report = summarize_lifecycle(state.index, now=NOW, stale_after_days=30)
        payload = _format_hygiene_report(report)

        assert payload["summary"]["expired_active"] == 1
        assert payload["summary"]["stale_proposed"] == 1
        assert payload["summary"]["supersession"] == 1
        assert payload["expired_active"][0]["id"] == "expired-focus"
        assert payload["stale_proposed"][0]["id"] == "old-proposal"
        assert payload["supersession"][0]["supersedes"] == ["old-architecture-rule"]
        assert "does not infer absence" in payload["privacy_boundary"][1]


class TestReceipts:
    def test_active_write_receipt_explains_visibility(self) -> None:
        receipt = _write_receipt(
            entry_id="current-focus",
            write_mode="active_ref",
            commit="abc123",
            active_ref="refs/heads/jurati/active/codex/current-focus",
        )

        assert "short-lived active context" in receipt["what_happened"]
        assert "not durable" in receipt["visibility"]
        assert "expire" in receipt["next_step"]

    def test_pr_write_receipt_explains_next_step(self) -> None:
        receipt = _write_receipt(
            entry_id="release-workflow",
            write_mode="review_pr",
            commit="def456",
            branch="jurati/release-workflow",
            pr_url="https://example.com/pr/1",
            pr_number=1,
        )

        assert "reviewed knowledge pull request" in receipt["what_happened"]
        assert receipt["pr_number"] == 1
        assert "run sync" in receipt["next_step"]

    def test_expire_receipt_distinguishes_active_ref(self) -> None:
        receipt = _expire_receipt(
            entry_id="current-focus",
            write_mode="active_ref",
            active_ref="refs/heads/jurati/active/codex/current-focus",
        )

        assert "Expired active context" in receipt["what_happened"]
        assert "No review" in receipt["next_step"]

    def test_branch_only_write_receipt(self) -> None:
        receipt = _write_receipt(
            entry_id="new-project",
            write_mode="branch_only",
            commit="abc123",
            branch="jurati/new-project",
        )
        assert "branch" in receipt["what_happened"].lower()
        assert receipt["branch"] == "jurati/new-project"
        assert "pr_url" not in receipt or receipt.get("pr_url") is None

    def test_branch_only_expire_receipt(self) -> None:
        receipt = _expire_receipt(
            entry_id="old-decision",
            write_mode="branch_only",
            commit="def456",
            branch="jurati/expire-old-decision",
        )
        assert "branch" in receipt["what_happened"].lower()
        assert receipt["branch"] == "jurati/expire-old-decision"


class TestQueryTool:
    """Test query logic via core_query against a populated index."""

    def test_query_matches_title(self) -> None:
        from jurati.core.search import query as core_query

        state = _build_state(
            _make_entry(entry_id="use-ruff", title="Use Ruff for linting"),
            _make_entry(entry_id="use-black", title="Use Black for formatting"),
        )
        results = core_query(state.index, "ruff", now=NOW)
        assert len(results) == 1
        assert results[0].entry.frontmatter.id == "use-ruff"
        assert "title contains the query topic" in results[0].match_reasons

    def test_query_excludes_expired_by_default(self) -> None:
        from jurati.core.search import query as core_query

        expired = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
        state = _build_state(
            _make_active_entry(entry_id="old-goal", expires_at=expired),
            _make_active_entry(entry_id="current-goal"),
        )
        results = core_query(state.index, "goal", now=NOW)
        ids = [r.entry.frontmatter.id for r in results]
        assert "current-goal" in ids
        assert "old-goal" not in ids

    def test_query_includes_expired_when_asked(self) -> None:
        from jurati.core.search import query as core_query

        expired = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
        state = _build_state(
            _make_active_entry(entry_id="old-goal", expires_at=expired),
        )
        results = core_query(state.index, "goal", now=NOW, include_expired=True)
        assert len(results) == 1


class TestReadTool:
    """Test read logic against the index."""

    def test_read_returns_entry(self) -> None:
        state = _build_state(_make_entry(entry_id="my-decision"))
        entry = state.index.get("my-decision")
        assert entry is not None
        assert entry.frontmatter.title == "Test entry"

    def test_read_missing_returns_none(self) -> None:
        state = _build_state()
        assert state.index.get("nonexistent") is None


class TestListTool:
    """Test list_entries logic against the index."""

    def test_list_filters_by_type(self) -> None:
        state = _build_state(
            _make_entry(entry_id="dec-1"),
            _make_active_entry(entry_id="active-1"),
        )
        entries = state.index.list_entries(now=NOW, entry_type=EntryType.DECISION)
        ids = [e.frontmatter.id for e in entries]
        assert "dec-1" in ids
        assert "active-1" not in ids

    def test_list_filters_by_project(self) -> None:
        state = _build_state(
            _make_entry(entry_id="proj-a", projects=["alpha"]),
            _make_entry(entry_id="proj-b", projects=["beta"]),
        )
        entries = state.index.list_entries(now=NOW, project="alpha")
        ids = [e.frontmatter.id for e in entries]
        assert "proj-a" in ids
        assert "proj-b" not in ids

    def test_list_filters_by_status(self) -> None:
        state = _build_state(
            _make_entry(entry_id="active-dec", status=EntryStatus.ACTIVE),
            _make_entry(
                entry_id="proposed-dec",
                status=EntryStatus.PROPOSED,
                pr=None,
            ),
        )
        entries = state.index.list_entries(now=NOW, status=EntryStatus.ACTIVE)
        ids = [e.frontmatter.id for e in entries]
        assert "active-dec" in ids
        assert "proposed-dec" not in ids


class TestValidateTool:
    """Test validate logic via validate_entry."""

    def test_valid_entry_returns_no_errors(self) -> None:
        from jurati.core.validate import validate_entry

        entry = _make_entry()
        errors = validate_entry(entry)
        assert errors == []

    def test_invalid_entry_returns_errors(self) -> None:
        from jurati.core.validate import validate_entry

        entry = _make_entry(entry_id="bad-path")
        entry = Entry(
            path="wrong-dir/bad-path.md",
            frontmatter=entry.frontmatter,
            body=entry.body,
        )
        errors = validate_entry(entry)
        assert any("path" in e for e in errors)
