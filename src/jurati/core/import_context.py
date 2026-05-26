"""Context-pack import planning."""

from __future__ import annotations

import re
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import frontmatter
from pydantic import BaseModel, Field, ValidationError

from jurati.core.changes import render_entry
from jurati.core.graph import validate_entry_links
from jurati.core.index import Index, parse_entry
from jurati.core.paths import TYPE_DIRS, entry_path
from jurati.core.schema import (
    DEFAULT_LEVEL_MAP,
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    ReviewMeta,
    Sensitivity,
    Visibility,
)
from jurati.core.secrets import scan_secrets
from jurati.core.validate import validate_entry


class ContextPackError(ValueError):
    """Raised when a context pack cannot be read as a bundle."""


class ContextPackItem(BaseModel):
    path: str
    category: str
    id: str | None = None
    title: str | None = None
    type: EntryType | None = None
    level: EscalationLevel | None = None
    projects: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    sensitivity: Sensitivity = Sensitivity.NORMAL
    visibility: Visibility = Visibility.INTERNAL
    personal: bool = False
    local_only: bool = False
    skip: bool = False
    skip_reason: str | None = None
    reject_reason: str | None = None


class ContextPackManifest(BaseModel):
    schema_version: int = 1
    name: str
    items: list[ContextPackItem]


@dataclass(frozen=True)
class ImportAction:
    action: str
    source_path: str
    category: str
    reason: str
    entry_id: str | None = None
    entry_type: EntryType | None = None
    level: EscalationLevel | None = None
    destination_path: str | None = None
    title: str | None = None
    errors: tuple[str, ...] = ()
    content: str | None = None
    entry: Entry | None = None


@dataclass(frozen=True)
class ImportPlan:
    bundle_name: str
    actions: tuple[ImportAction, ...]
    errors: tuple[str, ...] = ()
    source_label: str = "Context pack"
    source_tag: str = "context-pack"
    branch_prefix: str = "jurati/import-context"
    commit_message_prefix: str = "feat(kb): import context pack"

    @property
    def create_count(self) -> int:
        return _count(self.actions, "create")

    @property
    def skip_count(self) -> int:
        return _count(self.actions, "skip")

    @property
    def reject_count(self) -> int:
        return _count(self.actions, "reject")

    @property
    def valid(self) -> bool:
        return not self.errors and self.reject_count == 0


@dataclass(frozen=True)
class _ObsidianNote:
    source_path: str
    raw: str
    item: ContextPackItem
    aliases: tuple[str, ...]
    title: str


_CATEGORY_DEFAULTS: dict[str, tuple[EntryType, EscalationLevel]] = {
    "repo profile": (EntryType.PROJECT, EscalationLevel.L1),
    "repository profile": (EntryType.PROJECT, EscalationLevel.L1),
    "project": (EntryType.PROJECT, EscalationLevel.L1),
    "tool note": (EntryType.WORKFLOW, EscalationLevel.L2),
    "tool": (EntryType.WORKFLOW, EscalationLevel.L2),
    "error pattern": (EntryType.WORKFLOW, EscalationLevel.L2),
    "error": (EntryType.WORKFLOW, EscalationLevel.L2),
    "decision": (EntryType.DECISION, EscalationLevel.L2),
    "learning": (EntryType.PROJECT, EscalationLevel.L1),
    "query": (EntryType.WORKFLOW, EscalationLevel.L2),
    "workflow": (EntryType.WORKFLOW, EscalationLevel.L2),
    "principle": (EntryType.PRINCIPLE, EscalationLevel.L3),
}

