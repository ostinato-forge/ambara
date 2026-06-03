"""Safe path derivation from entry type and ID."""

from __future__ import annotations

from pathlib import Path

from ambara.core.schema import ID_PATTERN, EntryType

TYPE_DIRS: dict[EntryType, str] = {
    EntryType.PRINCIPLE: "principles",
    EntryType.DECISION: "decisions",
    EntryType.WORKFLOW: "workflows",
    EntryType.PROJECT: "projects",
    EntryType.ACTIVE: "active",
}


def entry_path(entry_type: EntryType, entry_id: str) -> str:
    if not ID_PATTERN.match(entry_id):
        raise ValueError(f"Invalid entry ID: {entry_id!r}")
    directory = TYPE_DIRS[entry_type]
    return f"{directory}/{entry_id}.md"


def active_ref(prefix: str, client: str, entry_id: str) -> str:
    if not ID_PATTERN.match(client):
        raise ValueError(f"Invalid client slug: {client!r}")
    if not ID_PATTERN.match(entry_id):
        raise ValueError(f"Invalid entry ID: {entry_id!r}")
    return f"refs/heads/{prefix}/{client}/{entry_id}"


def is_safe_path(repo_root: str, candidate: str) -> bool:
    root = Path(repo_root).resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
        return True
    except ValueError:
        return False
