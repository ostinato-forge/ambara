"""Branch naming, checkout lifecycle, and active ref management."""

from __future__ import annotations

import git


def create_branch(repo_path: str, branch_name: str, base: str = "HEAD") -> None:
    repo = git.Repo(repo_path)
    repo.git.checkout(base, b=branch_name)


def push_branch(repo_path: str, branch_name: str) -> None:
    repo = git.Repo(repo_path)
    repo.remotes.origin.push(f"{branch_name}:{branch_name}")


def push_active_ref(repo_path: str, ref_path: str, commit_sha: str) -> None:
    repo = git.Repo(repo_path)
    repo.remotes.origin.push(f"{commit_sha}:refs/heads/{ref_path}")


def delete_active_ref(repo_path: str, ref_path: str) -> None:
    repo = git.Repo(repo_path)
    repo.remotes.origin.push(f":refs/heads/{ref_path}")


def cleanup_branch(repo_path: str, branch_name: str, main_branch: str = "main") -> None:
    repo = git.Repo(repo_path)
    repo.git.checkout(main_branch)
    repo.git.branch("-D", branch_name)