_LOCAL_PATH_PARTS = {"local", "personal", "private", "scratch", "tmp", "secrets"}
_OBSIDIAN_SKIP_PATH_PARTS = {
    "daily",
    "daily note",
    "daily notes",
    "journal",
    "journals",
    "template",
    "templates",
}
_OBSIDIAN_ATTACHMENT_SUFFIXES = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".svg",
    ".webp",
}
_OBSIDIAN_EMBED_RE = re.compile(r"!\[\[([^\]\n]+)\]\]")
_OBSIDIAN_WIKI_LINK_RE = re.compile(r"(?<!!)\[\[([^\]\n]+)\]\]")
_OBSIDIAN_TAG_RE = re.compile(r"(?<![\w/])#([A-Za-z0-9][A-Za-z0-9_/-]*)")
_OBSIDIAN_DOCTYPE_CATEGORIES = {
    "ai decision": "decision",
    "ai error pattern": "error pattern",
    "ai learning": "learning",
    "ai principle": "principle",
    "ai repo profile": "project",
    "ai tool note": "tool note",
    "ai workflow": "workflow",
}


def plan_context_import(
    bundle_path: Path,
    *,
    knowledge_repo: Path,
    now: datetime,
) -> ImportPlan:
    manifest, notes = _read_bundle(bundle_path)
    return _plan_manifest_import(manifest, notes, knowledge_repo=knowledge_repo, now=now)


def plan_markdown_import(
    source_paths: Sequence[Path],
    *,
    knowledge_repo: Path,
    now: datetime,
    mode: str = "adr",
    projects: Sequence[str] = (),
    tags: Sequence[str] = (),
    source_root: Path | None = None,
) -> ImportPlan:
    """Plan an import from allowlisted local Markdown files or directories."""
    if not source_paths:
        raise ContextPackError("at least one source path is required")

    if mode == "obsidian":
        return plan_obsidian_import(
            source_paths,
            knowledge_repo=knowledge_repo,
            now=now,
            projects=projects,
            tags=tags,
            source_root=source_root,
        )

    category, mode_tags = _markdown_import_mode(mode)
    notes: dict[str, str] = {}
    items: list[ContextPackItem] = []
    display_root = source_root.resolve() if source_root is not None else None

    for source in source_paths:
        fallback_root = _source_fallback_root(source)
        for path in _iter_markdown_files(source):
            try:
                raw = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ContextPackError(f"could not read {path} as UTF-8: {exc}") from exc
            except OSError as exc:
                raise ContextPackError(f"could not read {path}: {exc}") from exc

            source_path = _source_display_path(path, display_root, fallback_root)
            if source_path in notes:
                raise ContextPackError(
                    f"duplicate Markdown source path after normalization: {source_path}"
                )
            notes[source_path] = raw
            title = _first_markdown_heading(raw)
            items.append(
                ContextPackItem(
                    path=source_path,
                    category=category,
                    title=title,
                    projects=list(projects),
                    tags=[*mode_tags, *tags],
                )
            )

    if not items:
        raise ContextPackError("no Markdown files found in source paths")

    manifest = ContextPackManifest(
        name=f"{mode} markdown",
        items=items,
    )
    return _plan_manifest_import(
        manifest,
        notes,
        knowledge_repo=knowledge_repo,
        now=now,
        source_label="Markdown import",
        source_tag="markdown-import",
        branch_prefix="jurati/import-docs",
        commit_message_prefix="feat(kb): import",
    )


