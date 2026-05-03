"""Tests for jurati.git.commit."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import git
import pytest

from jurati.core.changes import ExpireIntent, WriteIntent
from jurati.core.schema import EntryStatus, EscalationLevel
from jurati.git.commit import materialize_expire, materialize_write


@pytest.fixture()
def work_repo(tmp_path: Path) -> git.Repo:
    """A work repo with an initial commit."""
    work_dir = tmp_path / "work"
    work = git.Repo.init(work_dir)
    readme = Path(work.working_dir) / "README.md"
    readme.write_text("# test\n")
    work.index.add(["README.md"])
    work.index.commit("initial commit")
    return work


def _make_write_intent(
    *,
    entry_id: str = "test-entry",
    path: str = "decisions/test-entry.md",
    content: str = "---\nid: test-entry\n---\nTest body\n",
    branch: str = "jurati/test-entry",
    write_mode: str = "review_pr",
    level: EscalationLevel = EscalationLevel.L2,
) -> WriteIntent:
    return WriteIntent(
        path=path,
        content=content,
        branch=branch,
        write_mode=write_mode,
        entry_id=entry_id,
        level=level,
    )


class TestMaterializeWrite:
    def test_creates_file_and_commit(self, work_repo: git.Repo) -> None:
        intent = _make_write_intent()
        sha = materialize_write(str(work_repo.working_dir), intent)

        assert len(sha) == 40
        file_path = Path(work_repo.working_dir) / "decisions/test-entry.md"
        assert file_path.exists()
        assert "Test body" in file_path.read_text()

    def test_creates_parent_dirs(self, work_repo: git.Repo) -> None:
        intent = _make_write_intent(path="workflows/new-workflow.md", entry_id="new-workflow")
        materialize_write(str(work_repo.working_dir), intent)

        file_path = Path(work_repo.working_dir) / "workflows/new-workflow.md"
        assert file_path.exists()

    def test_rejects_path_traversal(self, work_repo: git.Repo) -> None:
        intent = _make_write_intent(path="../../../etc/passwd")
        with pytest.raises(ValueError, match="Path traversal rejected"):
            materialize_write(str(work_repo.working_dir), intent)

    def test_commit_message_format(self, work_repo: git.Repo) -> None:
        intent = _make_write_intent(entry_id="my-decision")
        materialize_write(str(work_repo.working_dir), intent)

        msg = work_repo.head.commit.message
        assert "feat(kb): add my-decision" in msg


class TestMaterializeExpire:
    @pytest.fixture()
    def repo_with_entry(self, work_repo: git.Repo) -> git.Repo:
        """Work repo with an existing active decision entry."""
        content = """\
---
schema_version: 1
id: old-decision
title: Old decision
type: decision
level: L2
status: active
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
expires_at: null
projects: []
tags: []
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: "https://github.com/example/repo/pull/1"
---

This is the old decision body.
"""
        entry_path = Path(work_repo.working_dir) / "decisions/old-decision.md"
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        entry_path.write_text(content)
        work_repo.index.add(["decisions/old-decision.md"])
        work_repo.index.commit("add old decision")
        return work_repo

    def test_updates_status_and_timestamp(self, repo_with_entry: git.Repo) -> None:
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        intent = ExpireIntent(
            entry_id="old-decision",
            path="decisions/old-decision.md",
            write_mode="review_pr",
            branch="jurati/expire-old-decision",
            new_status=EntryStatus.EXPIRED,
        )

        sha = materialize_expire(str(repo_with_entry.working_dir), intent, now)
        assert len(sha) == 40

        import frontmatter as fm

        file_path = Path(repo_with_entry.working_dir) / "decisions/old-decision.md"
        post = fm.loads(file_path.read_text())
        assert post.metadata["status"] == "expired"
        assert "2026-05-02" in str(post.metadata["updated_at"])

    def test_commit_message_format(self, repo_with_entry: git.Repo) -> None:
        now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        intent = ExpireIntent(
            entry_id="old-decision",
            path="decisions/old-decision.md",
            write_mode="review_pr",
            branch="jurati/expire-old-decision",
            new_status=EntryStatus.EXPIRED,
        )

        materialize_expire(str(repo_with_entry.working_dir), intent, now)
        msg = repo_with_entry.head.commit.message
        assert "chore(kb): expire old-decision" in msg
