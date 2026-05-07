"""Context-pack import planning."""

from __future__ import annotations

import re
import tarfile
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


def plan_context_import(
    bundle_path: Path,
    *,
    knowledge_repo: Path,
    now: datetime,
) -> ImportPlan:
    manifest, notes = _read_bundle(bundle_path)
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
    )


def default_import_branch(plan: ImportPlan) -> str:
    return f"jurati/import-context-{_slug(plan.bundle_name)}"


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
) -> ImportAction:
    reject_reason = _item_reject_reason(item)
    if reject_reason is not None:
        return _reject(item, reject_reason)

    raw = notes.get(item.path)
    if raw is None:
        return _reject(item, "source file missing from bundle")

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
            tags=_merged_tags(item.tags, _list_metadata(note_metadata, "tags"), category_key),
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
    body = _with_import_source(post.content, manifest=manifest, item=item)
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


def _item_reject_reason(item: ContextPackItem) -> str | None:
    try:
        _validate_member_path(item.path)
    except ContextPackError as exc:
        return str(exc)

    parts = {part.lower() for part in PurePosixPath(item.path).parts}
    if item.skip:
        return "item marked skip"
    if item.personal or item.local_only or parts.intersection(_LOCAL_PATH_PARTS):
        return "personal or local-only source"
    if item.sensitivity == Sensitivity.RESTRICTED:
        return "restricted content cannot be imported by context pack dry-run"
    return None


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
) -> str:
    body = body.strip()
    source = "\n".join(
        [
            "## Import Source",
            "",
            f"- Context pack: {manifest.name}",
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


def _merged_tags(manifest_tags: list[str], note_tags: list[str], category: str) -> list[str]:
    tags = [*manifest_tags, *note_tags, "context-pack", category.replace(" ", "-")]
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


def _count(actions: tuple[ImportAction, ...], action: str) -> int:
    return sum(1 for item in actions if item.action == action)
