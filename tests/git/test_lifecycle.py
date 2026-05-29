"""Tests for review-branch lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import frontmatter
import git

from jurati.core.scope_policy import ScopeMutePolicy
from jurati.git.lifecycle import collect_retire_scope_matches, materialize_retire_scope

NOW = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)


def _init_repo(path: Path) -> git.Repo:
    repo = git.Repo.init(path)
    with repo.config_writer() as writer:
        writer.set_value("user", "name", "Jurati Test")
        writer.set_value("user", "email", "jurati-test@example.com")
    return repo


def _write_entry(
    root: Path,
    relative_path: str,
    *,
    entry_id: str,
    title: str,
    entry_type: str,
    level: str,
    projects: list[str],
    expires_at: str | None = None,
) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    expires = f"expires_at: {expires_at}\n" if expires_at is not None else "expires_at: null\n"
    path.write_text(
        f"""---
schema_version: 1
id: {entry_id}
title: {title}
type: {entry_type}
level: {level}
status: active
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
{expires}projects: {projects}
tags: []
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: false
  pr: null
---

{title} body.
"""
    )


def test_materialize_retire_scope_expires_matching_entries_on_review_branch(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _write_entry(
        tmp_path,
        "active/au0035l-handoff.md",
        entry_id="au0035l-handoff",
        title="AU0035L handoff",
        entry_type="active",
        level="L0",
        projects=["AU0035L"],
        expires_at="2026-06-01T12:00:00Z",
    )
    _write_entry(
        tmp_path,
        "projects/au0035l-summary.md",
        entry_id="au0035l-summary",
        title="AU0035L summary",
        entry_type="project",
        level="L1",
        projects=["AU0035L"],
    )
    _write_entry(
        tmp_path,
        "projects/current-summary.md",
        entry_id="current-summary",
        title="Current summary",
        entry_type="project",
        level="L1",
        projects=["current"],
    )
    repo.index.add(
        [
            "active/au0035l-handoff.md",
            "projects/au0035l-summary.md",
            "projects/current-summary.md",
        ]
    )
    repo.index.commit("seed entries")
    policy = ScopeMutePolicy(projects=("au0035l",))

    matches = collect_retire_scope_matches(str(tmp_path), policy)
    result = materialize_retire_scope(
        str(tmp_path),
        policy,
        branch="jurati/retire-test",
        now=NOW,
    )

    assert {match.entry_id for match in matches} == {"au0035l-handoff", "au0035l-summary"}
    assert result.branch == "jurati/retire-test"
    assert len(result.matches) == 2
    assert (tmp_path / result.report_path).exists()
    active_post = frontmatter.load(tmp_path / "active/au0035l-handoff.md")
    project_post = frontmatter.load(tmp_path / "projects/au0035l-summary.md")
    current_post = frontmatter.load(tmp_path / "projects/current-summary.md")
    assert active_post.metadata["status"] == "expired"
    assert active_post.metadata["expires_at"] == "2026-05-29T12:00:00Z"
    assert project_post.metadata["status"] == "expired"
    assert current_post.metadata["status"] == "active"
