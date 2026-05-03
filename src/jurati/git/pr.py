"""GitHub PR adapter for L1 lightweight and L2/L3 review PRs."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class PRResult:
    url: str
    number: int
    branch: str


def create_pr(
    repo_path: str,
    branch: str,
    title: str,
    body: str,
    *,
    labels: list[str] | None = None,
    base: str = "main",
) -> PRResult:
    cmd = [
        "gh", "pr", "create",
        "--title", title,
        "--body", body,
        "--head", branch,
        "--base", base,
    ]
    if labels:
        for label in labels:
            cmd.extend(["--label", label])

    result = subprocess.run(
        cmd,
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    url = result.stdout.strip()
    try:
        number = int(url.rstrip("/").rsplit("/", 1)[-1])
    except ValueError as e:
        raise ValueError(f"Failed to parse PR number from gh output: {url!r}") from e
    return PRResult(url=url, number=number, branch=branch)


def create_lightweight_pr(
    repo_path: str,
    branch: str,
    title: str,
    body: str,
    *,
    base: str = "main",
) -> PRResult:
    return create_pr(
        repo_path,
        branch,
        title,
        body,
        labels=["jurati", "low-ceremony"],
        base=base,
    )


def create_review_pr(
    repo_path: str,
    branch: str,
    title: str,
    body: str,
    *,
    base: str = "main",
) -> PRResult:
    return create_pr(
        repo_path,
        branch,
        title,
        body,
        labels=["jurati", "review-required"],
        base=base,
    )
