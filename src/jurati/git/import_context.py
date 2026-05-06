"""Materialize context-pack import plans into review branches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import git

from jurati.core.import_context import ImportPlan
from jurati.core.paths import is_safe_path
from jurati.git.branch import create_branch


@dataclass(frozen=True)
class ImportWriteResult:
    branch: str
    commit: str
    created_paths: tuple[str, ...]


def materialize_context_import(
    repo_path: str,
    plan: ImportPlan,
    *,
    branch: str,
    base: str = "HEAD",
    message: str | None = None,
) -> ImportWriteResult:
    if not plan.valid:
        raise ValueError("Cannot write an invalid context import plan")

    creates = [action for action in plan.actions if action.action == "create"]
    if not creates:
        raise ValueError("Context import plan has no entries to create")

    repo = git.Repo(repo_path)
    if repo.is_dirty(untracked_files=True):
        raise ValueError("Knowledge repo working tree must be clean before import")

    create_branch(repo_path, branch, base)

    created_paths: list[str] = []
    for action in creates:
        if action.destination_path is None or action.content is None:
            raise ValueError(f"Import action is missing rendered content: {action.source_path}")
        if not is_safe_path(repo_path, action.destination_path):
            raise ValueError(f"Path traversal rejected: {action.destination_path!r}")

        full_path = Path(repo.working_dir) / action.destination_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(action.content)
        created_paths.append(action.destination_path)

    repo.index.add(created_paths)
    commit = repo.index.commit(message or f"feat(kb): import context pack {plan.bundle_name}")
    return ImportWriteResult(
        branch=branch,
        commit=commit.hexsha,
        created_paths=tuple(created_paths),
    )
