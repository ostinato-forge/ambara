# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Branch naming, checkout lifecycle, and active ref management."""

from __future__ import annotations

import random
import re
import time

import git

_SAFE_REF_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_.-]{0,250}$")


def _validate_ref(name: str, label: str = "ref") -> None:
    if ".." in name or name.endswith(".lock") or not _SAFE_REF_PATTERN.match(name):
        raise ValueError(f"Invalid {label}: {name!r}")


def _check_push(push_info: git.remote.PushInfoList) -> None:
    for info in push_info:
        if info.flags & info.ERROR:
            raise git.exc.GitCommandError("push", 128, stderr=info.summary)


def create_branch(repo_path: str, branch_name: str, base: str = "HEAD") -> None:
    _validate_ref(branch_name, "branch name")
    repo = git.Repo(repo_path)
    repo.git.checkout(base, b=branch_name)


def push_branch(repo_path: str, branch_name: str) -> None:
    repo = git.Repo(repo_path)
    _check_push(repo.remotes.origin.push(f"{branch_name}:{branch_name}"))


def push_active_ref(repo_path: str, ref_path: str, commit_sha: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise ValueError(f"Invalid commit SHA: {commit_sha!r}")
    _validate_ref(ref_path, "active ref path")
    repo = git.Repo(repo_path)
    _check_push(repo.remotes.origin.push(f"{commit_sha}:refs/heads/{ref_path}"))


def delete_active_ref(repo_path: str, ref_path: str) -> None:
    _validate_ref(ref_path, "active ref path")
    repo = git.Repo(repo_path)
    _check_push(repo.remotes.origin.push(f":refs/heads/{ref_path}"))


def cleanup_branch(repo_path: str, branch_name: str, main_branch: str = "main") -> None:
    if branch_name == main_branch:
        raise ValueError(f"Cannot cleanup main branch: {main_branch}")
    repo = git.Repo(repo_path)
    repo.git.checkout(main_branch)
    repo.git.branch("-D", branch_name)


def entry_exists_on_main(repo_path: str, entry_path: str, main_branch: str) -> bool:
    repo = git.Repo(repo_path)
    try:
        main_ref = repo.refs[f"origin/{main_branch}"]
        main_ref.commit.tree[entry_path]
        return True
    except (IndexError, KeyError):
        return False


def branch_exists_remote(repo_path: str, branch_name: str) -> bool:
    repo = git.Repo(repo_path)
    try:
        repo.refs[f"origin/{branch_name}"]
        return True
    except IndexError:
        return False


def push_branch_with_retry(repo_path: str, branch_name: str, *, max_retries: int = 3) -> None:
    for attempt in range(max_retries):
        try:
            push_branch(repo_path, branch_name)
            return
        except git.exc.GitCommandError:
            if attempt == max_retries - 1:
                raise
            delay = (2**attempt) + random.uniform(0, 1)
            time.sleep(delay)
            repo = git.Repo(repo_path)
            repo.remotes.origin.fetch()