def plan_obsidian_import(
    source_paths: Sequence[Path],
    *,
    knowledge_repo: Path,
    now: datetime,
    projects: Sequence[str] = (),
    tags: Sequence[str] = (),
    source_root: Path | None = None,
) -> ImportPlan:
    """Plan an import from allowlisted Obsidian vault notes."""
    if not source_paths:
        raise ContextPackError("at least one source path is required")

    notes: dict[str, str] = {}
    items: list[ContextPackItem] = []
    obsidian_notes: list[_ObsidianNote] = []
    display_root = source_root.resolve() if source_root is not None else None
    seen_paths: set[str] = set()

    for source in source_paths:
        fallback_root = _source_fallback_root(source)
        for path in _iter_obsidian_files(source):
            source_path = _source_display_path(path, display_root, fallback_root)
            if source_path in seen_paths:
                raise ContextPackError(
                    f"duplicate Obsidian source path after normalization: {source_path}"
                )
            seen_paths.add(source_path)

            suffix = path.suffix.lower()
            if suffix == ".md":
                raw = _read_source_text(path)
                metadata, content = _source_metadata_and_content(raw)
                title = _obsidian_title(path, raw, metadata)
                category = _obsidian_category(path, metadata)
                entry_id = _string_metadata(metadata, "jurati_id") or _string_metadata(
                    metadata, "id"
                )
                aliases = tuple(_metadata_strings(metadata, "aliases", "alias"))
                item = ContextPackItem(
                    path=source_path,
                    category=category,
                    id=entry_id or _obsidian_entry_id(title, source_path),
                    title=title,
                    projects=list(projects),
                    tags=[
                        "obsidian",
                        *tags,
                        *_obsidian_tags(metadata, content),
                        *_obsidian_folder_tags(source_path),
                    ],
                    skip_reason=_obsidian_skip_reason(path),
                    reject_reason=_obsidian_reject_reason(raw),
                )
                obsidian_notes.append(
                    _ObsidianNote(
                        source_path=source_path,
                        raw=raw,
                        item=item,
                        aliases=aliases,
                        title=title,
                    )
                )
                items.append(item)
                continue

            items.append(_obsidian_unsupported_item(path, source_path))

    if not items:
        raise ContextPackError("no Obsidian files found in source paths")

    link_targets = _obsidian_link_targets(obsidian_notes)
    for note in obsidian_notes:
        notes[note.source_path] = _prepare_obsidian_note(
            note.raw,
            source_path=note.source_path,
            aliases=note.aliases,
            title=note.title,
            link_targets=link_targets,
        )

    manifest = ContextPackManifest(
        name="obsidian vault",
        items=items,
    )
    return _plan_manifest_import(
        manifest,
        notes,
        knowledge_repo=knowledge_repo,
        now=now,
        source_label="Obsidian import",
        source_tag="obsidian-import",
        branch_prefix="jurati/import-obsidian",
        commit_message_prefix="feat(kb): import obsidian",
    )


def _plan_manifest_import(
    manifest: ContextPackManifest,
    notes: dict[str, str],
    *,
    knowledge_repo: Path,
    now: datetime,
    source_label: str = "Context pack",
    source_tag: str = "context-pack",
    branch_prefix: str = "jurati/import-context",
    commit_message_prefix: str = "feat(kb): import context pack",
) -> ImportPlan:
    existing_index, existing_errors = _load_existing_index(knowledge_repo)
    existing_ids = set(existing_index.entries)
    prospective_index = Index(entries=dict(existing_index.entries))

    actions: list[ImportAction] = []
    created_by_id: dict[str, str] = {}

    for item in manifest.items:
        action = _plan_item(
            item,
            notes=notes,
            manifest=manifest,
            existing_ids=existing_ids,
            created_by_id=created_by_id,
            now=now,
            source_label=source_label,
            source_tag=source_tag,
        )
        if action.action == "create" and action.entry is not None:
            created_by_id[action.entry.frontmatter.id] = item.path
            prospective_index.add(action.entry)
        actions.append(action)

    actions = _apply_link_validation(actions, prospective_index)
    return ImportPlan(
        bundle_name=manifest.name,
        actions=tuple(actions),
        errors=tuple(existing_errors),
        source_label=source_label,
        source_tag=source_tag,
        branch_prefix=branch_prefix,
        commit_message_prefix=commit_message_prefix,
    )


def default_import_branch(plan: ImportPlan) -> str:
    return f"{plan.branch_prefix}-{_slug(plan.bundle_name)}"


def _markdown_import_mode(mode: str) -> tuple[str, list[str]]:
    if mode == "adr":
        return "decision", ["adr"]
    if mode == "rfc":
        return "decision", ["rfc"]
    if mode == "docs":
        return "project", ["docs"]
    raise ContextPackError(f"unknown markdown import mode {mode!r}")


def _iter_markdown_files(source: Path) -> list[Path]:
    if source.is_file():
        if source.suffix.lower() != ".md":
            raise ContextPackError(f"{source} is not a Markdown file")
        return [source]
    if source.is_dir():
        source_root = source.resolve()
        return [
            path
            for path in sorted(source.rglob("*.md"))
            if not _has_hidden_relative_part(path, source_root)
        ]
    raise ContextPackError(f"source path does not exist: {source}")


