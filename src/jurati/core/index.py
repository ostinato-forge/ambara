"""Parse entries into an in-memory search index."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from jurati.core.schema import Entry
from jurati.core.validate import is_expired

if TYPE_CHECKING:
    from datetime import datetime

    from jurati.core.schema import EntryStatus, EntryType


@dataclass
class Index:
    entries: dict[str, Entry] = field(default_factory=dict)

    def add(self, entry: Entry) -> None:
        self.entries[entry.frontmatter.id] = entry

    def remove(self, entry_id: str) -> Entry | None:
        return self.entries.pop(entry_id, None)

    def get(self, entry_id: str) -> Entry | None:
        return self.entries.get(entry_id)

    def list_entries(
        self,
        *,
        now: datetime,
        entry_type: EntryType | None = None,
        project: str | None = None,
        status: EntryStatus | None = None,
        include_expired: bool = False,
    ) -> list[Entry]:
        results = list(self.entries.values())

        if not include_expired:
            results = [
                e for e in results
                if not is_expired(e, now)
            ]

        if entry_type is not None:
            results = [e for e in results if e.frontmatter.type == entry_type]
        if project is not None:
            results = [e for e in results if project in e.frontmatter.projects]
        if status is not None:
            results = [e for e in results if e.frontmatter.status == status]

        return sorted(results, key=lambda e: e.frontmatter.updated_at, reverse=True)


def parse_entry(path: str, raw_frontmatter: dict[str, Any], body: str) -> Entry:
    from jurati.core.schema import Frontmatter
    frontmatter = Frontmatter(**raw_frontmatter)
    return Entry(path=path, frontmatter=frontmatter, body=body)
