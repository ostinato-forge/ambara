"""Review-branch lifecycle operations for knowledge scopes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import frontmatter
import git

from jurati.core.index import parse_entry
from jurati.core.paths import TYPE_DIRS, is_safe_path
from jurati.core.schema import EntryStatus, EntryType
from jurati.core.scope_policy import ScopeMutePolicy, is_entry_muted, scope_policy_summary
from jurati.git.branch import create_branch


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
    timestamp = _format_timestamp(now)
    working_dir = Path(repo.working_dir)
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
        f"Generated: {_format_timestamp(now)}",
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


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validate_report_path(path: str) -> None:
    report_path = PurePosixPath(path)
    if "." in report_path.parts or ".." in report_path.parts:
        raise ValueError(f"Invalid lifecycle report path: {path!r}")
    if report_path.suffix != ".md":
        raise ValueError("Lifecycle report path must be a Markdown file")
    if len(report_path.parts) < 3 or report_path.parts[:2] != (".jurati", "lifecycle"):
        raise ValueError("Lifecycle report path must be under .jurati/lifecycle/")
