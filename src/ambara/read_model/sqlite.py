"""SQLite/FTS derived read model for Ambara entries."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ambara.core.schema import Entry, EntryStatus, EntryType, Sensitivity, Visibility
from ambara.core.scoring import tokenize
from ambara.filesystem_index import load_entries_from_root

SCHEMA_VERSION = 1
DEFAULT_DB_NAME = "read-model.sqlite3"


@dataclass(frozen=True)
class RebuildResult:
    db_path: Path
    entries_indexed: int
    entries_skipped_restricted: int
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReadModelResult:
    id: str
    title: str
    type: str
    status: str
    visibility: str
    path: str
    updated_at: str
    projects: tuple[str, ...]
    tags: tuple[str, ...]
    snippet: str
    score: float


def default_db_path(knowledge_repo: Path) -> Path:
    return knowledge_repo / ".ambara" / DEFAULT_DB_NAME


def rebuild_read_model(knowledge_repo: Path, *, db_path: Path | None = None) -> RebuildResult:
    root = knowledge_repo.resolve()
    target = db_path.resolve() if db_path is not None else default_db_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)

    entries, errors = load_entries_from_root(root)
    indexable = [
        entry for entry in entries if entry.frontmatter.sensitivity != Sensitivity.RESTRICTED
    ]

    _remove_database_files(target)

    with sqlite3.connect(target) as conn:
        _create_schema(conn)
        _insert_metadata(conn)
        _insert_entries(conn, indexable)
        conn.commit()

    return RebuildResult(
        db_path=target,
        entries_indexed=len(indexable),
        entries_skipped_restricted=len(entries) - len(indexable),
        errors=tuple(errors),
    )


def query_read_model(
    db_path: Path,
    query: str,
    *,
    now: datetime,
    entry_type: EntryType | None = None,
    project: str | None = None,
    status: EntryStatus | None = None,
    visibility: Visibility | None = None,
    include_expired: bool = False,
    limit: int = 10,
) -> list[ReadModelResult]:
    if limit <= 0:
        return []
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    fts_query = _fts_query(query)
    if not fts_query:
        return []

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
              e.id,
              e.title,
              e.type,
              e.status,
              e.visibility,
              e.path,
              e.updated_at,
              e.expires_at,
              e.projects,
              e.tags,
              snippet(entries_fts, 2, '<mark>', '</mark>', '...', 32) AS snippet,
              bm25(entries_fts) AS score
            FROM entries_fts
            JOIN entries e ON e.rowid = entries_fts.rowid
            WHERE entries_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (fts_query, limit * 4),
        ).fetchall()

    results: list[ReadModelResult] = []
    for row in rows:
        if entry_type is not None and row["type"] != str(entry_type):
            continue
        if status is not None and row["status"] != str(status):
            continue
        if visibility is not None and row["visibility"] != str(visibility):
            continue

        projects = tuple(json.loads(row["projects"]))
        if project is not None and project not in projects:
            continue

        if not include_expired and _row_is_expired(row, now):
            continue

        results.append(
            ReadModelResult(
                id=row["id"],
                title=row["title"],
                type=row["type"],
                status=row["status"],
                visibility=row["visibility"],
                path=row["path"],
                updated_at=row["updated_at"],
                projects=projects,
                tags=tuple(json.loads(row["tags"])),
                snippet=row["snippet"],
                score=float(row["score"]),
            )
        )
        if len(results) >= limit:
            break

    return results


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE entries (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          type TEXT NOT NULL,
          level TEXT NOT NULL,
          status TEXT NOT NULL,
          path TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          expires_at TEXT,
          projects TEXT NOT NULL,
          tags TEXT NOT NULL,
          visibility TEXT NOT NULL,
          body TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE entries_fts USING fts5(
          title,
          tags,
          body,
          content='entries',
          content_rowid='rowid'
        );
        """
    )


def _insert_metadata(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO metadata(key, value) VALUES (?, ?)",
        [
            ("schema_version", str(SCHEMA_VERSION)),
            ("source", "derived"),
        ],
    )


def _insert_entries(conn: sqlite3.Connection, entries: list[Entry]) -> None:
    for entry in entries:
        fm = entry.frontmatter
        cursor = conn.execute(
            """
            INSERT INTO entries(
              id,
              title,
              type,
              level,
              status,
              path,
              created_at,
              updated_at,
              expires_at,
              projects,
              tags,
              visibility,
              body
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fm.id,
                fm.title,
                str(fm.type),
                str(fm.level),
                str(fm.status),
                entry.path,
                fm.created_at.isoformat(),
                fm.updated_at.isoformat(),
                fm.expires_at.isoformat() if fm.expires_at else None,
                json.dumps(fm.projects),
                json.dumps(fm.tags),
                str(fm.visibility),
                entry.body,
            ),
        )
        conn.execute(
            "INSERT INTO entries_fts(rowid, title, tags, body) VALUES (?, ?, ?, ?)",
            (cursor.lastrowid, fm.title, " ".join(fm.tags), entry.body),
        )


def _row_is_expired(row: sqlite3.Row, now: datetime) -> bool:
    expires_at = row["expires_at"]
    if expires_at is None:
        return False
    value = datetime.fromisoformat(expires_at)
    if value.tzinfo is None and now.tzinfo is not None:
        value = value.replace(tzinfo=now.tzinfo)
    return now >= value


def _fts_query(value: str) -> str:
    tokens = tokenize(value)
    return " OR ".join(f'"{token}"' for token in tokens)


def _remove_database_files(target: Path) -> None:
    for path in (
        target,
        target.with_name(f"{target.name}-wal"),
        target.with_name(f"{target.name}-shm"),
    ):
        if path.exists():
            path.unlink()
