"""Tests for jurati.git.repo."""

from __future__ import annotations

import os
from pathlib import Path

import git

from jurati.git.repo import (
    ensure_repo,
    fetch_all,
    get_main_tree_hash,
    load_index_from_repo,
    repo_cache_path,
)


class TestRepoCachePath:
    def test_deterministic(self) -> None:
        url = "https://github.com/org/repo.git"
        p1 = repo_cache_path(url, "/tmp/cache")
        p2 = repo_cache_path(url, "/tmp/cache")
        assert p1 == p2

    def test_different_urls_different_paths(self) -> None:
        p1 = repo_cache_path("https://github.com/org/a.git", "/cache")
        p2 = repo_cache_path("https://github.com/org/b.git", "/cache")
        assert p1 != p2

    def test_path_under_cache_dir(self) -> None:
        path = repo_cache_path("https://example.com/repo.git", "/my/cache")
        assert path.startswith("/my/cache/")


class TestEnsureRepo:
    def test_clones_from_remote(self, bare_remote: git.Repo, cache_dir: Path) -> None:
        path = ensure_repo(str(bare_remote.common_dir), str(cache_dir))
        assert os.path.isdir(os.path.join(path, ".git"))
        cloned = git.Repo(path)
        assert "origin" in [r.name for r in cloned.remotes]

    def test_reuses_existing_clone(self, bare_remote: git.Repo, cache_dir: Path) -> None:
        url = str(bare_remote.common_dir)
        path1 = ensure_repo(url, str(cache_dir))
        path2 = ensure_repo(url, str(cache_dir))
        assert path1 == path2

    def test_creates_cache_dir(self, bare_remote: git.Repo, tmp_path: Path) -> None:
        new_cache = tmp_path / "does" / "not" / "exist"
        path = ensure_repo(str(bare_remote.common_dir), str(new_cache))
        assert os.path.isdir(path)


class TestFetchAll:
    def test_fetches_main_branch(self, seeded_remote: git.Repo, cache_dir: Path) -> None:
        url = str(seeded_remote.common_dir)
        repo_path = ensure_repo(url, str(cache_dir))
        fetch_all(repo_path)

        repo = git.Repo(repo_path)
        main = repo.commit("origin/main")
        tree_names = [item.name for item in main.tree]
        assert "decisions" in tree_names
        assert "principles" in tree_names

    def test_fetches_active_refs(
        self, seeded_remote_with_active: git.Repo, cache_dir: Path
    ) -> None:
        url = str(seeded_remote_with_active.common_dir)
        repo_path = ensure_repo(url, str(cache_dir))
        fetch_all(repo_path)

        repo = git.Repo(repo_path)
        ref_paths = [str(r) for r in repo.refs]
        active_refs = [r for r in ref_paths if "jurati/active" in r]
        assert len(active_refs) > 0


