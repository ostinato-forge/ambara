"""Tests for jurati.server read tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import anyio

from jurati.core.content_policy import WritePolicy
from jurati.core.content_policy_config import default_config
from jurati.core.hygiene import summarize_lifecycle
from jurati.core.index import Index
from jurati.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
    Sensitivity,
)
from jurati.core.scoring import build_inverted_index
from jurati.core.search import SearchResult
from jurati.git.config import JuratiConfig
from jurati.server import (
    ServerState,
    SyncHealth,
    _add_entry_to_index,
    _build_context_payload,
    _build_search_results,
    _entry_counts,
    _expire_receipt,
    _explain_payload,
    _format_entry,
    _format_hygiene_report,
    _format_result,
    _get_bm25_index,
    _remove_entry_from_index,
    _state_status_payload,
    _write_receipt,
    propose,
    read,
    record,
    validate,
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
    review_after: datetime | None = None,
    supersedes: list[str] | None = None,
    superseded_by: str | None = None,
    pr: str | None = "https://github.com/org/repo/pull/1",
    sensitivity: Sensitivity = Sensitivity.NORMAL,
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
            review_after=review_after,
            tags=tags or [],
            projects=projects or [],
            supersedes=supersedes or [],
            superseded_by=superseded_by,
            sensitivity=sensitivity,
            review=ReviewMeta(required=True, pr=pr),
        ),
        body=body,
    )


def _make_active_entry(
    *,
    entry_id: str = "sprint-goal",
    expires_at: datetime | None = None,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
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
            sensitivity=sensitivity,
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


class _FakeCtx:
    def __init__(self, state: ServerState) -> None:
        self.request_context = type("RC", (), {"lifespan_context": state})()


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

        assert "shared agent context" in payload["summary"]
        assert any("local cache" in item for item in payload["reads"])
        assert any("pull request" in item for item in payload["writes"])
        assert any("human-reviewable source format" in item for item in payload["storage_model"])
        assert "persist query text" in payload["does_not"]
        assert payload["request_mapping"][0]["tool"] == "propose"
        assert "team decision" in payload["request_mapping"][0]["developer_request"].lower()


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
        needs_review = _make_entry(
            entry_id="review-cache-choice",
            title="Review cache choice",
            status=EntryStatus.ACTIVE,
            pr="https://github.com/org/repo/pull/2",
            review_after=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
        proposed_review = _make_entry(
            entry_id="review-proposed-choice",
            title="Review proposed choice",
            status=EntryStatus.PROPOSED,
            pr=None,
            review_after=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
        state = _build_state(expired_active, stale_proposed, replacement, needs_review)
        state.index.add(proposed_review)

        report = summarize_lifecycle(state.index, now=NOW, stale_after_days=30)
        payload = _format_hygiene_report(report)

        assert payload["summary"]["expired_active"] == 1
        assert payload["summary"]["stale_proposed"] == 1
        assert payload["summary"]["revalidation"] == 1
        assert payload["summary"]["supersession"] == 1
        assert payload["expired_active"][0]["id"] == "expired-focus"
        assert payload["stale_proposed"][0]["id"] == "old-proposal"
        assert payload["revalidation"][0]["id"] == "review-cache-choice"
        assert all(item["id"] != "review-proposed-choice" for item in payload["revalidation"])
        assert payload["revalidation"][0]["review_after"] == "2026-05-01T12:00:00+00:00"
        assert payload["supersession"][0]["supersedes"] == ["old-architecture-rule"]
        assert "does not infer absence" in payload["privacy_boundary"][2]
        assert "Call expire" not in payload["expired_active"][0]["next_step"]
        assert "active ref" not in payload["expired_active"][0]["next_step"]
        assert "knowledge PR" not in payload["stale_proposed"][0]["next_step"]
        assert "merge" not in payload["stale_proposed"][0]["next_step"].lower()
        assert "knowledge workflow" in payload["revalidation"][0]["next_step"]


class TestReceipts:
    def _assert_human_fields_hide_internals(
        self, receipt: dict[str, object], *, extra_forbidden: tuple[str, ...] = ()
    ) -> None:
        human_text = " ".join(
            str(receipt[key])
            for key in ("developer_confirmation", "what_happened", "visibility", "next_step")
        ).lower()
        forbidden = (
            "entry_id",
            "refs/",
            "active ref",
            "branch",
            "pr ",
            "pr#",
            "pull request",
            "knowledge repo",
            "jurati",
            "run sync",
            "sync()",
            "other agents",
            "will see",
            "merge ",
            "expires",
            *extra_forbidden,
        )
        for term in forbidden:
            assert term not in human_text

        guidance = receipt["agent_guidance"]
        assert isinstance(guidance, dict)
        assert guidance["default_reply"] == receipt["developer_confirmation"]
        assert "debugging was explicitly requested" in guidance["developer_reply"]
        assert "entry_id" in guidance["debug_only_fields"]
        assert "branch" in guidance["debug_only_fields"]

    def test_active_write_receipt_biases_to_human_confirmation(self) -> None:
        receipt = _write_receipt(
            entry_id="current-focus",
            write_mode="active_ref",
            commit="abc123",
            active_ref="refs/heads/jurati/active/codex/current-focus",
        )

        assert receipt["developer_confirmation"] == "Recorded the current work update."
        assert receipt["next_step"] == "No developer action needed."
        assert receipt["active_ref"] == "refs/heads/jurati/active/codex/current-focus"
        self._assert_human_fields_hide_internals(receipt, extra_forbidden=("current-focus",))

    def test_pr_write_receipt_biases_to_human_confirmation(self) -> None:
        receipt = _write_receipt(
            entry_id="release-workflow",
            write_mode="review_pr",
            commit="def456",
            branch="jurati/release-workflow",
            pr_url="https://example.com/pr/1",
            pr_number=1,
        )

        assert receipt["developer_confirmation"] == "Submitted the update for team review."
        assert receipt["next_step"] == "No developer action needed."
        assert receipt["pr_number"] == 1
        self._assert_human_fields_hide_internals(receipt, extra_forbidden=("release-workflow",))

    def test_expire_receipt_biases_to_human_confirmation(self) -> None:
        receipt = _expire_receipt(
            entry_id="current-focus",
            write_mode="active_ref",
            active_ref="refs/heads/jurati/active/codex/current-focus",
        )

        assert receipt["developer_confirmation"] == "Cleared the stale context."
        assert receipt["next_step"] == "No developer action needed."
        assert receipt["active_ref"] == "refs/heads/jurati/active/codex/current-focus"
        self._assert_human_fields_hide_internals(receipt, extra_forbidden=("current-focus",))

    def test_branch_only_write_receipt(self) -> None:
        receipt = _write_receipt(
            entry_id="new-project",
            write_mode="branch_only",
            commit="abc123",
            branch="jurati/new-project",
        )
        assert receipt["developer_confirmation"] == "Saved the update for review."
        assert receipt["branch"] == "jurati/new-project"
        assert "pr_url" not in receipt or receipt.get("pr_url") is None
        self._assert_human_fields_hide_internals(receipt, extra_forbidden=("new-project",))

    def test_branch_only_expire_receipt(self) -> None:
        receipt = _expire_receipt(
            entry_id="old-decision",
            write_mode="branch_only",
            commit="def456",
            branch="jurati/expire-old-decision",
        )
        assert receipt["developer_confirmation"] == "Submitted the cleanup for review."
        assert receipt["branch"] == "jurati/expire-old-decision"
        self._assert_human_fields_hide_internals(receipt, extra_forbidden=("old-decision",))


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

    def test_bm25_cache_rebuilds_after_index_mutation(self) -> None:
        state = _build_state(_make_entry(entry_id="alpha", title="Alpha", body="alpha body"))
        initial_index = _get_bm25_index(state)
        assert initial_index.doc_count == 1

        _add_entry_to_index(
            state,
            _make_entry(
                entry_id="body-hit",
                title="Unrelated title",
                body="needle appears only in the body",
            ),
        )

        rebuilt_index = _get_bm25_index(state)
        assert rebuilt_index is not initial_index
        results = _build_search_results(
            state.index,
            "needle",
            now=NOW,
            prebuilt_index=rebuilt_index,
        )
        assert [item["id"] for item in results] == ["body-hit"]

        assert _remove_entry_from_index(state, "body-hit") is not None
        removed_index = _get_bm25_index(state)
        assert removed_index is not rebuilt_index
        assert removed_index.doc_count == 1


class TestContextPayload:
    def test_context_excludes_expired_and_restricted_active_entries(self) -> None:
        expired = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
        state = _build_state(
            _make_active_entry(entry_id="expired-focus", expires_at=expired),
            _make_active_entry(
                entry_id="restricted-focus",
                sensitivity=Sensitivity.RESTRICTED,
            ),
            _make_active_entry(entry_id="current-focus"),
        )

        payload = _build_context_payload(state.index, now=NOW, goal="focus")

        ids = [item["id"] for item in payload["active"]]
        assert ids == ["current-focus"]


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

    def test_read_returns_links_and_backlinks(self) -> None:
        source = _make_entry(entry_id="source-entry", body="See [[target-entry|target]].")
        target = _make_entry(entry_id="target-entry")
        state = _build_state(source, target)
        ctx = _FakeCtx(state)

        async def run() -> tuple[dict[str, object], dict[str, object]]:
            return (
                await read(id="source-entry", ctx=ctx),
                await read(id="target-entry", ctx=ctx),
            )

        source_payload, target_payload = anyio.run(run)

        assert source_payload["links"] == {
            "outgoing": ["target-entry"],
            "backlinks": [],
            "broken": [],
        }
        assert target_payload["links"] == {
            "outgoing": [],
            "backlinks": ["source-entry"],
            "broken": [],
        }

    def test_read_backlinks_do_not_leak_restricted_sources(self) -> None:
        restricted_source = _make_entry(
            entry_id="restricted-source",
            body="See [[target-entry]].",
            sensitivity=Sensitivity.RESTRICTED,
        )
        target = _make_entry(entry_id="target-entry")
        state = _build_state(restricted_source, target)
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            return await read(id="target-entry", ctx=ctx)

        payload = anyio.run(run)

        assert payload["links"] == {
            "outgoing": [],
            "backlinks": [],
            "broken": [],
        }

    def test_read_restricted_entry_by_id_is_hidden(self) -> None:
        restricted = _make_entry(
            entry_id="restricted-entry",
            body="Sensitive details.",
            sensitivity=Sensitivity.RESTRICTED,
        )
        state = _build_state(restricted)
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            return await read(id="restricted-entry", ctx=ctx)

        payload = anyio.run(run)

        assert payload == {"error": "Entry 'restricted-entry' not found"}


class TestWritePathCorrections:
    def test_record_returns_structured_correction_for_durable_decision(self) -> None:
        state = _build_state()
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            return await record(
                type="decision",
                title="Token rotation approach",
                content="Use rotation ids and grace periods.",
                ctx=ctx,
                entry_id="token-rotation-approach",
            )

        payload = anyio.run(run)

        assert "cannot create L2 content" in str(payload["error"])
        correction = payload["suggested_write_path"]
        assert correction["tool"] == "propose"
        assert correction["arguments"]["type"] == "decision"
        assert correction["arguments"]["title"] == "Token rotation approach"
        assert "request_mapping" in payload["agent_guidance"]

    def test_propose_returns_structured_correction_for_handoff(self) -> None:
        state = _build_state()
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            return await propose(
                type="active",
                title="Frontend handoff",
                content="Waiting on auth backend merge.",
                ctx=ctx,
                entry_id="frontend-handoff",
            )

        payload = anyio.run(run)

        assert "cannot create L0" in str(payload["error"]) or "cannot create ACTIVE" in str(
            payload["error"]
        )
        correction = payload["suggested_write_path"]
        assert correction["tool"] == "record"
        assert correction["arguments"]["type"] == "active"
        assert "Translate the developer's normal request" in payload["agent_guidance"]["write_path"]


class TestWriteAdvisories:
    def test_record_includes_write_advisories_when_duplicate_exists(self) -> None:
        from jurati.git.pr import PRResult

        state = _build_state(
            _make_entry(
                entry_id="auth-status",
                title="Auth status",
                entry_type=EntryType.PROJECT,
                level=EscalationLevel.L1,
                status=EntryStatus.PROPOSED,
                projects=["api-service"],
                pr=None,
            )
        )
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            with patch(
                "jurati.server._finish_pr_write",
                return_value=(
                    "sha123",
                    PRResult(
                        url="https://github.com/org/repo/pull/1",
                        number=1,
                        branch="jurati/new-auth-status",
                        kind="pr",
                    ),
                    None,
                ),
            ):
                return await record(
                    type="project",
                    title="Auth status",
                    content="Backend auth is ready.",
                    ctx=ctx,
                    entry_id="new-auth-status",
                    projects=["api-service"],
                )

        payload = anyio.run(run)

        assert payload["status"] == "ok"
        advisories = payload["write_advisories"]
        assert advisories["duplicates"][0]["id"] == "auth-status"
        assert advisories["expired_active"] == []
        assert "write_advisories" in payload["agent_guidance"]["debug_only_fields"]
        assert "Auth status" not in payload["developer_confirmation"]

    def test_propose_includes_write_advisories_when_duplicate_exists(self) -> None:
        from jurati.git.pr import PRResult

        state = _build_state(
            _make_entry(
                entry_id="token-format",
                title="Token format",
                entry_type=EntryType.DECISION,
                level=EscalationLevel.L2,
                projects=["api-service"],
            )
        )
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            with patch(
                "jurati.server._finish_pr_write",
                return_value=(
                    "sha456",
                    PRResult(
                        url="https://github.com/org/repo/pull/2",
                        number=2,
                        branch="jurati/new-token-format",
                        kind="pr",
                    ),
                    None,
                ),
            ):
                return await propose(
                    type="decision",
                    title="Token format v2",
                    content="Use rotation IDs.",
                    ctx=ctx,
                    entry_id="new-token-format",
                    projects=["api-service"],
                )

        payload = anyio.run(run)

        assert payload["status"] == "ok"
        advisories = payload["write_advisories"]
        assert advisories["duplicates"][0]["id"] == "token-format"
        assert "avoid repeating it" in advisories["agent_instruction"]

    def test_record_omits_write_advisories_when_clean(self) -> None:
        from jurati.git.pr import PRResult

        state = _build_state()
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            with patch(
                "jurati.server._finish_pr_write",
                return_value=(
                    "sha789",
                    PRResult(
                        url="https://github.com/org/repo/pull/3",
                        number=3,
                        branch="jurati/new-auth-status",
                        kind="pr",
                    ),
                    None,
                ),
            ):
                return await record(
                    type="project",
                    title="Auth status",
                    content="Backend auth is ready.",
                    ctx=ctx,
                    entry_id="new-auth-status",
                    projects=["api-service"],
                )

        payload = anyio.run(run)

        assert payload["status"] == "ok"
        assert "write_advisories" not in payload


class TestContentPolicyWriteIntegration:
    def test_active_record_requires_repo_policy_opt_in(self) -> None:
        state = _build_state()
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            return await record(
                type="active",
                title="Current handoff",
                content="Working on the migration.",
                ctx=ctx,
                entry_id="current-handoff",
            )

        payload = anyio.run(run)

        assert "Active context is disabled by repo policy" in payload["error"]
        assert "active_ref" not in payload

    def test_record_adds_content_review_label_for_review_verdict(self) -> None:
        from jurati.git.pr import PRResult

        state = _build_state()
        state.content_policy = WritePolicy(default_config())
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            with patch(
                "jurati.server._finish_pr_write",
                return_value=(
                    "sha123",
                    PRResult(
                        url="https://github.com/org/repo/pull/1",
                        number=1,
                        branch="jurati/project-contact",
                        kind="pr",
                    ),
                    None,
                ),
            ) as finish:
                payload = await record(
                    type="project",
                    title="Project contact",
                    content="Contact alice@example.com for migration details.",
                    ctx=ctx,
                    entry_id="project-contact",
                )
                labels = finish.call_args.kwargs["labels"]
                assert "content-review-required" in labels
                return payload

        payload = anyio.run(run)

        assert payload["status"] == "ok"
        assert payload["content_policy"]["action"] == "require_review"
        assert "pii.email" in payload["content_policy"]["policy_rules"]

    def test_propose_adds_content_warning_label_for_warning_verdict(self) -> None:
        from jurati.git.pr import PRResult

        state = _build_state()
        state.content_policy = WritePolicy(default_config())
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            with patch(
                "jurati.server._finish_pr_write",
                return_value=(
                    "sha456",
                    PRResult(
                        url="https://github.com/org/repo/pull/2",
                        number=2,
                        branch="jurati/deployment-workflow",
                        kind="pr",
                    ),
                    None,
                ),
            ) as finish:
                payload = await propose(
                    type="workflow",
                    title="Deployment workflow",
                    content="Do not ignore the failing tests before review.",
                    ctx=ctx,
                    entry_id="deployment-workflow",
                )
                labels = finish.call_args.kwargs["labels"]
                assert "content-warning" in labels
                return payload

        payload = anyio.run(run)

        assert payload["status"] == "ok"
        assert payload["content_policy"]["action"] == "allow_with_warning"

    def test_active_record_invalidates_cached_search_index(self) -> None:
        state = _build_state()
        state.config = JuratiConfig(
            remote_url="https://example.com/repo.git",
            active_refs_enabled=True,
        )
        state._cached_bm25_index = build_inverted_index([])
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            with patch("jurati.server._do_active_record", return_value="sha789"):
                return await record(
                    type="active",
                    title="Current handoff",
                    content="Working on search cache invalidation.",
                    ctx=ctx,
                    entry_id="current-handoff",
                    expires_at="2026-05-03T12:00:00+00:00",
                )

        payload = anyio.run(run)

        assert payload["status"] == "ok"
        assert state._cached_bm25_index is None

    def test_active_record_defaults_expiry_from_policy_ttl(self) -> None:
        state = _build_state()
        state.config = JuratiConfig(
            remote_url="https://example.com/repo.git",
            active_refs_enabled=True,
            active_ref_ttl_hours=2,
        )
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            with patch("jurati.server._do_active_record", return_value="sha789"):
                return await record(
                    type="active",
                    title="Current handoff",
                    content="Working on TTL defaults.",
                    ctx=ctx,
                    entry_id="current-handoff",
                )

        before = datetime.now(UTC)
        payload = anyio.run(run)
        after = datetime.now(UTC)

        assert payload["status"] == "ok"
        entry = state.index.entries["current-handoff"]
        assert entry.frontmatter.expires_at is not None
        assert before + timedelta(hours=2) <= entry.frontmatter.expires_at
        assert entry.frontmatter.expires_at <= after + timedelta(hours=2, seconds=1)

    def test_active_record_rejects_expiry_beyond_policy_ttl(self) -> None:
        state = _build_state()
        state.config = JuratiConfig(
            remote_url="https://example.com/repo.git",
            active_refs_enabled=True,
            active_ref_ttl_hours=1,
        )
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            return await record(
                type="active",
                title="Current handoff",
                content="Working on TTL caps.",
                ctx=ctx,
                entry_id="current-handoff",
                expires_at=(datetime.now(UTC) + timedelta(hours=3)).isoformat(),
            )

        payload = anyio.run(run)

        assert "expires_at exceeds repo policy TTL (1h)" in payload["error"]

    def test_active_record_rejects_invalid_policy_ttl(self) -> None:
        state = _build_state()
        state.config = JuratiConfig(
            remote_url="https://example.com/repo.git",
            active_refs_enabled=True,
            active_ref_ttl_hours=169,
        )
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            return await record(
                type="active",
                title="Current handoff",
                content="Working on TTL validation.",
                ctx=ctx,
                entry_id="current-handoff",
            )

        payload = anyio.run(run)

        assert "repo policy TTL must be between 1 and 168h" in payload["error"]


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

    def test_validate_tool_reports_unresolved_links(self) -> None:
        entry = _make_entry(entry_id="source-entry", body="See [[missing-entry]].")
        state = _build_state(entry)
        ctx = _FakeCtx(state)

        async def run() -> dict[str, object]:
            return await validate(ctx=ctx, id="source-entry")

        payload = anyio.run(run)

        assert payload["valid"] is False
        assert "unresolved wiki link to 'missing-entry'" in str(payload["errors"])


class TestCheckRemoteBranch:
    def test_returns_true_when_branch_exists(self) -> None:
        mock_ref = type("MockRef", (), {"name": "origin/jurati/test-entry"})()
        mock_repo = type("MockRepo", (), {"refs": [mock_ref]})()
        with patch.dict("sys.modules", {}), patch("git.Repo", return_value=mock_repo):
            from jurati.server import _check_remote_branch

            result = _check_remote_branch("/repo", "jurati", "test-entry")
            assert result is True

    def test_returns_false_when_branch_missing(self) -> None:
        mock_ref = type("MockRef", (), {"name": "origin/jurati/other-entry"})()
        mock_repo = type("MockRepo", (), {"refs": [mock_ref]})()
        with patch("git.Repo", return_value=mock_repo):
            from jurati.server import _check_remote_branch

            result = _check_remote_branch("/repo", "jurati", "test-entry")
            assert result is False
