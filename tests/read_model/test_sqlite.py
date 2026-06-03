# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ambara.core.changes import render_entry
from ambara.core.paths import entry_path
from ambara.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
    Sensitivity,
    Visibility,
)
from ambara.read_model.sqlite import (
    default_db_path,
    query_read_model,
    rebuild_read_model,
)

NOW = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)


def _entry(
    *,
    entry_id: str,
    title: str,
    body: str,
    entry_type: EntryType = EntryType.PROJECT,
    level: EscalationLevel = EscalationLevel.L1,
    status: EntryStatus = EntryStatus.PROPOSED,
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
    visibility: Visibility = Visibility.INTERNAL,
    expires_at: datetime | None = None,
) -> Entry:
    fm = Frontmatter(
        id=entry_id,
        title=title,
        type=entry_type,
        level=level,
        status=status,
        created_at=NOW - timedelta(days=1),
        updated_at=NOW,
        expires_at=expires_at,
        projects=projects or [],
        tags=tags or [],
        sensitivity=sensitivity,
        visibility=visibility,
        review=ReviewMeta(required=level != EscalationLevel.L0),
    )
    return Entry(path=entry_path(entry_type, entry_id), frontmatter=fm, body=body)


def _write_entry(root: Path, entry: Entry) -> None:
    path = root / entry.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_entry(entry.frontmatter, entry.body))


def test_rebuild_read_model_creates_sqlite_fts_store(tmp_path: Path) -> None:
    repo = tmp_path / "knowledge"
    _write_entry(
        repo,
        _entry(
            entry_id="api-service",
            title="API Service",
            body="Handles request validation.",
            projects=["api"],
            tags=["service"],
        ),
    )

    result = rebuild_read_model(repo)

    assert result.db_path == default_db_path(repo)
    assert result.entries_indexed == 1
    assert result.entries_skipped_restricted == 0
    with sqlite3.connect(result.db_path) as conn:
        assert conn.execute("SELECT value FROM metadata WHERE key='source'").fetchone()[0] == (
            "derived"
        )
        assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 1


def test_query_read_model_filters_restricted_and_expired_entries(tmp_path: Path) -> None:
    repo = tmp_path / "knowledge"
    _write_entry(
        repo,
        _entry(
            entry_id="public-api",
            title="Public API",
            body="Validate API request bodies.",
            projects=["api"],
        ),
    )
    _write_entry(
        repo,
        _entry(
            entry_id="restricted-api",
            title="Restricted API",
            body="Secret API request details.",
            sensitivity=Sensitivity.RESTRICTED,
        ),
    )
    _write_entry(
        repo,
        _entry(
            entry_id="expired-api",
            title="Expired API",
            body="Old API request context.",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            expires_at=NOW - timedelta(hours=1),
        ),
    )

    result = rebuild_read_model(repo)
    matches = query_read_model(result.db_path, "API request", now=NOW)

    assert result.entries_indexed == 2
    assert result.entries_skipped_restricted == 1
    assert [item.id for item in matches] == ["public-api"]
    assert query_read_model(result.db_path, "Secret", now=NOW, include_expired=True) == []
    with sqlite3.connect(result.db_path) as conn:
        indexed_ids = {
            row[0] for row in conn.execute("SELECT id FROM entries ORDER BY id").fetchall()
        }
    assert "restricted-api" not in indexed_ids


def test_query_read_model_can_filter_type_project_status_and_include_expired(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "knowledge"
    _write_entry(
        repo,
        _entry(
            entry_id="api-workflow",
            title="API Workflow",
            body="API validation workflow.",
            entry_type=EntryType.WORKFLOW,
            level=EscalationLevel.L2,
            status=EntryStatus.ACTIVE,
            projects=["api"],
        ),
    )
    _write_entry(
        repo,
        _entry(
            entry_id="web-project",
            title="Web Project",
            body="API validation consumer.",
            status=EntryStatus.PROPOSED,
            projects=["web"],
        ),
    )
    _write_entry(
        repo,
        _entry(
            entry_id="expired-api",
            title="Expired API",
            body="API validation handoff.",
            entry_type=EntryType.ACTIVE,
            level=EscalationLevel.L0,
            status=EntryStatus.ACTIVE,
            projects=["api"],
            expires_at=NOW - timedelta(hours=1),
        ),
    )
    _write_entry(
        repo,
        _entry(
            entry_id="external-api",
            title="External API",
            body="API validation external guidance.",
            visibility=Visibility.EXTERNAL,
        ),
    )

    result = rebuild_read_model(repo)

    workflows = query_read_model(
        result.db_path,
        "API validation",
        now=NOW,
        entry_type=EntryType.WORKFLOW,
        project="api",
        status=EntryStatus.ACTIVE,
    )
    with_expired = query_read_model(
        result.db_path,
        "API validation",
        now=NOW,
        include_expired=True,
    )
    external = query_read_model(
        result.db_path,
        "API validation",
        now=NOW,
        visibility=Visibility.EXTERNAL,
    )

    assert [item.id for item in workflows] == ["api-workflow"]
    assert "expired-api" in {item.id for item in with_expired}
    assert [item.id for item in external] == ["external-api"]
