# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for ambara.git.branch."""

from __future__ import annotations

from pathlib import Path

import git
import pytest

from ambara.git.branch import (
    cleanup_branch,
    create_branch,
    delete_active_ref,
    push_active_ref,
    push_branch,
)


@pytest.fixture()
def work_repo(tmp_path: Path) -> tuple[git.Repo, git.Repo]:
    """A work repo with a bare remote, seeded with an initial commit."""
    bare_dir = tmp_path / "remote.git"
    bare = git.Repo.init(bare_dir, bare=True)

    work_dir = tmp_path / "work"
    work = git.Repo.init(work_dir)
    work.create_remote("origin", str(bare_dir))

    readme = Path(work.working_dir) / "README.md"
    readme.write_text("# test\n")
    work.index.add(["README.md"])
    work.index.commit("initial commit")
    work.git.branch("-m", work.active_branch.name, "main")
    work.remotes.origin.push("HEAD:refs/heads/main")

    return work, bare


class TestCreateBranch:
    def test_creates_and_checks_out(self, work_repo: tuple[git.Repo, git.Repo]) -> None:
        work, _ = work_repo
        create_branch(str(work.working_dir), "feat/test")
        assert work.active_branch.name == "feat/test"

    def test_reject_existing_branch(self, work_repo: tuple[git.Repo, git.Repo]) -> None:
        work, _ = work_repo
        create_branch(str(work.working_dir), "feat/test")
        work.git.checkout("main")
        with pytest.raises(git.GitCommandError):
            create_branch(str(work.working_dir), "feat/test")


class TestPushBranch:
    def test_pushes_to_remote(self, work_repo: tuple[git.Repo, git.Repo]) -> None:
        work, bare = work_repo
        create_branch(str(work.working_dir), "feat/push-test")

        test_file = Path(work.working_dir) / "test.txt"
        test_file.write_text("content")
        work.index.add(["test.txt"])
        work.index.commit("test commit")

        push_branch(str(work.working_dir), "feat/push-test")

        remote_refs = [ref.name for ref in bare.refs]
        assert "feat/push-test" in remote_refs


class TestActiveRef:
    def test_push_active_ref(self, work_repo: tuple[git.Repo, git.Repo]) -> None:
        work, bare = work_repo
        sha = work.head.commit.hexsha
        push_active_ref(str(work.working_dir), "ambara/active/client/entry-1", sha)

        remote_refs = [ref.name for ref in bare.refs]
        assert "ambara/active/client/entry-1" in remote_refs

    def test_delete_active_ref(self, work_repo: tuple[git.Repo, git.Repo]) -> None:
        work, bare = work_repo
        sha = work.head.commit.hexsha
        push_active_ref(str(work.working_dir), "ambara/active/client/entry-1", sha)
        delete_active_ref(str(work.working_dir), "ambara/active/client/entry-1")

        remote_refs = [ref.name for ref in bare.refs]
        assert "ambara/active/client/entry-1" not in remote_refs


class TestCleanupBranch:
    def test_switches_to_main_and_deletes(self, work_repo: tuple[git.Repo, git.Repo]) -> None:
        work, _ = work_repo
        create_branch(str(work.working_dir), "feat/cleanup-test")

        cleanup_branch(str(work.working_dir), "feat/cleanup-test", "main")
        assert work.active_branch.name == "main"
        assert "feat/cleanup-test" not in [b.name for b in work.branches]
