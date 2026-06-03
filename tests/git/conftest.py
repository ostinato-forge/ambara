"""Shared fixtures for git integration tests."""

from __future__ import annotations

from pathlib import Path

import git
import pytest

SAMPLE_DECISION = """\
---
schema_version: 1
id: use-ruff
title: Use Ruff for linting
type: decision
level: L2
status: active
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
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

We use Ruff for all Python linting and formatting.
"""

SAMPLE_PRINCIPLE = """\
---
schema_version: 1
id: core-no-io
title: Core must not perform I/O
type: principle
level: L3
status: active
created_at: 2026-05-01T10:00:00Z
updated_at: 2026-05-01T10:00:00Z
expires_at: null
projects: []
tags: [architecture]
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: "https://github.com/example/repo/pull/2"
---

The core/ package must never import from git/ or perform I/O.
"""

SAMPLE_ACTIVE = """\
---
schema_version: 1
id: current-sprint-goal
title: Current sprint goal
type: active
level: L0
status: active
created_at: 2026-05-01T08:00:00Z
updated_at: 2026-05-01T08:00:00Z
expires_at: 2026-06-01T08:00:00Z
projects: []
tags: []
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: false
  pr: null
---

Ship ambara v1.
"""


def _commit_file(
    repo: git.Repo,
    path: str,
    content: str,
    message: str,
) -> git.Commit:
    """Write a file and commit it to the repo."""
    full_path = Path(repo.working_dir) / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    repo.index.add([path])
    return repo.index.commit(message)


@pytest.fixture()
def bare_remote(tmp_path: Path) -> git.Repo:
    """An empty bare git repo acting as the remote."""
    return git.Repo.init(tmp_path / "remote.git", bare=True)


@pytest.fixture()
def seeded_remote(tmp_path: Path) -> git.Repo:
    """A bare remote seeded with sample entries on main."""
    work_dir = tmp_path / "seed-work"
    bare_dir = tmp_path / "remote.git"
    bare = git.Repo.init(bare_dir, bare=True)

    work = git.Repo.init(work_dir)
    work.create_remote("origin", str(bare_dir))

    _commit_file(work, "decisions/use-ruff.md", SAMPLE_DECISION, "add decision")
    _commit_file(work, "principles/core-no-io.md", SAMPLE_PRINCIPLE, "add principle")

    work.remotes.origin.push("HEAD:refs/heads/main")

    return bare


@pytest.fixture()
def seeded_remote_with_active(seeded_remote: git.Repo, tmp_path: Path) -> git.Repo:
    """A bare remote with main entries and an active overlay ref."""
    work_dir = tmp_path / "active-work"
    work = git.Repo.clone_from(str(seeded_remote.common_dir), work_dir)

    _commit_file(work, "active/current-sprint-goal.md", SAMPLE_ACTIVE, "add active entry")
    work.remotes.origin.push("HEAD:refs/heads/ambara/active/test-client/current-sprint-goal")

    return seeded_remote


@pytest.fixture()
def cache_dir(tmp_path: Path) -> Path:
    """An empty cache directory."""
    d = tmp_path / "cache"
    d.mkdir()
    return d