def _iter_obsidian_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    if source.is_dir():
        source_root = source.resolve()
        return [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file() and not _has_hidden_relative_part(path, source_root)
        ]
    raise ContextPackError(f"source path does not exist: {source}")


def _read_source_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ContextPackError(f"could not read {path} as UTF-8: {exc}") from exc
    except OSError as exc:
        raise ContextPackError(f"could not read {path}: {exc}") from exc


def _has_hidden_relative_part(path: Path, source_root: Path) -> bool:
    try:
        parts = path.resolve().relative_to(source_root).parts
    except ValueError:
        parts = path.parts
    return any(part.startswith(".") for part in parts)


def _source_fallback_root(source: Path) -> Path:
    return source.resolve().parent


def _source_display_path(
    path: Path,
    source_root: Path | None,
    fallback_root: Path,
) -> str:
    resolved = path.resolve()
    for root in (source_root, fallback_root):
        if root is None:
            continue
        try:
            return resolved.relative_to(root).as_posix()
        except ValueError:
            continue
    return path.name


def _first_markdown_heading(raw: str) -> str | None:
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            return title or None
    return None


def _source_metadata_and_content(raw: str) -> tuple[dict[str, Any], str]:
    try:
        post = frontmatter.loads(raw)
    except Exception:
        return {}, raw
    return dict(post.metadata), post.content


def _obsidian_title(path: Path, raw: str, metadata: dict[str, Any]) -> str:
    return (
        _string_metadata(metadata, "title")
        or _first_markdown_heading(raw)
        or _title_from_path(path.as_posix())
    )


def _obsidian_category(path: Path, metadata: dict[str, Any]) -> str:
    doctype = _string_metadata(metadata, "doctype")
    if doctype is not None:
        mapped = _OBSIDIAN_DOCTYPE_CATEGORIES.get(_normalize_category(doctype))
        if mapped is not None:
            return mapped

    explicit = (
        _string_metadata(metadata, "jurati_category")
        or _string_metadata(metadata, "category")
        or _string_metadata(metadata, "jurati_type")
        or _string_metadata(metadata, "type")
    )
    if explicit is not None and _normalize_category(explicit) in _CATEGORY_DEFAULTS:
        return explicit

    parts = {_normalize_path_part(part) for part in path.with_suffix("").parts}
    if parts.intersection({"principle", "principles"}):
        return "principle"
    if parts.intersection({"decision", "decisions", "adr", "adrs"}):
        return "decision"
    if parts.intersection({"workflow", "workflows", "runbook", "runbooks", "process"}):
        return "workflow"
    return "project"


def _obsidian_entry_id(title: str, source_path: str) -> str:
    if title:
        return _slug_text(title)
    return _slug(source_path)


def _obsidian_tags(metadata: dict[str, Any], content: str) -> list[str]:
    values = [
        *_metadata_strings(metadata, "tags", "tag", split=True),
        *[match.group(1) for match in _OBSIDIAN_TAG_RE.finditer(content)],
    ]
    return list(dict.fromkeys(tag for value in values if (tag := _normalize_tag(value))))


def _obsidian_folder_tags(source_path: str) -> list[str]:
    parent = PurePosixPath(source_path).parent
    if parent == PurePosixPath("."):
        return []
    return [
        f"folder-{folder}"
        for part in parent.parts
        if (folder := _normalize_tag(part)) and folder not in _OBSIDIAN_SKIP_PATH_PARTS
    ]


def _obsidian_skip_reason(path: Path) -> str | None:
    parts = {_normalize_path_part(part) for part in path.parts}
    if parts.intersection(_OBSIDIAN_SKIP_PATH_PARTS):
        return "default Obsidian daily note or template source"
    return None


def _obsidian_reject_reason(raw: str) -> str | None:
    if _OBSIDIAN_EMBED_RE.search(raw):
        return "Obsidian embeds are unsupported"
    return None


