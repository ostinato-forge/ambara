"""Offline capture queue for the git hook."""

from __future__ import annotations

import json
from pathlib import Path

_PENDING_DIR = "jurati-pending"


def _pending_path(git_dir: str) -> Path:
    return Path(git_dir) / _PENDING_DIR


def save_pending(git_dir: str, commit_sha: str, message: str) -> None:
    pending_dir = _pending_path(git_dir)
    pending_dir.mkdir(exist_ok=True)
    marker = pending_dir / f"{commit_sha}.json"
    marker.write_text(json.dumps({"commit_sha": commit_sha, "message": message}))


def list_pending(git_dir: str) -> list[dict[str, str]]:
    pending_dir = _pending_path(git_dir)
    if not pending_dir.exists():
        return []
    results = []
    for marker in sorted(pending_dir.glob("*.json")):
        data = json.loads(marker.read_text())
        results.append(data)
    return results


def remove_pending(git_dir: str, commit_sha: str) -> None:
    marker = _pending_path(git_dir) / f"{commit_sha}.json"
    if marker.exists():
        marker.unlink()
