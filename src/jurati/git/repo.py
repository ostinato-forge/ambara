"""Clone, fetch, and index loading for the knowledge repo."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import frontmatter
import git

from jurati.core.index import Index, parse_entry
from jurati.core.paths import TYPE_DIRS

logger = logging.getLogger(__name__)

_ENTRY_DIRS = set(TYPE_DIRS.values())


def repo_cache_path(remote_url: str, cache_dir: str) -> str:
    url_hash = hashlib.sha256(remote_url.encode()).hexdigest()[:16]
    return os.path.join(cache_dir, url_hash)


def ensure_repo(remote_url: str, cache_dir: str) -> str:
    path = repo_cache_path(remote_url, cache_dir)
    if os.path.isdir(os.path.join(path, ".git")):
        return path
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    git.Repo.clone_from(remote_url, path)
    return path


def fetch_all(
    repo_path: str,
    main_branch: str = "main",
    active_ref_prefix: str = "jurati/active",
) -> None:
    repo = git.Repo(repo_path)
    origin = repo.remotes.origin
    origin.fetch(f"+refs/heads/{main_branch}:refs/remotes/origin/{main_branch}", prune=True)
    origin.fetch(
        f"+refs/heads/{active_ref_prefix}/*:refs/remotes/origin/{active_ref_prefix}/*", prune=True
    )


def get_main_tree_hash(repo_path: str, main_branch: str = "main") -> str:
    repo = git.Repo(repo_path)
    ref = repo.refs[f"origin/{main_branch}"]
    return ref.commit.tree.hexsha


def load_index_from_repo(
    repo_path: str,
    main_branch: str = "main",
    active_ref_prefix: str = "jurati/active",
) -> Index:
    repo = git.Repo(repo_path)
    index = Index()

    main_commit = repo.commit(f"origin/{main_branch}")
    _load_entries_from_tree(main_commit.tree, index)

    _overlay_active_refs(repo, active_ref_prefix, index)

    return index


def _load_entries_from_tree(tree: git.Tree, index: Index) -> None:
    for item in tree:
        if item.type == "tree" and item.name in _ENTRY_DIRS:
            _load_dir(item, item.name, index)


def _load_dir(tree: git.Tree, dir_name: str, index: Index) -> None:
    for blob in tree:
        if blob.type != "blob" or not blob.name.endswith(".md"):
            continue
        path = f"{dir_name}/{blob.name}"
        _parse_and_add(path, blob, index)


def _parse_and_add(path: str, blob: git.Blob, index: Index) -> None:
    try:
        raw = blob.data_stream.read().decode("utf-8")
        post = frontmatter.loads(raw)
        entry = parse_entry(path, dict(post.metadata), post.content)
        index.add(entry)
    except Exception:
        logger.warning("Skipping malformed entry: %s", path, exc_info=True)


def _overlay_active_refs(
    repo: git.Repo,
    active_ref_prefix: str,
    index: Index,
) -> None:
    prefix = f"refs/remotes/origin/{active_ref_prefix}/"
    for ref in repo.refs:
        ref_path = ref.path
        if not ref_path.startswith(prefix):
            continue
        try:
            commit = ref.commit
            _load_entries_from_tree(commit.tree, index)
        except Exception:
            logger.warning("Skipping malformed active ref: %s", ref_path, exc_info=True)