def _obsidian_unsupported_item(path: Path, source_path: str) -> ContextPackItem:
    suffix = path.suffix.lower()
    if suffix == ".canvas":
        return ContextPackItem(
            path=source_path,
            category="canvas",
            skip=True,
            skip_reason="Obsidian Canvas files are unsupported",
        )
    return ContextPackItem(
        path=source_path,
        category="attachment",
        skip=True,
        skip_reason=(
            "Obsidian attachments are unsupported"
            if suffix in _OBSIDIAN_ATTACHMENT_SUFFIXES
            else "non-Markdown Obsidian file skipped"
        ),
    )


def _obsidian_link_targets(notes: Sequence[_ObsidianNote]) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for note in notes:
        if note.item.id is None:
            continue
        for key in _obsidian_link_keys(note):
            candidates.setdefault(key, set()).add(note.item.id)
    return {key: next(iter(ids)) for key, ids in candidates.items() if len(ids) == 1}


def _obsidian_link_keys(note: _ObsidianNote) -> set[str]:
    source = PurePosixPath(note.source_path)
    without_suffix = source.with_suffix("").as_posix()
    keys = {
        source.stem,
        without_suffix,
        note.title,
        *note.aliases,
    }
    return {_normalize_obsidian_link_target(key) for key in keys if key}


def _prepare_obsidian_note(
    raw: str,
    *,
    source_path: str,
    aliases: Sequence[str],
    title: str,
    link_targets: dict[str, str],
) -> str:
    try:
        post = frontmatter.loads(raw)
    except Exception:
        return raw

    body = _rewrite_obsidian_wikilinks(post.content, link_targets)
    body = _append_obsidian_metadata(
        body,
        source_path=source_path,
        aliases=aliases,
        title=title,
        metadata=dict(post.metadata),
    )
    if not post.metadata:
        return body

    rewritten = frontmatter.Post(body)
    rewritten.metadata.update(post.metadata)
    rendered: str = frontmatter.dumps(rewritten)
    return rendered


def _rewrite_obsidian_wikilinks(body: str, link_targets: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        target_part, separator, label_part = inner.partition("|")
        target_without_heading = target_part.split("#", 1)[0].strip()
        normalized = _normalize_obsidian_link_target(target_without_heading)
        replacement = link_targets.get(normalized)
        if replacement is None:
            return match.group(0)
        label = label_part.strip() if separator else target_part.strip()
        if label and label != replacement:
            return f"[[{replacement}|{label}]]"
        return f"[[{replacement}]]"

    return _OBSIDIAN_WIKI_LINK_RE.sub(replace, body)


def _append_obsidian_metadata(
    body: str,
    *,
    source_path: str,
    aliases: Sequence[str],
    title: str,
    metadata: dict[str, Any],
) -> str:
    folder = PurePosixPath(source_path).parent.as_posix()
    provenance = [
        "## Obsidian Metadata",
        "",
        f"- Note title: {title}",
    ]
    if folder != ".":
        provenance.append(f"- Folder: {folder}")
    if aliases:
        provenance.append(f"- Aliases: {', '.join(aliases)}")

    unsupported_keys = sorted(
        key
        for key in metadata
        if key
        not in {
            "alias",
            "aliases",
            "category",
            "id",
            "jurati_category",
            "jurati_id",
            "jurati_type",
            "tag",
            "tags",
            "title",
            "type",
        }
    )
    if unsupported_keys:
        provenance.append(
            "- Unsupported properties reported during review: " + ", ".join(unsupported_keys)
        )

    body = body.strip()
    section = "\n".join(provenance)
    if not body:
        return section
    return f"{body}\n\n{section}"


def _normalize_obsidian_link_target(value: str) -> str:
    target = value.split("#", 1)[0].strip().removesuffix(".md")
    return re.sub(r"\s+", " ", target).casefold()


def _metadata_strings(
    metadata: dict[str, Any],
    *keys: str,
    split: bool = False,
) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str):
            values.extend(_split_metadata_string(value) if split else [value.strip()])
        elif isinstance(value, list):
            values.extend(item.strip() for item in value if isinstance(item, str))
    return [value for value in values if value]


