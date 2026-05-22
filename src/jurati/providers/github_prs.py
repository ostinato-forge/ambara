"""GitHub adapter — read labeled PRs from configured repositories.

Uses `gh api` via subprocess. No direct HTTP library dependency.
Tokens are never stored on long-lived state; errors are sanitized
to redact any token that may appear in stderr.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from jurati.core.pr_signals import PathStatus, PRSignal
from jurati.git.config import PRSignalsConfig

logger = logging.getLogger(__name__)

_TOKEN_PATTERN = re.compile(r"(gh[ps]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{22,})")
_BODY_EXCERPT_LIMIT = 500


def _sanitize_error(message: str) -> str:
    return _TOKEN_PATTERN.sub("[REDACTED]", message)


def _derive_target_areas(paths: list[str]) -> tuple[str, ...]:
    areas: set[str] = set()
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 2:
            areas.add("/".join(parts[:2]))
    return tuple(sorted(areas))


def _normalize_state(raw: str) -> Literal["open", "merged", "closed"]:
    lowered = raw.lower()
    if lowered == "merged":
        return "merged"
    if lowered == "closed":
        return "closed"
    return "open"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _gh_env(token: str | None) -> dict[str, str]:
    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token
    return env


def _is_rate_limit_error(stderr: str) -> bool:
    lowered = stderr.lower()
    return "rate limit" in lowered or "api rate limit" in lowered or "429" in lowered


def _run_gh_api_json(
    cmd: list[str],
    *,
    repo: str,
    description: str,
    env: dict[str, str],
    max_retries: int = 2,
) -> object | None:
    for attempt in range(max_retries + 1):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
        except subprocess.TimeoutExpired:
            logger.warning("GitHub API %s timed out for %s", description, repo)
            return None
        except OSError as exc:
            logger.warning("gh CLI not available: %s", _sanitize_error(str(exc)))
            return None

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if _is_rate_limit_error(stderr) and attempt < max_retries:
                delay = (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "GitHub API %s rate-limited for %s, retrying in %.1fs (%d/%d)",
                    description,
                    repo,
                    delay,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(delay)
                continue
            logger.warning(
                "GitHub API %s error for %s: %s",
                description,
                repo,
                _sanitize_error(stderr),
            )
            return None

        try:
            return cast(object, json.loads(result.stdout))
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from GitHub API %s for %s", description, repo)
            return None

    return None


def _fetch_search_items(
    repo: str,
    config: PRSignalsConfig,
    *,
    env: dict[str, str],
) -> list[dict[str, object]]:
    since = datetime.now(UTC) - timedelta(days=config.recency_days)
    query = f"repo:{repo} is:pr label:{config.label} updated:>={since.strftime('%Y-%m-%d')}"
    payload = _run_gh_api_json(
        [
            "gh",
            "api",
            "search/issues",
            "--method",
            "GET",
            "-f",
            f"q={query}",
            "-f",
            "per_page=30",
            "--jq",
            ".items",
        ],
        repo=repo,
        description="search",
        env=env,
    )
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _fetch_pr_detail(repo: str, number: int, *, env: dict[str, str]) -> dict[str, object] | None:
    payload = _run_gh_api_json(
        ["gh", "api", f"repos/{repo}/pulls/{number}"],
        repo=repo,
        description=f"pull/{number}",
        env=env,
    )
    return payload if isinstance(payload, dict) else None


def _fetch_pr_files(repo: str, number: int, *, env: dict[str, str]) -> list[str] | None:
    payload = _run_gh_api_json(
        ["gh", "api", f"repos/{repo}/pulls/{number}/files?per_page=100"],
        repo=repo,
        description=f"pull/{number}/files",
        env=env,
    )
    if not isinstance(payload, list):
        return None
    paths: list[str] = []
    for item in payload:
        if isinstance(item, dict) and "filename" in item:
            paths.append(str(item["filename"]))
        elif isinstance(item, str):
            paths.append(item)
    return paths


def _normalize_pr(
    raw: dict[str, object],
    repo: str,
    *,
    include_body_excerpt: bool,
    include_changed_paths: bool,
) -> PRSignal:
    number = int(str(raw.get("number", 0)))
    state: Literal["open", "merged", "closed"] = _normalize_state(str(raw.get("state", "open")))
    if raw.get("mergedAt") or raw.get("merged_at"):
        state = "merged"

    labels_raw = raw.get("labels", [])
    if isinstance(labels_raw, list):
        labels = tuple(
            (lb.get("name", "") if isinstance(lb, dict) else str(lb)) for lb in labels_raw
        )
    else:
        labels = ()

    body_raw = str(raw.get("body", "") or "")
    body_excerpt: str | None = body_raw[:_BODY_EXCERPT_LIMIT] if include_body_excerpt else None

    changed_paths_status: PathStatus = "disabled"
    changed_paths_raw: list[str] = []
    if include_changed_paths:
        if "files" in raw and isinstance(raw["files"], list):
            changed_paths_status = "available"
            files_raw = raw["files"]
            for f in files_raw:
                if isinstance(f, dict) and "filename" in f:
                    changed_paths_raw.append(str(f["filename"]))
                elif isinstance(f, str):
                    changed_paths_raw.append(f)
        else:
            changed_paths_status = "unavailable"

    created_at = _parse_datetime(str(raw.get("createdAt") or raw.get("created_at") or ""))
    updated_at = _parse_datetime(str(raw.get("updatedAt") or raw.get("updated_at") or ""))
    merged_at = _parse_datetime(str(raw.get("mergedAt") or raw.get("merged_at") or "") or None)
    now = datetime.now(UTC)

    return PRSignal(
        signal_id=f"github:{repo}:pull:{number}",
        provider="github",
        repo=repo,
        number=number,
        url=str(raw.get("html_url", raw.get("url", f"https://github.com/{repo}/pull/{number}"))),
        title=str(raw.get("title", "")),
        body_excerpt=body_excerpt,
        author=_extract_author(raw),
        state=state,
        labels=labels,
        created_at=created_at or now,
        updated_at=updated_at or now,
        merged_at=merged_at,
        changed_paths=tuple(changed_paths_raw),
        target_areas=_derive_target_areas(changed_paths_raw),
        changed_paths_status=changed_paths_status,
    )


def _extract_author(raw: dict[str, object]) -> str:
    author = raw.get("author") or raw.get("user")
    if isinstance(author, dict):
        return str(author.get("login", "unknown"))
    return str(author) if author else "unknown"


def fetch_labeled_prs(
    config: PRSignalsConfig,
    repo: str,
    *,
    token: str | None = None,
) -> list[PRSignal]:
    if repo not in config.repos:
        return []

    env = _gh_env(token)
    items = _fetch_search_items(repo, config, env=env)

    signals = []
    for item in items:
        try:
            number = int(str(item.get("number", 0)))
            raw = _fetch_pr_detail(repo, number, env=env) or item
            if config.include_changed_paths:
                raw = {k: v for k, v in raw.items() if k != "files"}
            if config.include_changed_paths:
                files = _fetch_pr_files(repo, number, env=env)
                if files is not None:
                    raw = {**raw, "files": [{"filename": path} for path in files]}
            sig = _normalize_pr(
                raw,
                repo,
                include_body_excerpt=config.include_body_excerpt,
                include_changed_paths=config.include_changed_paths,
            )
            signals.append(sig)
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("Skipping malformed PR from %s: %s", repo, exc)
            continue

    return signals


def fetch_all_signals(
    config: PRSignalsConfig,
    *,
    token: str | None = None,
) -> list[PRSignal]:
    all_signals: list[PRSignal] = []
    for repo in config.repos:
        all_signals.extend(fetch_labeled_prs(config, repo, token=token))
    return all_signals
