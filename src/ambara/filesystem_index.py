"""Load knowledge entries from a local filesystem tree."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from ambara.core.index import Index, parse_entry
from ambara.core.paths import TYPE_DIRS
from ambara.core.schema import Entry


def load_entries_from_root(root: Path) -> tuple[list[Entry], list[str]]:
    entries: list[Entry] = []
    errors: list[str] = []
    for directory in TYPE_DIRS.values():
        entry_dir = root / directory
        if not entry_dir.exists():
            continue
        for path in sorted(entry_dir.glob("*.md")):
            relative_path = path.relative_to(root).as_posix()
            try:
                post = frontmatter.load(path)
                entries.append(parse_entry(relative_path, dict(post.metadata), post.content))
            except Exception as exc:
                errors.append(f"{relative_path}: parse error: {exc}")
    return entries, errors


def load_index_from_root(root: Path) -> tuple[Index, list[str]]:
    entries, errors = load_entries_from_root(root)
    index = Index()
    for entry in entries:
        index.add(entry)
    return index, errors