def _split_metadata_string(value: str) -> list[str]:
    normalized = value.replace(",", " ")
    return [item.strip() for item in normalized.split() if item.strip()]


def _normalize_tag(value: str) -> str:
    tag = value.strip().lstrip("#").replace("/", "-")
    tag = re.sub(r"[^A-Za-z0-9_-]+", "-", tag).strip("-").lower()
    return tag


def _normalize_path_part(value: str) -> str:
    return value.strip().lower().replace("_", " ").replace("-", " ")


def _read_bundle(bundle_path: Path) -> tuple[ContextPackManifest, dict[str, str]]:
    if not tarfile.is_tarfile(bundle_path):
        raise ContextPackError(f"{bundle_path} is not a tar archive")

    try:
        with tarfile.open(bundle_path, "r:*") as tar:
            members = [member for member in tar.getmembers() if member.isfile()]
            member_map = _normalized_member_map(members)
            if "manifest.json" not in member_map:
                raise ContextPackError("context pack must contain manifest.json")

            manifest_data = _read_text_member(tar, member_map["manifest.json"])
            try:
                manifest = ContextPackManifest.model_validate_json(manifest_data)
            except ValidationError as exc:
                raise ContextPackError(f"invalid manifest.json: {exc}") from exc

            notes: dict[str, str] = {}
            for name, member in member_map.items():
                if name == "manifest.json":
                    continue
                notes[name] = _read_text_member(tar, member)
            return manifest, notes
    except tarfile.TarError as exc:
        raise ContextPackError(f"could not read context pack: {exc}") from exc


def _plan_item(
    item: ContextPackItem,
    *,
    notes: dict[str, str],
    manifest: ContextPackManifest,
    existing_ids: set[str],
    created_by_id: dict[str, str],
    now: datetime,
    source_label: str,
    source_tag: str,
) -> ImportAction:
    path_reject_reason = _path_reject_reason(item)
    if path_reject_reason is not None:
        return _reject(item, path_reject_reason)

    skip_reason = _item_skip_reason(item)
    if skip_reason is not None:
        return ImportAction(
            action="skip",
            source_path=item.path,
            category=item.category,
            reason=skip_reason,
        )

    reject_reason = _item_reject_reason(item, source_label=source_label)
    if reject_reason is not None:
        return _reject(item, reject_reason)

    raw = notes.get(item.path)
    if raw is None:
        return _reject(item, "source file missing from bundle")
    if scan_secrets(raw):
        return _reject(item, "source content appears to contain secrets")

    category_key = _normalize_category(item.category)
    default = _CATEGORY_DEFAULTS.get(category_key)
    if default is None:
        return _reject(item, f"unknown category {item.category!r}")

    try:
        post = frontmatter.loads(raw)
    except Exception as exc:
        return _reject(
            item,
            "source frontmatter parse error",
            errors=(str(exc),),
        )
    note_metadata = dict(post.metadata)
    entry_type, level = _resolve_type_and_level(item, default)
    entry_id = item.id or _string_metadata(note_metadata, "id") or _slug(item.title or item.path)
    title = item.title or _string_metadata(note_metadata, "title") or _title_from_path(item.path)

    if entry_id in existing_ids:
        return ImportAction(
            action="skip",
            source_path=item.path,
            category=item.category,
            reason="entry id already exists",
            entry_id=entry_id,
            entry_type=entry_type,
            level=level,
            destination_path=entry_path(entry_type, entry_id),
            title=title,
        )

    if entry_id in created_by_id:
        return _reject(
            item,
            f"duplicate entry id {entry_id!r} also used by {created_by_id[entry_id]}",
        )

    try:
        fm = Frontmatter(
            id=entry_id,
            title=title,
            type=entry_type,
            level=level,
            status=EntryStatus.PROPOSED,
            created_at=now,
            updated_at=now,
            expires_at=None,
            projects=item.projects or _list_metadata(note_metadata, "projects"),
            tags=_merged_tags(
                item.tags,
                _list_metadata(note_metadata, "tags"),
                category_key,
                source_tag,
            ),
            sensitivity=item.sensitivity,
            review=ReviewMeta(required=True),
            visibility=item.visibility,
        )
    except ValidationError as exc:
        return _reject(
            item,
            "generated frontmatter failed validation",
            entry_id=entry_id,
            entry_type=entry_type,
            level=level,
            title=title,
            errors=(str(exc),),
        )
    body = _with_import_source(
        post.content,
        manifest=manifest,
        item=item,
        source_label=source_label,
    )
    entry = Entry(path=entry_path(entry_type, entry_id), frontmatter=fm, body=body)
    content = render_entry(fm, body)
    errors = tuple(validate_entry(entry))

    if errors:
        return _reject(
            item,
            "generated entry failed validation",
            entry_id=entry_id,
            entry_type=entry_type,
            level=level,
            destination_path=entry.path,
            title=title,
            errors=errors,
        )

    return ImportAction(
        action="create",
        source_path=item.path,
        category=item.category,
        reason="ready to import",
        entry_id=entry_id,
        entry_type=entry_type,
        level=level,
        destination_path=entry.path,
        title=title,
        content=content,
        entry=entry,
    )


