# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Privacy regression tests — ensure ambara produces no telemetry."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

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

NOW = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)


def _make_entry(entry_id: str = "test-entry") -> Entry:
    return Entry(
        path=f"decisions/{entry_id}.md",
        frontmatter=Frontmatter(
            id=entry_id,
            title="Test decision",
            type=EntryType.DECISION,
            level=EscalationLevel.L2,
            status=EntryStatus.ACTIVE,
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            updated_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            review=ReviewMeta(required=True, pr="https://github.com/org/repo/pull/1"),
        ),
        body="Decision body.",
    )


class TestNoTelemetry:
    def test_query_produces_no_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        index = Index()
        index.add(_make_entry())
        core_query(index, "test", now=NOW)

        created = list(tmp_path.rglob("*"))
        assert len(created) == 0

    def test_index_operations_produce_no_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        index = Index()
        entry = _make_entry()
        index.add(entry)
        index.get("test-entry")
        index.list_entries(now=NOW)
        index.remove("test-entry")

        created = list(tmp_path.rglob("*"))
        assert len(created) == 0

    def test_no_query_text_in_index(self) -> None:
        index = Index()
        index.add(_make_entry())
        core_query(index, "secret-search-term", now=NOW)

        index_repr = str(index.entries)
        assert "secret-search-term" not in index_repr

    def test_match_reasons_do_not_store_query_text(self) -> None:
        index = Index()
        index.add(_make_entry())

        results = core_query(index, "test", now=NOW)

        assert results
        assert "test" not in str(results[0].match_reasons)


class TestAuthPrivacy:
    def test_auth_candidate_has_no_token_field(self) -> None:
        from ambara.git.auth import AuthCandidate

        c = AuthCandidate(method="api_token", source="env_ambara", owner="o", repo="r")
        field_names = [f.name for f in c.__dataclass_fields__.values()]
        assert "token" not in field_names

    def test_pr_result_has_no_auth_field(self) -> None:
        from ambara.git.pr import PRResult

        r = PRResult(url=None, number=None, branch="b", kind="branch")
        field_names = [f.name for f in r.__dataclass_fields__.values()]
        assert "auth_method" not in field_names
        assert "auth_user" not in field_names
        assert "auth_fallback_used" not in field_names

    def test_branch_only_receipt_has_no_auth_info(self) -> None:
        from ambara.server import _write_receipt

        receipt = _write_receipt(
            entry_id="test",
            write_mode="branch_only",
            branch="ambara/test",
            commit="abc",
        )
        receipt_str = str(receipt).lower()
        assert "auth" not in receipt_str
        assert "token" not in receipt_str
        assert "fallback" not in receipt_str

    def test_status_payload_has_no_auth_section(self) -> None:
        import threading
        from datetime import UTC, datetime

        from ambara.core.index import Index
        from ambara.git.config import AmbaraConfig
        from ambara.server import ServerState, SyncHealth, _state_status_payload

        index = Index()
        index.add(_make_entry())
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        state = ServerState(
            config=AmbaraConfig(
                remote_url="git@github.com:org/repo.git",
                cache_dir="/tmp/test",
                main_branch="main",
                active_ref_prefix="ambara/active",
                client_slug="test",
            ),
            repo_path="/tmp/test",
            index=index,
            last_sync=now,
            sync_health=SyncHealth(last_success=now),
            write_lock=threading.Lock(),
        )
        payload = _state_status_payload(state)
        payload_str = str(payload).lower()
        assert "auth_status" not in payload_str
        assert "pr_capability" not in payload_str