class TestLoadIndex:
    def test_loads_main_entries(self, seeded_remote: git.Repo, cache_dir: Path) -> None:
        url = str(seeded_remote.common_dir)
        repo_path = ensure_repo(url, str(cache_dir))
        fetch_all(repo_path)

        index = load_index_from_repo(repo_path)
        assert index.get("use-ruff") is not None
        assert index.get("core-no-io") is not None

    def test_entry_fields_parsed(self, seeded_remote: git.Repo, cache_dir: Path) -> None:
        url = str(seeded_remote.common_dir)
        repo_path = ensure_repo(url, str(cache_dir))
        fetch_all(repo_path)

        index = load_index_from_repo(repo_path)
        entry = index.get("use-ruff")
        assert entry is not None
        assert entry.frontmatter.title == "Use Ruff for linting"
        assert entry.frontmatter.type == "decision"
        assert entry.frontmatter.level == "L2"
        assert entry.path == "decisions/use-ruff.md"

    def test_overlays_active_refs(
        self, seeded_remote_with_active: git.Repo, cache_dir: Path
    ) -> None:
        url = str(seeded_remote_with_active.common_dir)
        repo_path = ensure_repo(url, str(cache_dir))
        fetch_all(repo_path)

        index = load_index_from_repo(repo_path)
        assert index.get("use-ruff") is not None
        active = index.get("current-sprint-goal")
        assert active is not None
        assert active.frontmatter.type == "active"

    def test_active_ref_overwrites_main_entry(
        self, seeded_remote: git.Repo, cache_dir: Path, tmp_path: Path
    ) -> None:
        work_dir = tmp_path / "overlay-work"
        work = git.Repo.clone_from(str(seeded_remote.common_dir), work_dir)

        updated = """\
---
schema_version: 1
id: use-ruff
title: Use Ruff for linting (updated via active ref)
type: decision
level: L2
status: active
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-02T12:00:00Z
expires_at: null
projects: []
tags: [tooling]
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: "https://github.com/example/repo/pull/1"
---

Updated body from active ref.
"""
        entry_path = Path(work.working_dir) / "decisions" / "use-ruff.md"
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        entry_path.write_text(updated)
        work.index.add(["decisions/use-ruff.md"])
        work.index.commit("update via active ref")
        work.remotes.origin.push("HEAD:refs/heads/jurati/active/test-client/use-ruff")

        url = str(seeded_remote.common_dir)
        repo_path = ensure_repo(url, str(cache_dir))
        fetch_all(repo_path)

        index = load_index_from_repo(repo_path)
        entry = index.get("use-ruff")
        assert entry is not None
        assert "updated via active ref" in entry.frontmatter.title

    def test_skips_malformed_entries(
        self, seeded_remote: git.Repo, cache_dir: Path, tmp_path: Path
    ) -> None:
        work_dir = tmp_path / "add-bad"
        work = git.Repo.clone_from(str(seeded_remote.common_dir), work_dir)

        bad_path = Path(work.working_dir) / "decisions" / "bad-entry.md"
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("not valid frontmatter at all {{{{")
        work.index.add(["decisions/bad-entry.md"])
        work.index.commit("add malformed entry")
        work.remotes.origin.push("HEAD:refs/heads/main")

        url = str(seeded_remote.common_dir)
        repo_path = ensure_repo(url, str(cache_dir))
        fetch_all(repo_path)

        index = load_index_from_repo(repo_path)
        assert index.get("bad-entry") is None
        assert index.get("use-ruff") is not None

    def test_tree_hash_detects_no_change(self, seeded_remote: git.Repo, cache_dir: Path) -> None:
        remote_url = str(seeded_remote.common_dir)
        repo_path = ensure_repo(remote_url, str(cache_dir))
        fetch_all(repo_path)

        hash1 = get_main_tree_hash(repo_path, "main")
        fetch_all(repo_path)
        hash2 = get_main_tree_hash(repo_path, "main")
        assert hash1 == hash2

    def test_tree_hash_detects_change(
        self, seeded_remote: git.Repo, cache_dir: Path, tmp_path: Path
    ) -> None:
        remote_url = str(seeded_remote.common_dir)
        repo_path = ensure_repo(remote_url, str(cache_dir))
        fetch_all(repo_path)
        hash1 = get_main_tree_hash(repo_path, "main")

        work_dir = tmp_path / "tree-change"
        work = git.Repo.clone_from(str(seeded_remote.common_dir), work_dir)
        (Path(work.working_dir) / "new-file.md").write_text("new content")
        work.index.add(["new-file.md"])
        work.index.commit("add new file")
        work.remotes.origin.push(refspec="HEAD:refs/heads/main", force=True)

        fetch_all(repo_path)
        hash2 = get_main_tree_hash(repo_path, "main")
        assert hash1 != hash2

    def test_empty_repo(self, bare_remote: git.Repo, cache_dir: Path, tmp_path: Path) -> None:
        work_dir = tmp_path / "init-work"
        work = git.Repo.init(work_dir)
        work.create_remote("origin", str(bare_remote.common_dir))
        readme = Path(work.working_dir) / "README.md"
        readme.write_text("# Empty knowledge repo\n")
        work.index.add(["README.md"])
        work.index.commit("initial commit")
        work.remotes.origin.push("HEAD:refs/heads/main")

        url = str(bare_remote.common_dir)
        repo_path = ensure_repo(url, str(cache_dir))
        fetch_all(repo_path)

        index = load_index_from_repo(repo_path)
        assert len(index.entries) == 0
