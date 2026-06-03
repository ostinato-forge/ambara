# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""GitLab adapter — read labeled merge requests from configured repositories."""

from __future__ import annotations

import logging
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx

from ambara.core.pr_signals import PathStatus, PRSignal
from ambara.git.auth import AuthCandidate, read_token
from ambara.git.config import PRSignalsConfig
from ambara.providers.errors import SignalProviderError

logger = logging.getLogger(__name__)

_BODY_EXCERPT_LIMIT = 500


def _derive_target_areas(paths: list[str]) -> tuple[str, ...]:
    areas: set[str] = set()
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 2:
            areas.add("/".join(parts[:2]))
    return tuple(sorted(areas))


def _normalize_state(raw: str, *, merged_at: str | None) -> Literal["open", "merged", "closed"]:
    if merged_at:
        return "merged"
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


def _token_from_env(fallback: str | None) -> str | None:
    if fallback:
        return fallback
    return read_token(AuthCandidate(method="api_token", source="env_ambara")) or read_token(
        AuthCandidate(method="api_token", source="env_gl")
    )


def _base_url(config: PRSignalsConfig) -> str:
    return (config.gitlab_base_url or "https://gitlab.com").rstrip("/")


def _project_id(repo: str) -> str:
    return urllib.parse.quote(repo, safe="")


def _fetch_merge_request_list(
    repo: str,
    config: PRSignalsConfig,
    *,
    token: str,
) -> list[dict[str, object]]:
    since = datetime.now(UTC) - timedelta(days=config.recency_days)
    url = f"{_base_url(config)}/api/v4/projects/{_project_id(repo)}/merge_requests"
    try:
        resp = httpx.get(
            url,
            headers={"PRIVATE-TOKEN": token},
            params={
                "state": "all",
                "labels": config.label,
                "updated_after": since.isoformat().replace("+00:00", "Z"),
                "per_page": "30",
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise SignalProviderError(f"GitLab merge request search failed for {repo}: {exc}") from exc
    if resp.status_code != 200:
        raise SignalProviderError(f"GitLab merge request search failed for {repo}")
    payload = resp.json()
    if not isinstance(payload, list):
        raise SignalProviderError(f"GitLab merge request search failed for {repo}")
    return [item for item in payload if isinstance(item, dict)]


def _fetch_merge_request_detail(
    repo: str,
    iid: int,
    config: PRSignalsConfig,
    *,
    token: str,
) -> dict[str, object]:
    url = f"{_base_url(config)}/api/v4/projects/{_project_id(repo)}/merge_requests/{iid}"
    try:
        resp = httpx.get(url, headers={"PRIVATE-TOKEN": token}, timeout=30)
    except httpx.HTTPError as exc:
        raise SignalProviderError(f"GitLab MR detail fetch failed for {repo}!{iid}: {exc}") from exc
    if resp.status_code != 200:
        raise SignalProviderError(f"GitLab MR detail fetch failed for {repo}!{iid}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise SignalProviderError(f"GitLab MR detail fetch failed for {repo}!{iid}")
    return payload


def _fetch_merge_request_changes(
    repo: str,
    iid: int,
    config: PRSignalsConfig,
    *,
    token: str,
) -> list[str]:
    url = f"{_base_url(config)}/api/v4/projects/{_project_id(repo)}/merge_requests/{iid}/changes"
    try:
        resp = httpx.get(url, headers={"PRIVATE-TOKEN": token}, timeout=30)
    except httpx.HTTPError as exc:
        raise SignalProviderError(f"GitLab MR change fetch failed for {repo}!{iid}: {exc}") from exc
    if resp.status_code != 200:
        raise SignalProviderError(f"GitLab MR change fetch failed for {repo}!{iid}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise SignalProviderError(f"GitLab MR change fetch failed for {repo}!{iid}")
    changes = payload.get("changes", [])
    if not isinstance(changes, list):
        raise SignalProviderError(f"GitLab MR change fetch failed for {repo}!{iid}")
    paths: list[str] = []
    for item in changes:
        if isinstance(item, dict) and "new_path" in item:
            paths.append(str(item["new_path"]))
        elif isinstance(item, dict) and "old_path" in item:
            paths.append(str(item["old_path"]))
    return paths


def _extract_author(raw: dict[str, object]) -> str:
    author = raw.get("author")
    if isinstance(author, dict):
        return str(author.get("username") or author.get("name") or "unknown")
    return "unknown"


def _normalize_merge_request(
    raw: dict[str, object],
    repo: str,
    config: PRSignalsConfig,
) -> PRSignal:
    number = int(str(raw.get("iid", 0)))
    merged_at_raw = str(raw.get("merged_at", "") or "") or None
    state = _normalize_state(str(raw.get("state", "opened")), merged_at=merged_at_raw)

    labels_raw = raw.get("labels", [])
    labels = tuple(str(label) for label in labels_raw) if isinstance(labels_raw, list) else ()

    body_raw = str(raw.get("description", "") or "")
    body_excerpt: str | None = (
        body_raw[:_BODY_EXCERPT_LIMIT] if config.include_body_excerpt else None
    )

    changed_paths_status: PathStatus = "disabled"
    changed_paths_raw: list[str] = []
    if config.include_changed_paths:
        if "changes" in raw and isinstance(raw["changes"], list):
            changed_paths_status = "available"
            for item in raw["changes"]:
                if isinstance(item, dict) and "new_path" in item:
                    changed_paths_raw.append(str(item["new_path"]))
        else:
            changed_paths_status = "unavailable"

    created_at = _parse_datetime(str(raw.get("created_at") or ""))
    updated_at = _parse_datetime(str(raw.get("updated_at") or ""))
    merged_at = _parse_datetime(merged_at_raw)
    now = datetime.now(UTC)

    return PRSignal(
        signal_id=f"gitlab:{repo}:merge_request:{number}",
        provider="gitlab",
        repo=repo,
        number=number,
        url=str(
            raw.get(
                "web_url",
                f"{_base_url(config)}/{repo}/-/merge_requests/{number}",
            )
        ),
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


def fetch_labeled_merge_requests(
    config: PRSignalsConfig,
    repo: str,
    *,
    token: str | None = None,
) -> list[PRSignal]:
    if repo not in config.repos:
        return []

    auth_token = _token_from_env(token)
    if auth_token is None:
        raise SignalProviderError(f"GitLab merge request search failed for {repo}")

    items = _fetch_merge_request_list(repo, config, token=auth_token)
    signals: list[PRSignal] = []
    for item in items:
        try:
            iid = int(str(item.get("iid", 0)))
            raw = _fetch_merge_request_detail(repo, iid, config, token=auth_token)
            if config.include_changed_paths:
                paths = _fetch_merge_request_changes(repo, iid, config, token=auth_token)
                raw = {**raw, "changes": [{"new_path": path} for path in paths]}
            sig = _normalize_merge_request(raw, repo, config)
            signals.append(sig)
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("Skipping malformed GitLab MR from %s: %s", repo, exc)
            continue
    return signals


def fetch_all_signals(
    config: PRSignalsConfig,
    *,
    token: str | None = None,
) -> list[PRSignal]:
    all_signals: list[PRSignal] = []
    for repo in config.repos:
        all_signals.extend(fetch_labeled_merge_requests(config, repo, token=token))
    return all_signals
