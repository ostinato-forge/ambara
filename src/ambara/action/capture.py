# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""CI capture entrypoint for ambara commit-driven knowledge extraction."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import git

from ambara.capture.extract import parse_commit_message
from ambara.core.schema import EscalationLevel
from ambara.git.forge import parse_remote
from ambara.git.repo import fetch_all, repo_cache_path

_AMBARA_LINE_RE = re.compile(r"^ambara(?:\([a-z]+\))?:\s*.+$", re.MULTILINE)


def collect_ambara_messages(
    commits: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [c for c in commits if parse_commit_message(c["message"]) is not None]


def derive_batch_branch(repo_slug: str, push_sha: str, *, count: int = 2) -> str | None:
    if count <= 1:
        return None
    return f"ambara/{repo_slug}/batch-{push_sha[:6]}"


def extract_ambara_lines_from_body(body: str | None) -> list[str]:
    if not body:
        return []
    return _AMBARA_LINE_RE.findall(body)


def message_dedup_key(message: str) -> str:
    first_line = message.split("\n", 1)[0].strip()
    return hashlib.sha256(first_line.encode()).hexdigest()[:12]


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _authenticated_remote(remote: str, token: str | None) -> str:
    if not token:
        return remote

    remote_ref = parse_remote(remote)
    if remote_ref is None:
        return remote

    quoted = urllib.parse.quote(token, safe="")
    suffix = f"{remote_ref.path}.git"
    if remote_ref.forge == "github":
        return f"https://x-access-token:{quoted}@{remote_ref.host}/{suffix}"
    if remote_ref.forge == "gitlab":
        return f"https://oauth2:{quoted}@{remote_ref.host}/{suffix}"
    return remote


def _prepare_knowledge_repo(
    *,
    remote: str,
    cache_dir: str,
    main_branch: str,
    token: str | None,
) -> str:
    path = repo_cache_path(remote, cache_dir)
    auth_remote = _authenticated_remote(remote, token)
    if os.path.isdir(os.path.join(path, ".git")):
        repo = git.Repo(path)
        repo.remotes.origin.set_url(auth_remote)
    else:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        git.Repo.clone_from(auth_remote, path)
    fetch_all(path, main_branch)
    return path


def _repo_slug(source_repo: str) -> str:
    cleaned = source_repo.strip().strip("/")
    if not cleaned:
        raise ValueError("source repository must not be empty")
    return cleaned.split("/")[-1]


def _source_context() -> tuple[str, str, str, Literal["github_actions", "gitlab_ci", "unknown"]]:
    override_repo = os.environ.get("AMBARA_SOURCE_REPOSITORY")
    override_sha = os.environ.get("AMBARA_SOURCE_SHA")
    if override_repo and override_sha:
        return (
            override_repo,
            override_sha,
            os.environ.get("AMBARA_SOURCE_BEFORE", ""),
            cast_caller_source(os.environ.get("AMBARA_CALLER_SOURCE")),
        )

    github_repo = os.environ.get("GITHUB_REPOSITORY")
    github_sha = os.environ.get("GITHUB_SHA")
    if github_repo and github_sha:
        return (
            github_repo,
            github_sha,
            os.environ.get("GITHUB_EVENT_BEFORE", ""),
            "github_actions",
        )

    gitlab_repo = os.environ.get("CI_PROJECT_PATH")
    gitlab_sha = os.environ.get("CI_COMMIT_SHA")
    if gitlab_repo and gitlab_sha:
        return (
            gitlab_repo,
            gitlab_sha,
            os.environ.get("CI_COMMIT_BEFORE_SHA", ""),
            "gitlab_ci",
        )

    raise KeyError(
        "CI source context is missing. Set GitHub/GitLab CI env vars or "
        "AMBARA_SOURCE_REPOSITORY and AMBARA_SOURCE_SHA."
    )


def cast_caller_source(value: str | None) -> Literal["github_actions", "gitlab_ci", "unknown"]:
    if value == "github_actions":
        return "github_actions"
    if value == "gitlab_ci":
        return "gitlab_ci"
    return "unknown"


def main() -> None:
    source_repo, push_sha, before, caller_source = _source_context()
    repo_slug = _repo_slug(source_repo)
    auto_merge = os.environ.get("AMBARA_AUTO_MERGE", "true").lower() == "true"
    remote = os.environ["AMBARA_KNOWLEDGE_REMOTE"]
    token = os.environ.get("AMBARA_KNOWLEDGE_TOKEN")
    main_branch = os.environ.get("AMBARA_MAIN_BRANCH", "main")
    cache_dir = os.environ.get(
        "AMBARA_CACHE_DIR",
        os.path.join(tempfile.gettempdir(), "ambara-knowledge"),
    )
    knowledge_repo_path = _prepare_knowledge_repo(
        remote=remote,
        cache_dir=cache_dir,
        main_branch=main_branch,
        token=token,
    )

    if not before or before == "0" * 40:
        shas = [_git("log", "-1", "--format=%H")]
    else:
        shas = _git("log", "--format=%H", f"{before}..{push_sha}").splitlines()

    commits: list[dict[str, str]] = []
    for sha in shas:
        msg = _git("log", "-1", "--format=%B", sha)
        author = _git("log", "-1", "--format=%ae", sha)
        commits.append({"sha": sha, "message": msg, "author": author})

    synthetic: list[dict[str, str]] = []
    for commit in commits:
        body_lines = extract_ambara_lines_from_body(commit["message"])
        parsed = parse_commit_message(commit["message"])
        if parsed is None and body_lines:
            for line in body_lines:
                synthetic.append(
                    {
                        "sha": commit["sha"],
                        "message": line,
                        "author": commit["author"],
                    }
                )
    commits.extend(synthetic)

    ambara_commits = collect_ambara_messages(commits)
    if not ambara_commits:
        print("No ambara: commits found.")
        return

    now = datetime.now(UTC)
    captured = 0
    for jc in ambara_commits:
        try:
            from ambara.capture.pipeline import run_capture

            outcome = run_capture(
                message=jc["message"],
                repo_slug=repo_slug,
                knowledge_repo_path=knowledge_repo_path,
                main_branch=main_branch,
                now=now,
                source_commit=jc["sha"],
                source_author=jc["author"],
                caller_source=caller_source,
            )
            if outcome:
                captured += 1
                print(f'[ambara] captured: "{outcome.entry_id}" ({outcome.level})')
                if outcome.content_policy_action == "require_review":
                    rules = ", ".join(outcome.content_policy_rules)
                    print(f"[ambara] content review required: {rules}")
                if outcome.content_policy_warning:
                    print(f"[ambara] warning: {outcome.content_policy_warning}")
                if (
                    auto_merge
                    and outcome.level == EscalationLevel.L1
                    and not outcome.secret_detected
                ):
                    print(f"[ambara] auto-merge eligible: {outcome.entry_id} (L1, clean)")
        except Exception as e:
            print(f"[ambara] error capturing {jc['sha'][:8]}: {e}", file=sys.stderr)

    print(f"Captured {captured} entries from {repo_slug}")


if __name__ == "__main__":
    main()
