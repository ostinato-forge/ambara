"""Offline capture queue for the git hook."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

_PENDING_DIR = "jurati-pending"
_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")

logger = logging.getLogger(__name__)


def _validate_sha(commit_sha: str) -> None:
    if not _SHA_PATTERN.match(commit_sha):
        raise ValueError(f"Invalid commit SHA: {commit_sha!r}")


def _pending_path(git_dir: str) -> Path:
    return Path(git_dir) / _PENDING_DIR


def save_pending(
    git_dir: str,
    commit_sha: str,
    message: str,
    *,
    author: str | None = None,
    repo_slug: str | None = None,
) -> None:
    _validate_sha(commit_sha)
    pending_dir = _pending_path(git_dir)
    pending_dir.mkdir(exist_ok=True)
    marker = pending_dir / f"{commit_sha}.json"
    payload = {"commit_sha": commit_sha, "message": message}
    if author is not None:
        payload["author"] = author
    if repo_slug is not None:
        payload["repo_slug"] = repo_slug
    marker.write_text(json.dumps(payload))


def list_pending(git_dir: str) -> list[dict[str, str]]:
    pending_dir = _pending_path(git_dir)
    if not pending_dir.exists():
        return []
    results = []
    for marker in sorted(pending_dir.glob("*.json")):
        try:
            data = json.loads(marker.read_text())
            results.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping corrupt pending file %s: %s", marker, exc)
    return results


def remove_pending(git_dir: str, commit_sha: str) -> None:
    _validate_sha(commit_sha)
    marker = _pending_path(git_dir) / f"{commit_sha}.json"
    if marker.exists():
        marker.unlink()