def _apply_link_validation(actions: list[ImportAction], index: Index) -> list[ImportAction]:
    link_errors = validate_entry_links(index)
    errors_by_path: dict[str, list[str]] = {}
    for error in link_errors:
        path, _, message = error.partition(": ")
        errors_by_path.setdefault(path, []).append(message or error)

    updated: list[ImportAction] = []
    for action in actions:
        if action.action != "create" or action.destination_path not in errors_by_path:
            updated.append(action)
            continue
        updated.append(
            ImportAction(
                action="reject",
                source_path=action.source_path,
                category=action.category,
                reason="generated entry has unresolved links",
                entry_id=action.entry_id,
                entry_type=action.entry_type,
                level=action.level,
                destination_path=action.destination_path,
                title=action.title,
                errors=tuple(errors_by_path[action.destination_path]),
            )
        )
    return updated


def _load_existing_index(root: Path) -> tuple[Index, list[str]]:
    index = Index()
    errors: list[str] = []
    if not root.exists():
        return index, [f"knowledge repo does not exist: {root}"]

    for directory in TYPE_DIRS.values():
        entry_dir = root / directory
        if not entry_dir.exists():
            continue
        for path in sorted(entry_dir.glob("*.md")):
            relative_path = path.relative_to(root).as_posix()
            try:
                post = frontmatter.load(path)
                index.add(parse_entry(relative_path, dict(post.metadata), post.content))
            except Exception as exc:
                errors.append(f"{relative_path}: parse error: {exc}")
    return index, errors


def _resolve_type_and_level(
    item: ContextPackItem,
    default: tuple[EntryType, EscalationLevel],
) -> tuple[EntryType, EscalationLevel]:
    entry_type = item.type or default[0]
    level = item.level or (
        DEFAULT_LEVEL_MAP[entry_type][0] if item.type is not None else default[1]
    )
    return entry_type, level


def _item_reject_reason(item: ContextPackItem, *, source_label: str) -> str | None:
    if item.reject_reason:
        return item.reject_reason

    if item.personal or item.local_only or _has_local_path_part(item.path):
        return "personal or local-only source"
    if item.sensitivity == Sensitivity.RESTRICTED:
        return f"restricted content cannot be imported by {source_label.lower()} dry-run"
    return None


def _path_reject_reason(item: ContextPackItem) -> str | None:
    try:
        _validate_member_path(item.path)
    except ContextPackError as exc:
        return str(exc)
    return None


def _item_skip_reason(item: ContextPackItem) -> str | None:
    if item.skip_reason:
        return item.skip_reason
    if item.skip:
        return "item marked skip"
    return None


def _has_local_path_part(path: str) -> bool:
    for part in PurePosixPath(path).parts:
        normalized = _normalize_path_part(part)
        if normalized in _LOCAL_PATH_PARTS:
            return True
        if set(normalized.split()).intersection(_LOCAL_PATH_PARTS):
            return True
    return False


