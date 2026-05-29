"""Review-branch lifecycle operations for knowledge scopes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

import frontmatter
import git

from jurati.core.index import parse_entry
from jurati.core.paths import TYPE_DIRS, is_safe_path
from jurati.core.schema import Entry, EntryStatus, EntryType, EscalationLevel, Sensitivity
from jurati.core.scope_policy import ScopeMutePolicy, is_entry_muted, scope_policy_summary
from jurati.core.time import format_timestamp
from jurati.git.branch import create_branch


@dataclass(frozen=True)
class ClearEntriesFilter:
    entry_types: tuple[EntryType, ...] = ()
    levels: tuple[EscalationLevel, ...] = ()
    projects: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    include_restricted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "projects", _normalized_tuple(self.projects))
        object.__setattr__(self, "repos", _normalized_tuple(self.repos))
        object.__setattr__(self, "tags", _normalized_tuple(self.tags))

    def has_selectors(self) -> bool:
        return bool(self.entry_types or self.levels or self.projects or self.repos or self.tags)


@dataclass(frozen=True)
class ClearEntryMatch:
    entry_id: str
    title: str
    entry_type: str
    level: str
    status: str
    sensitivity: str
    path: str
    action: str


@dataclass(frozen=True)
class ClearEntriesResult:
    branch: str
    commit: str
    report_path: str
    matches: tuple[ClearEntryMatch, ...]


@dataclass(frozen=True)
class RetireScopeMatch:
    entry_id: str
    title: str
    entry_type: str
    status: str
    path: str
    action: str


@dataclass(frozen=True)
class RetireScopeResult:
    branch: str
    commit: str
    report_path: str
    matches: tuple[RetireScopeMatch, ...]


def default_retire_scope_branch(now: datetime) -> str:
    return f"jurati/retire-scope-{now.strftime('%Y%m%d-%H%M%S')}"


def default_retire_scope_report_path(now: datetime) -> str:
    return f".jurati/lifecycle/{now.strftime('%Y-%m-%d')}-retire-scope.md"


def default_clear_entries_branch(now: datetime) -> str:
    return f"jurati/clear-context-{now.strftime('%Y%m%d-%H%M%S')}"


def default_clear_entries_report_path(now: datetime) -> str:
    return f".jurati/lifecycle/{now.strftime('%Y-%m-%d')}-clear-context.md"


def collect_clear_entries_matches(
    repo_path: str, filters: ClearEntriesFilter
) -> tuple[ClearEntryMatch, ...]:
    repo = git.Repo(repo_path)
    working_dir = Path(repo.working_dir)
    matches: list[ClearEntryMatch] = []
    for directory in TYPE_DIRS.values():
        entry_dir = working_dir / directory
        if not entry_dir.exists():
            continue
        for path in sorted(entry_dir.glob("*.md")):
            relative_path = path.relative_to(working_dir).as_posix()
            post = frontmatter.load(path)
            try:
                entry = parse_entry(relative_path, dict(post.metadata), post.content)
            except Exception as exc:
                raise ValueError(f"{relative_path}: parse error: {exc}") from exc
            if entry.frontmatter.status in (EntryStatus.EXPIRED, EntryStatus.SUPERSEDED):
                continue
            if (
                entry.frontmatter.sensitivity == Sensitivity.RESTRICTED
                and not filters.include_restricted
            ):
                continue
            if not _entry_matches_clear_filters(entry, filters):
                continue
            action = "expire_active" if entry.frontmatter.type == EntryType.ACTIVE else "expire"
            matches.append(
                ClearEntryMatch(
                    entry_id=entry.frontmatter.id,
                    title=entry.frontmatter.title,
                    entry_type=str(entry.frontmatter.type),
                    level=str(entry.frontmatter.level),
                    status=str(entry.frontmatter.status),
                    sensitivity=str(entry.frontmatter.sensitivity),
                    path=relative_path,
                    action=action,
                )
            )
    return tuple(matches)


def materialize_clear_entries(
    repo_path: str,
    filters: ClearEntriesFilter,
    *,
    branch: str,
    now: datetime,
    base: str = "HEAD",
    report_path: str | None = None,
    message: str | None = None,
) -> ClearEntriesResult:
    matches = collect_clear_entries_matches(repo_path, filters)
    if not matches:
        raise ValueError("No current entries matched the clear filters")

    path = report_path or default_clear_entries_report_path(now)
    if not is_safe_path(repo_path, path):
        raise ValueError(f"Path traversal rejected: {path!r}")
    _validate_report_path(path)

    repo = git.Repo(repo_path)
    if repo.is_dirty(untracked_files=True):
        raise ValueError("Knowledge repo working tree must be clean before clearing context")

    create_branch(repo_path, branch, base)
    changed_paths = _expire_matches(Path(repo.working_dir), matches, now)
    full_report_path = Path(repo.working_dir) / path
    full_report_path.parent.mkdir(parents=True, exist_ok=True)
    full_report_path.write_text(_clear_entries_report(filters, matches, now))
    repo.index.add([*changed_paths, path])
    commit = repo.index.commit(message or "chore(kb): clear context entries")
    return ClearEntriesResult(
        branch=branch,
        commit=commit.hexsha,
        report_path=path,
        matches=matches,
    )


def collect_retire_scope_matches(
    repo_path: str, policy: ScopeMutePolicy
) -> tuple[RetireScopeMatch, ...]:
    if policy.is_empty():
        raise ValueError("retire scope policy must not be empty")

    repo = git.Repo(repo_path)
    working_dir = Path(repo.working_dir)
    matches: list[RetireScopeMatch] = []
    for directory in TYPE_DIRS.values():
        entry_dir = working_dir / directory
        if not entry_dir.exists():
            continue
        for path in sorted(entry_dir.glob("*.md")):
            relative_path = path.relative_to(working_dir).as_posix()
            post = frontmatter.load(path)
            try:
                entry = parse_entry(relative_path, dict(post.metadata), post.content)
            except Exception as exc:
                raise ValueError(f"{relative_path}: parse error: {exc}") from exc
            if entry.frontmatter.status in (EntryStatus.EXPIRED, EntryStatus.SUPERSEDED):
                continue
            if not is_entry_muted(entry, policy):
                continue
            action = (
                "expire_active" if entry.frontmatter.type == EntryType.ACTIVE else "retire_entry"
            )
            matches.append(
                RetireScopeMatch(
                    entry_id=entry.frontmatter.id,
                    title=entry.frontmatter.title,
                    entry_type=str(entry.frontmatter.type),
                    status=str(entry.frontmatter.status),
                    path=relative_path,
                    action=action,
                )
            )
    return tuple(matches)


def materialize_retire_scope(
    repo_path: str,
    policy: ScopeMutePolicy,
    *,
    branch: str,
    now: datetime,
    base: str = "HEAD",
    report_path: str | None = None,
    message: str | None = None,
) -> RetireScopeResult:
    matches = collect_retire_scope_matches(repo_path, policy)
    if not matches:
        raise ValueError("No active entries matched the requested scope")

    path = report_path or default_retire_scope_report_path(now)
    if not is_safe_path(repo_path, path):
        raise ValueError(f"Path traversal rejected: {path!r}")
    _validate_report_path(path)

    repo = git.Repo(repo_path)
    if repo.is_dirty(untracked_files=True):
        raise ValueError("Knowledge repo working tree must be clean before retiring a scope")

    create_branch(repo_path, branch, base)
    working_dir = Path(repo.working_dir)
    changed_paths = _expire_matches(working_dir, matches, now)

    full_report_path = working_dir / path
    full_report_path.parent.mkdir(parents=True, exist_ok=True)
    full_report_path.write_text(_retire_scope_report(policy, matches, now))
    repo.index.add([*changed_paths, path])
    commit = repo.index.commit(message or "chore(kb): retire scope")
    return RetireScopeResult(
        branch=branch,
        commit=commit.hexsha,
        report_path=path,
        matches=matches,
    )


def _retire_scope_report(
    policy: ScopeMutePolicy,
    matches: tuple[RetireScopeMatch, ...],
    now: datetime,
) -> str:
    summary = scope_policy_summary(policy)
    lines = [
        "# Retire Jurati Scope",
        "",
        f"Generated: {format_timestamp(now)}",
        "",
        "This is reviewed lifecycle cleanup. It expires matching context so normal "
        "startup, query, and search paths stop treating it as current. It does not "
        "rewrite git history or perform emergency purge.",
        "",
        "## Scope",
        "",
    ]
    for key in ("projects", "repos", "signal_sources", "tags"):
        values = summary[key]
        if values:
            lines.append(f"- {key}: {', '.join(values)}")
    lines.extend(["", "## Entries", ""])
    for match in matches:
        lines.append(
            f"- `{match.entry_id}` ({match.entry_type}, {match.status}) "
            f"`{match.path}` -> {match.action}"
        )
    return "\n".join(lines) + "\n"


def _clear_entries_report(
    filters: ClearEntriesFilter,
    matches: tuple[ClearEntryMatch, ...],
    now: datetime,
) -> str:
    lines = [
        "# Clear Jurati Context",
        "",
        f"Generated: {format_timestamp(now)}",
        "",
        "This is reviewed lifecycle cleanup. It expires matching entries so normal "
        "startup, query, and search paths stop treating them as current. It does not "
        "delete files, rewrite git history, or perform emergency purge.",
        "",
        "## Filters",
        "",
    ]
    selector_lines = _clear_selector_lines(filters)
    if selector_lines:
        lines.extend(selector_lines)
    else:
        target = (
            "all current entries"
            if filters.include_restricted
            else "all current non-restricted entries"
        )
        lines.append(f"- {target}")
    if filters.include_restricted:
        lines.append("- restricted entries included")
    else:
        lines.append("- restricted entries excluded")
    lines.extend(["", "## Entries", ""])
    for match in matches:
        lines.append(
            f"- `{match.entry_id}` ({match.entry_type}, {match.level}, {match.status}, "
            f"{match.sensitivity}) `{match.path}` -> {match.action}"
        )
    return "\n".join(lines) + "\n"


def _clear_selector_lines(filters: ClearEntriesFilter) -> list[str]:
    lines: list[str] = []
    if filters.entry_types:
        lines.append(f"- types: {', '.join(str(value) for value in filters.entry_types)}")
    if filters.levels:
        lines.append(f"- levels: {', '.join(str(value) for value in filters.levels)}")
    if filters.projects:
        lines.append(f"- projects: {', '.join(filters.projects)}")
    if filters.repos:
        lines.append(f"- repos: {', '.join(filters.repos)}")
    if filters.tags:
        lines.append(f"- tags: {', '.join(filters.tags)}")
    return lines


def _entry_matches_clear_filters(entry: Entry, filters: ClearEntriesFilter) -> bool:
    fm = entry.frontmatter
    if filters.entry_types and fm.type not in filters.entry_types:
        return False
    if filters.levels and fm.level not in filters.levels:
        return False
    if filters.projects and not _overlaps(fm.projects, filters.projects):
        return False
    if filters.tags and not _overlaps(fm.tags, filters.tags):
        return False
    if filters.repos:
        source_repo = fm.source.repo if fm.source else None
        if source_repo is None or _normalize(source_repo) not in filters.repos:
            return False
    return True


def _expire_matches(
    working_dir: Path,
    matches: tuple[ClearEntryMatch, ...] | tuple[RetireScopeMatch, ...],
    now: datetime,
) -> list[str]:
    timestamp = format_timestamp(now)
    changed_paths: list[str] = []
    for match in matches:
        full_path = working_dir / match.path
        post = frontmatter.load(full_path)
        post.metadata["status"] = str(EntryStatus.EXPIRED)
        post.metadata["updated_at"] = timestamp
        if post.metadata.get("type") == str(EntryType.ACTIVE):
            post.metadata["expires_at"] = timestamp
        full_path.write_text(frontmatter.dumps(post))
        changed_paths.append(match.path)
    return changed_paths


def _overlaps(values: list[str], filters: tuple[str, ...]) -> bool:
    return bool({_normalize(value) for value in values}.intersection(filters))


def _normalize(value: str) -> str:
    return value.strip().lower()


def _normalized_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({_normalize(value) for value in values if value.strip()}))


def _validate_report_path(path: str) -> None:
    report_path = PurePosixPath(path)
    if "." in report_path.parts or ".." in report_path.parts:
        raise ValueError(f"Invalid lifecycle report path: {path!r}")
    if report_path.suffix != ".md":
        raise ValueError("Lifecycle report path must be a Markdown file")
    if len(report_path.parts) < 3 or report_path.parts[:2] != (".jurati", "lifecycle"):
        raise ValueError("Lifecycle report path must be under .jurati/lifecycle/")
