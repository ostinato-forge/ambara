"""GitHub adapter — read labeled PRs from configured repositories.

Uses `gh api` via subprocess. No direct HTTP library dependency.
Tokens are never stored on long-lived state; errors are sanitized
to redact any token that may appear in stderr.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Literal

from jurati.core.pr_signals import PRSignal
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

    changed_paths_raw: list[str] = []
    if include_changed_paths:
        files_raw = raw.get("files", [])
        if isinstance(files_raw, list):
            for f in files_raw:
                if isinstance(f, dict) and "filename" in f:
                    changed_paths_raw.append(str(f["filename"]))
                elif isinstance(f, str):
                    changed_paths_raw.append(f)

    created_at = _parse_datetime(str(raw.get("createdAt") or raw.get("created_at") or ""))
    updated_at = _parse_datetime(str(raw.get("updatedAt") or raw.get("updated_at") or ""))
    merged_at = _parse_datetime(str(raw.get("mergedAt") or raw.get("merged_at") or "") or None)
    now = datetime.now(UTC)

    return PRSignal(
        signal_id=f"github:{repo}:pull:{number}",
        provider="github",
        repo=repo,
        number=number,
        url=str(raw.get("url", raw.get("html_url", f"https://github.com/{repo}/pull/{number}"))),
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

    since = datetime.now(UTC) - timedelta(days=config.recency_days)

    query = f"repo:{repo} is:pr label:{config.label} updated:>={since.strftime('%Y-%m-%d')}"
    cmd = [
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
    ]

    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except subprocess.TimeoutExpired:
        logger.warning("GitHub API request timed out for %s", repo)
        return []
    except OSError as exc:
        logger.warning("gh CLI not available: %s", _sanitize_error(str(exc)))
        return []

    if result.returncode != 0:
        logger.warning(
            "GitHub API error for %s: %s",
            repo,
            _sanitize_error(result.stderr.strip()),
        )
        return []

    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON from GitHub API for %s", repo)
        return []

    if not isinstance(items, list):
        return []

    signals = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            sig = _normalize_pr(
                item,
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
