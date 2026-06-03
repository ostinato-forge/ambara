"""Wiki-link graph helpers for Ambara entries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ambara.core.schema import ID_PATTERN, Sensitivity

if TYPE_CHECKING:
    from ambara.core.index import Index
    from ambara.core.schema import Entry


_WIKI_LINK_RE = re.compile(r"(?<!!)\[\[([^\]\n]+)\]\]")
_FENCED_CODE_RE = re.compile(r"(^|\n)(```|~~~).*?(?:\n\2(?=\n|$)|$)", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


@dataclass(frozen=True)
class WikiLink:
    raw: str
    target: str
    label: str | None = None


@dataclass(frozen=True)
class BrokenLink:
    source_id: str
    source_path: str
    target: str
    raw: str
    reason: str


@dataclass(frozen=True)
class EntryGraph:
    outgoing: dict[str, tuple[str, ...]]
    backlinks: dict[str, tuple[str, ...]]
    broken: tuple[BrokenLink, ...]
    restricted_entry_ids: frozenset[str]

    def links_for(self, entry_id: str) -> dict[str, Any]:
        return {
            "outgoing": list(self.outgoing.get(entry_id, ())),
            "backlinks": list(self.backlinks.get(entry_id, ())),
            "broken": [
                {
                    "target": broken.target,
                    "raw": broken.raw,
                    "reason": broken.reason,
                }
                for broken in self.broken
                if broken.source_id == entry_id
            ],
        }


def parse_wiki_links(body: str) -> tuple[WikiLink, ...]:
    links: list[WikiLink] = []
    linkable_body = _mask_code(body)
    for match in _WIKI_LINK_RE.finditer(linkable_body):
        raw = match.group(0)
        inner = match.group(1).strip()
        if not inner:
            continue
        target_part, _, label_part = inner.partition("|")
        target = target_part.split("#", 1)[0].strip()
        if not target:
            continue
        label = label_part.strip() or None
        links.append(WikiLink(raw=raw, target=target, label=label))
    return tuple(links)


def _mask_code(body: str) -> str:
    masked = _FENCED_CODE_RE.sub(lambda match: _spaces(match.group(0)), body)
    return _INLINE_CODE_RE.sub(lambda match: _spaces(match.group(0)), masked)


def _spaces(value: str) -> str:
    return "".join("\n" if char == "\n" else " " for char in value)


def build_entry_graph(index: Index) -> EntryGraph:
    known_ids = set(index.entries)
    outgoing: dict[str, list[str]] = {entry_id: [] for entry_id in known_ids}
    backlinks: dict[str, list[str]] = {entry_id: [] for entry_id in known_ids}
    broken: list[BrokenLink] = []

    for entry in index.entries.values():
        source_id = entry.frontmatter.id
        for link in parse_wiki_links(entry.body):
            if not ID_PATTERN.match(link.target):
                broken.append(_broken(entry, link, "invalid_id"))
                continue
            if link.target not in known_ids:
                broken.append(_broken(entry, link, "unresolved"))
                continue
            _append_unique(outgoing[source_id], link.target)
            _append_unique(backlinks[link.target], source_id)

    return EntryGraph(
        outgoing={key: tuple(value) for key, value in outgoing.items()},
        backlinks={key: tuple(value) for key, value in backlinks.items()},
        broken=tuple(broken),
        restricted_entry_ids=frozenset(
            entry.frontmatter.id
            for entry in index.entries.values()
            if entry.frontmatter.sensitivity == Sensitivity.RESTRICTED
        ),
    )


def validate_entry_links(index: Index, *, entry_id: str | None = None) -> list[str]:
    return validate_graph_links(build_entry_graph(index), entry_id=entry_id)


def validate_graph_links(graph: EntryGraph, *, entry_id: str | None = None) -> list[str]:
    errors: list[str] = []

    for broken in graph.broken:
        if entry_id is not None and broken.source_id != entry_id:
            continue
        if broken.reason == "invalid_id":
            errors.append(
                f"{broken.source_path}: wiki link target {broken.target!r} is not a valid entry id"
            )
        else:
            errors.append(f"{broken.source_path}: unresolved wiki link to {broken.target!r}")

    return errors


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _broken(entry: Entry, link: WikiLink, reason: str) -> BrokenLink:
    return BrokenLink(
        source_id=entry.frontmatter.id,
        source_path=entry.path,
        target=link.target,
        raw=link.raw,
        reason=reason,
    )
