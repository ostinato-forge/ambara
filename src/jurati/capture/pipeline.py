"""End-to-end capture orchestration for the jurati: commit convention."""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

import git

from jurati.capture.extract import derive_entry_id, parse_commit_message, scan_secrets
from jurati.core.changes import plan_capture
from jurati.core.schema import EscalationLevel, SourceMeta
from jurati.git.branch import create_branch, push_branch
from jurati.git.commit import materialize_write


@dataclass(frozen=True)
class CaptureOutcome:
    entry_id: str
    level: EscalationLevel
    sha: str
    branch: str | None
    secret_detected: bool
    contradiction_ids: list[str] = field(default_factory=list)


def entry_exists_on_main(repo_path: str, entry_path: str, main_branch: str) -> bool:
    repo = git.Repo(repo_path)
    try:
        main_ref = repo.refs[f"origin/{main_branch}"]
        main_ref.commit.tree[entry_path]
        return True
    except (IndexError, KeyError):
        return False


def branch_exists_remote(repo_path: str, branch_name: str) -> bool:
    repo = git.Repo(repo_path)
    try:
        repo.refs[f"origin/{branch_name}"]
        return True
    except (IndexError, ValueError):
        return False


def push_branch_with_retry(repo_path: str, branch_name: str, *, max_retries: int = 3) -> None:
    for attempt in range(max_retries):
        try:
            push_branch(repo_path, branch_name)
            return
        except git.exc.GitCommandError:
            if attempt == max_retries - 1:
                raise
            delay = (2**attempt) + random.uniform(0, 1)
            time.sleep(delay)
            repo = git.Repo(repo_path)
            repo.remotes.origin.fetch()


def run_capture(
    *,
    message: str,
    repo_slug: str,
    knowledge_repo_path: str,
    main_branch: str,
    now: datetime,
    source_commit: str,
    source_author: str,
    extra_secret_patterns: list[re.Pattern[str]] | None = None,
) -> CaptureOutcome | None:
    parsed = parse_commit_message(message)
    if parsed is None:
        return None

    entry_id = derive_entry_id(repo_slug, parsed.title, commit_sha=source_commit)
    source = SourceMeta(repo=repo_slug, commit=source_commit, author=source_author)

    secret_detected = scan_secrets(f"{parsed.title} {parsed.body}", extra_secret_patterns)
    level = parsed.level
    if secret_detected and level in (EscalationLevel.L0, EscalationLevel.L1):
        level = EscalationLevel.L2

    intent = plan_capture(
        entry_type=parsed.entry_type,
        title=parsed.title,
        body=parsed.body,
        entry_id=entry_id,
        level=level,
        now=now,
        source=source,
    )

    if entry_exists_on_main(knowledge_repo_path, intent.path, main_branch):
        return None

    if intent.branch and branch_exists_remote(knowledge_repo_path, intent.branch):
        return None

    if intent.branch is None:
        raise ValueError("Capture pipeline does not handle L0 active entries")

    contradiction_ids: list[str] = []
    try:
        from jurati.core.curation import detect_contradictions  # type: ignore[import-not-found]
        from jurati.git.repo import load_index_from_repo

        index = load_index_from_repo(knowledge_repo_path, main_branch)
        conflicts = detect_contradictions(
            parsed.title,
            list(index.entries.values()),
            entry_type=parsed.entry_type,
        )
        contradiction_ids = [c.frontmatter.id for c in conflicts]
    except Exception:
        pass

    create_branch(knowledge_repo_path, intent.branch, f"origin/{main_branch}")
    sha = materialize_write(knowledge_repo_path, intent)
    push_branch_with_retry(knowledge_repo_path, intent.branch)

    return CaptureOutcome(
        entry_id=entry_id,
        level=level,
        sha=sha,
        branch=intent.branch,
        secret_detected=secret_detected,
        contradiction_ids=contradiction_ids,
    )
