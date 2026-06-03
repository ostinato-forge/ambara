"""Materialize curation reports into review branches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

import frontmatter
import git

from ambara.core.paths import TYPE_DIRS, is_safe_path
from ambara.core.schema import EntryStatus
from ambara.core.time import format_timestamp
from ambara.git.branch import create_branch


@dataclass(frozen=True)
class CurationReportWriteResult:
    branch: str
    commit: str
    path: str
    marked_paths: tuple[str, ...] = ()
    expired_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class _EntryPost:
    relative_path: str
    path: Path
    post: frontmatter.Post


def default_curation_report_branch(now: datetime) -> str:
    return f"ambara/curation/{now.strftime('%Y-%m-%d')}"


def default_curation_report_path(now: datetime) -> str:
    return f".ambara/curation/{now.strftime('%Y-%m-%d')}-weekly-hygiene.md"


def materialize_curation_report(
    repo_path: str,
    body: str,
    *,
    branch: str,
    now: datetime,
    base: str = "HEAD",
    path: str | None = None,
    message: str | None = None,
    revalidation_entry_ids: tuple[str, ...] = (),
    expired_active_entry_ids: tuple[str, ...] = (),
) -> CurationReportWriteResult:
    """Write a generated curation report to a review branch."""
    if not body.strip():
        raise ValueError("Curation report body must not be empty")

    report_path = path or default_curation_report_path(now)
    if not is_safe_path(repo_path, report_path):
        raise ValueError(f"Path traversal rejected: {report_path!r}")
    _validate_report_path(report_path)

    repo = git.Repo(repo_path)
    if repo.is_dirty(untracked_files=True):
        raise ValueError("Knowledge repo working tree must be clean before curation report")

    create_branch(repo_path, branch, base)

    full_path = Path(repo.working_dir) / report_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    revalidation_matches = _plan_entries_for_revalidation(repo, revalidation_entry_ids)
    expiry_matches = _plan_active_entries_for_expiry(repo, expired_active_entry_ids)
    marked_paths = _mark_entries_for_revalidation(revalidation_matches, now)
    expired_paths = _expire_active_entries(expiry_matches, now)
    full_path.write_text(_with_final_newline(body))
    repo.index.add([report_path, *marked_paths, *expired_paths])

    commit = repo.index.commit(
        message or f"chore(kb): add curation report {now.strftime('%Y-%m-%d')}"
    )
    return CurationReportWriteResult(
        branch=branch,
        commit=commit.hexsha,
        path=report_path,
        marked_paths=tuple(marked_paths),
        expired_paths=tuple(expired_paths),
    )


def _with_final_newline(value: str) -> str:
    return value if value.endswith("\n") else f"{value}\n"


def _plan_entries_for_revalidation(
    repo: git.Repo,
    entry_ids: tuple[str, ...],
) -> list[_EntryPost]:
    matches = _find_entry_posts(
        repo,
        entry_ids,
        missing_message="Curation revalidation target not found",
    )
    for match in matches:
        entry_id = match.post.metadata.get("id")
        if match.post.metadata.get("type") == "active":
            raise ValueError(f"Cannot mark active entry for review_after: {entry_id}")
    return matches


def _plan_active_entries_for_expiry(
    repo: git.Repo,
    entry_ids: tuple[str, ...],
) -> list[_EntryPost]:
    matches = _find_entry_posts(
        repo,
        entry_ids,
        missing_message="Curation active expiry target not found",
    )
    for match in matches:
        entry_id = match.post.metadata.get("id")
        if match.post.metadata.get("type") != "active":
            raise ValueError(f"Cannot expire non-active entry from curation report: {entry_id}")
    return matches


def _find_entry_posts(
    repo: git.Repo,
    entry_ids: tuple[str, ...],
    *,
    missing_message: str,
) -> list[_EntryPost]:
    if not entry_ids:
        return []

    remaining = set(entry_ids)
    matches: list[_EntryPost] = []
    working_dir = Path(repo.working_dir)

    for directory in TYPE_DIRS.values():
        entry_dir = working_dir / directory
        if not entry_dir.exists():
            continue
        for path in sorted(entry_dir.glob("*.md")):
            post = frontmatter.load(path)
            entry_id = post.metadata.get("id")
            if entry_id not in remaining:
                continue
            matches.append(
                _EntryPost(
                    relative_path=path.relative_to(working_dir).as_posix(),
                    path=path,
                    post=post,
                )
            )
            remaining.remove(entry_id)

    if remaining:
        missing = ", ".join(sorted(remaining))
        raise ValueError(f"{missing_message}: {missing}")
    return matches


def _mark_entries_for_revalidation(matches: list[_EntryPost], now: datetime) -> list[str]:
    timestamp = format_timestamp(now)
    marked_paths: list[str] = []
    for match in matches:
        post = match.post
        post.metadata["review_after"] = timestamp
        post.metadata["updated_at"] = timestamp
        match.path.write_text(frontmatter.dumps(post))
        marked_paths.append(match.relative_path)
    return marked_paths


def _expire_active_entries(matches: list[_EntryPost], now: datetime) -> list[str]:
    timestamp = format_timestamp(now)
    expired_paths: list[str] = []
    for match in matches:
        post = match.post
        post.metadata["status"] = str(EntryStatus.EXPIRED)
        post.metadata["updated_at"] = timestamp
        match.path.write_text(frontmatter.dumps(post))
        expired_paths.append(match.relative_path)
    return expired_paths


def _validate_report_path(path: str) -> None:
    report_path = PurePosixPath(path)
    if "." in report_path.parts or ".." in report_path.parts:
        raise ValueError(f"Invalid curation report path: {path!r}")
    if report_path.suffix != ".md":
        raise ValueError("Curation report path must be a Markdown file")
    if len(report_path.parts) < 3 or report_path.parts[:2] != (".ambara", "curation"):
        raise ValueError("Curation report path must be under .ambara/curation/")
