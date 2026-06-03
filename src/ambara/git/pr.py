"""PR creation with candidate-based auth dispatch."""

from __future__ import annotations

import contextlib
import logging
import random
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

from ambara.git.auth import AuthCandidate, _gh_subprocess_env, read_token

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PRResult:
    url: str | None
    number: int | None
    branch: str
    kind: Literal["pr", "branch"]


def create_pr(
    repo_path: str,
    branch: str,
    title: str,
    body: str,
    *,
    labels: list[str],
    base: str,
    candidates: Sequence[AuthCandidate],
) -> tuple[PRResult, AuthCandidate | None]:
    owner: str | None = None
    repo: str | None = None

    for candidate in candidates:
        if candidate.owner:
            owner = candidate.owner
        if candidate.repo:
            repo = candidate.repo

        if candidate.method == "api_token":
            result = _try_api(candidate, branch, title, body, labels=labels, base=base)
            if result is not None:
                return result, candidate

        elif candidate.method == "gh_cli":
            result = _try_gh_cli(
                repo_path,
                candidate,
                branch,
                title,
                body,
                labels=labels,
                base=base,
            )
            if result is not None:
                return result, candidate

    return _branch_only(branch, owner=owner, repo=repo, base=base), None


_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503})
_MAX_RETRIES = 2


def _try_api(
    candidate: AuthCandidate,
    branch: str,
    title: str,
    body: str,
    *,
    labels: list[str],
    base: str,
) -> PRResult | None:
    token = read_token(candidate)
    if token is None:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    url = f"https://api.github.com/repos/{candidate.owner}/{candidate.repo}/pulls"
    payload = {"title": title, "body": body, "head": branch, "base": base}

    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=30)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            if attempt < _MAX_RETRIES:
                delay = (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "PR creation connect/timeout error, retrying in %.1fs: %s", delay, exc
                )
                time.sleep(delay)
                continue
            return None
        except httpx.HTTPError:
            return None

        if resp.status_code == 201:
            try:
                data = resp.json()
                pr_number = data["number"]
                pr_url = data["html_url"]
            except (ValueError, KeyError, TypeError):
                return None
            if labels:
                with contextlib.suppress(Exception):
                    httpx.post(
                        f"https://api.github.com/repos/{candidate.owner}/{candidate.repo}"
                        f"/issues/{pr_number}/labels",
                        headers=headers,
                        json={"labels": labels},
                        timeout=30,
                    )
            return PRResult(url=pr_url, number=pr_number, branch=branch, kind="pr")

        if resp.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = min(float(retry_after), 30.0)
            else:
                delay = (2**attempt) + random.uniform(0, 1)
            logger.warning(
                "PR creation returned %d, retrying in %.1fs (%d/%d)",
                resp.status_code,
                delay,
                attempt + 1,
                _MAX_RETRIES,
            )
            time.sleep(delay)
            continue

        return None

    return None


def _try_gh_cli(
    repo_path: str,
    candidate: AuthCandidate,
    branch: str,
    title: str,
    body: str,
    *,
    labels: list[str],
    base: str,
) -> PRResult | None:
    cmd = [
        "gh",
        "pr",
        "create",
        "--repo",
        f"{candidate.owner}/{candidate.repo}",
        "--title",
        title,
        "--body",
        body,
        "--head",
        branch,
        "--base",
        base,
    ]
    for label in labels:
        cmd.extend(["--label", label])

    try:
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            env=_gh_subprocess_env(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    url = result.stdout.strip()
    try:
        number = int(url.rstrip("/").rsplit("/", 1)[-1])
    except (ValueError, IndexError):
        return None

    return PRResult(url=url, number=number, branch=branch, kind="pr")


def _branch_only(
    branch: str,
    *,
    owner: str | None,
    repo: str | None,
    base: str,
) -> PRResult:
    url: str | None = None
    if owner and repo:
        url = f"https://github.com/{owner}/{repo}/compare/{base}...{branch}?expand=1"
    return PRResult(url=url, number=None, branch=branch, kind="branch")


@dataclass(frozen=True)
class StalePR:
    number: int
    title: str
    url: str
    created_at: str
    branch: str


def list_open_prs(
    repo_path: str,
    *,
    label: str = "ambara",
    older_than_days: int = 30,
) -> list[StalePR]:
    """List open PRs with the given label older than the threshold."""
    import json
    from datetime import UTC, datetime, timedelta

    cmd = [
        "gh",
        "pr",
        "list",
        "--state",
        "open",
        "--label",
        label,
        "--json",
        "number,title,url,createdAt,headRefName",
        "--limit",
        "100",
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            env=_gh_subprocess_env(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if result.returncode != 0:
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    stale: list[StalePR] = []
    for pr in data:
        created = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))
        if created < cutoff:
            stale.append(
                StalePR(
                    number=pr["number"],
                    title=pr["title"],
                    url=pr["url"],
                    created_at=pr["createdAt"],
                    branch=pr["headRefName"],
                )
            )
    return stale
