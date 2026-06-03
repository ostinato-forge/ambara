"""Tests for review-branch lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import frontmatter
import git

from ambara.core.schema import EntryType, EscalationLevel
from ambara.core.scope_policy import ScopeMutePolicy
from ambara.git.lifecycle import (
    ClearEntriesFilter,
    collect_clear_entries_matches,
    collect_retire_scope_matches,
    materialize_clear_entries,
    materialize_retire_scope,
)

NOW = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)


def _init_repo(path: Path) -> git.Repo:
    repo = git.Repo.init(path)
    with repo.config_writer() as writer:
        writer.set_value("user", "name", "Ambara Test")
        writer.set_value("user", "email", "ambara-test@example.com")
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
    status: str = "active",
    tags: list[str] | None = None,
    sensitivity: str = "normal",
    expires_at: str | None = None,
    source_repo: str | None = None,
) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    expires = f"expires_at: {expires_at}\n" if expires_at is not None else "expires_at: null\n"
    source = (
        f"source:\n  repo: {source_repo}\n  commit: abc123\n"
        if source_repo is not None
        else "source: null\n"
    )
    path.write_text(
        f"""---
schema_version: 1
id: {entry_id}
title: {title}
type: {entry_type}
level: {level}
status: {status}
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
{expires}projects: {projects}
tags: {tags or []}
supersedes: []
superseded_by: null
sensitivity: {sensitivity}
review:
  required: false
  pr: null
{source}
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
        "active/legacy-proj-handoff.md",
        entry_id="legacy-proj-handoff",
        title="LEGACY-PROJ handoff",
        entry_type="active",
        level="L0",
        projects=["LEGACY-PROJ"],
        expires_at="2026-06-01T12:00:00Z",
    )
    _write_entry(
        tmp_path,
        "projects/legacy-proj-summary.md",
        entry_id="legacy-proj-summary",
        title="LEGACY-PROJ summary",
        entry_type="project",
        level="L1",
        projects=["LEGACY-PROJ"],
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
            "active/legacy-proj-handoff.md",
            "projects/legacy-proj-summary.md",
            "projects/current-summary.md",
        ]
    )
    repo.index.commit("seed entries")
    policy = ScopeMutePolicy(projects=("legacy-proj",))

    matches = collect_retire_scope_matches(str(tmp_path), policy)
    result = materialize_retire_scope(
        str(tmp_path),
        policy,
        branch="ambara/retire-test",
        now=NOW,
    )

    assert {match.entry_id for match in matches} == {"legacy-proj-handoff", "legacy-proj-summary"}
    assert result.branch == "ambara/retire-test"
    assert len(result.matches) == 2
    assert (tmp_path / result.report_path).exists()
    active_post = frontmatter.load(tmp_path / "active/legacy-proj-handoff.md")
    project_post = frontmatter.load(tmp_path / "projects/legacy-proj-summary.md")
    current_post = frontmatter.load(tmp_path / "projects/current-summary.md")
    assert active_post.metadata["status"] == "expired"
    assert active_post.metadata["expires_at"] == "2026-05-29T12:00:00Z"
    assert project_post.metadata["status"] == "expired"
    assert current_post.metadata["status"] == "active"


def test_collect_clear_entries_filters_by_type_level_project_repo_and_tag(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _write_entry(
        tmp_path,
        "projects/matching.md",
        entry_id="matching-entry",
        title="Matching entry",
        entry_type="project",
        level="L1",
        projects=["LEGACY-PROJ"],
        tags=["cleanup"],
        source_repo="org/api",
    )
    _write_entry(
        tmp_path,
        "projects/wrong-repo.md",
        entry_id="wrong-repo",
        title="Wrong repo",
        entry_type="project",
        level="L1",
        projects=["LEGACY-PROJ"],
        tags=["cleanup"],
        source_repo="org/web",
    )
    _write_entry(
        tmp_path,
        "decisions/wrong-type.md",
        entry_id="wrong-type",
        title="Wrong type",
        entry_type="decision",
        level="L2",
        projects=["LEGACY-PROJ"],
        tags=["cleanup"],
        source_repo="org/api",
    )
    repo.index.add(
        [
            "projects/matching.md",
            "projects/wrong-repo.md",
            "decisions/wrong-type.md",
        ]
    )
    repo.index.commit("seed entries")

    matches = collect_clear_entries_matches(
        str(tmp_path),
        ClearEntriesFilter(
            entry_types=(EntryType.PROJECT,),
            levels=(EscalationLevel.L1,),
            projects=("legacy-proj",),
            repos=("org/api",),
            tags=("cleanup",),
        ),
    )

    assert [match.entry_id for match in matches] == ["matching-entry"]


def test_materialize_clear_entries_expires_all_non_restricted_current_entries(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _write_entry(
        tmp_path,
        "active/current-handoff.md",
        entry_id="current-handoff",
        title="Current handoff",
        entry_type="active",
        level="L0",
        projects=["demo"],
        expires_at="2026-06-01T12:00:00Z",
    )
    _write_entry(
        tmp_path,
        "projects/current-project.md",
        entry_id="current-project",
        title="Current project",
        entry_type="project",
        level="L1",
        projects=["demo"],
    )
    _write_entry(
        tmp_path,
        "projects/restricted-project.md",
        entry_id="restricted-project",
        title="Restricted project",
        entry_type="project",
        level="L1",
        projects=["demo"],
        sensitivity="restricted",
    )
    _write_entry(
        tmp_path,
        "projects/already-expired.md",
        entry_id="already-expired",
        title="Already expired",
        entry_type="project",
        level="L1",
        projects=["demo"],
        status="expired",
    )
    repo.index.add(
        [
            "active/current-handoff.md",
            "projects/current-project.md",
            "projects/restricted-project.md",
            "projects/already-expired.md",
        ]
    )
    repo.index.commit("seed entries")

    result = materialize_clear_entries(
        str(tmp_path),
        ClearEntriesFilter(),
        branch="ambara/clear-test",
        now=NOW,
    )

    assert {match.entry_id for match in result.matches} == {"current-handoff", "current-project"}
    assert repo.active_branch.name == "ambara/clear-test"
    assert (tmp_path / result.report_path).exists()
    active_post = frontmatter.load(tmp_path / "active/current-handoff.md")
    project_post = frontmatter.load(tmp_path / "projects/current-project.md")
    restricted_post = frontmatter.load(tmp_path / "projects/restricted-project.md")
    expired_post = frontmatter.load(tmp_path / "projects/already-expired.md")
    assert active_post.metadata["status"] == "expired"
    assert active_post.metadata["expires_at"] == "2026-05-29T12:00:00Z"
    assert project_post.metadata["status"] == "expired"
    assert restricted_post.metadata["status"] == "active"
    assert expired_post.metadata["status"] == "expired"


def test_clear_entries_can_include_restricted_entries(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_entry(
        tmp_path,
        "projects/restricted-project.md",
        entry_id="restricted-project",
        title="Restricted project",
        entry_type="project",
        level="L1",
        projects=["demo"],
        sensitivity="restricted",
    )
    repo.index.add(["projects/restricted-project.md"])
    repo.index.commit("seed entries")

    matches = collect_clear_entries_matches(
        str(tmp_path),
        ClearEntriesFilter(include_restricted=True),
    )

    assert [match.entry_id for match in matches] == ["restricted-project"]
    result = materialize_clear_entries(
        str(tmp_path),
        ClearEntriesFilter(include_restricted=True),
        branch="ambara/clear-restricted",
        now=NOW,
    )
    report = (tmp_path / result.report_path).read_text()
    assert "- restricted entries included" in report