def _validate_member_path(path: str) -> None:
    pure_path = PurePosixPath(path)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        raise ContextPackError(f"unsafe bundle path: {path}")


def _normalized_member_map(members: list[tarfile.TarInfo]) -> dict[str, tarfile.TarInfo]:
    normalized = [(_normalize_member_path(member.name), member) for member in members]
    names = [name for name, _member in normalized]
    prefix = _bundle_root_prefix(names)

    member_map: dict[str, tarfile.TarInfo] = {}
    for name, member in normalized:
        canonical = _strip_bundle_prefix(name, prefix)
        if not canonical:
            continue
        if canonical in member_map:
            raise ContextPackError(f"duplicate bundle path after normalization: {canonical}")
        member_map[canonical] = member
    return member_map


def _normalize_member_path(path: str) -> str:
    _validate_member_path(path)
    parts = [part for part in PurePosixPath(path).parts if part not in ("", ".")]
    return PurePosixPath(*parts).as_posix() if parts else ""


def _bundle_root_prefix(names: list[str]) -> str | None:
    if "manifest.json" in names:
        return None
    if not names:
        return None
    prefixes = {PurePosixPath(name).parts[0] for name in names if PurePosixPath(name).parts}
    if len(prefixes) != 1:
        return None
    prefix = next(iter(prefixes))
    if f"{prefix}/manifest.json" in names:
        return prefix
    return None


def _strip_bundle_prefix(path: str, prefix: str | None) -> str:
    if prefix is None:
        return path
    pure_path = PurePosixPath(path)
    if pure_path.parts[:1] != (prefix,):
        return path
    stripped = PurePosixPath(*pure_path.parts[1:])
    return stripped.as_posix()


def _read_text_member(tar: tarfile.TarFile, member: tarfile.TarInfo) -> str:
    extracted = tar.extractfile(member)
    if extracted is None:
        raise ContextPackError(f"could not read bundle member: {member.name}")
    return extracted.read().decode("utf-8")


def _reject(
    item: ContextPackItem,
    reason: str,
    *,
    entry_id: str | None = None,
    entry_type: EntryType | None = None,
    level: EscalationLevel | None = None,
    destination_path: str | None = None,
    title: str | None = None,
    errors: tuple[str, ...] = (),
) -> ImportAction:
    return ImportAction(
        action="reject",
        source_path=item.path,
        category=item.category,
        reason=reason,
        entry_id=entry_id,
        entry_type=entry_type,
        level=level,
        destination_path=destination_path,
        title=title,
        errors=errors,
    )


def _with_import_source(
    body: str,
    *,
    manifest: ContextPackManifest,
    item: ContextPackItem,
    source_label: str,
) -> str:
    body = body.strip()
    source = "\n".join(
        [
            "## Import Source",
            "",
            f"- {source_label}: {manifest.name}",
            f"- Source category: {item.category}",
            f"- Source path: {item.path}",
        ]
    )
    if not body:
        return source
    return f"{body}\n\n{source}"


def _normalize_category(value: str) -> str:
    return value.strip().lower().replace("_", " ").replace("-", " ")


def _string_metadata(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _list_metadata(metadata: dict[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _merged_tags(
    manifest_tags: list[str],
    note_tags: list[str],
    category: str,
    source_tag: str,
) -> list[str]:
    tags = [*manifest_tags, *note_tags, source_tag, category.replace(" ", "-")]
    return list(dict.fromkeys(tag for tag in tags if tag))


def _title_from_path(path: str) -> str:
    stem = PurePosixPath(path).stem
    return stem.replace("-", " ").replace("_", " ").strip().title() or "Imported Context"


def _slug(value: str) -> str:
    stem = PurePosixPath(value).stem
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    if len(slug) < 3:
        slug = f"ctx-{slug or 'entry'}"
    return slug[:120]


def _slug_text(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if len(slug) < 3:
        slug = f"ctx-{slug or 'entry'}"
    return slug[:120]


def _count(actions: tuple[ImportAction, ...], action: str) -> int:
    return sum(1 for item in actions if item.action == action)
