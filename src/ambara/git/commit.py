# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Materialize planned changes (WriteIntent/ExpireIntent) into git commits."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import frontmatter
import git

from ambara.core.changes import ExpireIntent, WriteIntent
from ambara.core.events import EventRecord
from ambara.core.paths import is_safe_path
from ambara.core.schema import EntryStatus


def _materialize_event(repo: git.Repo, event: EventRecord | None) -> None:
    if event is None:
        return
    event_path = event.path()
    event_full = Path(repo.working_dir) / event_path
    event_full.parent.mkdir(parents=True, exist_ok=True)
    event_full.write_text(event.to_json())
    repo.index.add([event_path])


def commit_index(repo: git.Repo, message: str) -> git.Commit:
    """Create an Ambara-managed commit without invoking ambient Git hooks."""

    return repo.index.commit(message, skip_hooks=True)


def materialize_write(repo_path: str, intent: WriteIntent) -> str:
    if not is_safe_path(repo_path, intent.path):
        raise ValueError(f"Path traversal rejected: {intent.path!r}")

    repo = git.Repo(repo_path)
    full_path = Path(repo.working_dir) / intent.path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(intent.content)
    repo.index.add([intent.path])

    _materialize_event(repo, intent.event)

    message = f"feat(kb): add {intent.entry_id}"
    commit = commit_index(repo, message)
    return commit.hexsha


def materialize_expire(
    repo_path: str,
    intent: ExpireIntent,
    now: datetime,
) -> str:
    if not is_safe_path(repo_path, intent.path):
        raise ValueError(f"Path traversal rejected: {intent.path!r}")

    repo = git.Repo(repo_path)
    full_path = Path(repo.working_dir) / intent.path

    raw = full_path.read_text()
    post = frontmatter.loads(raw)
    post.metadata["status"] = str(EntryStatus.EXPIRED)
    post.metadata["updated_at"] = now.isoformat()

    full_path.write_text(frontmatter.dumps(post))
    repo.index.add([intent.path])

    _materialize_event(repo, intent.event)

    message = f"chore(kb): expire {intent.entry_id}"
    commit = commit_index(repo, message)
    return commit.hexsha
