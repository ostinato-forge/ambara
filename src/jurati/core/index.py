"""Parse frontmatter and build in-memory search index."""

from __future__ import annotations

from dataclasses import dataclass, field

from jurati.core.schema import Entry, EntryType, EntryStatus, Frontmatter


@dataclass
class Index:
    entries: dict[str, Entry] = field(default_factory=dict)

    def add(self, entry: Entry) -> None:
        self.entries[entry.path] = entry

    def remove(self, path: str) -> Entry | None:
        return self.entries.pop(path, None)

    def get(self, path: str) -> Entry | None:
        return self.entries.get(path)

    def list_entries(
        self,
        *,
        entry_type: EntryType | None = None,
        project: str | None = None,
        status: EntryStatus | None = None,
    ) -> list[Entry]:
        results = list(self.entries.values())
        if entry_type is not None:
            results = [e for e in results if e.frontmatter.type == entry_type]
        if project is not None:
            results = [e for e in results if project in e.frontmatter.projects]
        if status is not None:
            results = [e for e in results if e.frontmatter.status == status]
        return sorted(results, key=lambda e: e.frontmatter.date, reverse=True)


def parse_entry(path: str, raw_frontmatter: dict, body: str) -> Entry:
    frontmatter = Frontmatter(**raw_frontmatter)
    return Entry(path=path, frontmatter=frontmatter, body=body)
