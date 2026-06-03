# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Jira adapter — read labeled issues from configured projects.

Uses httpx for REST API calls against the Jira v3 search/jql endpoint
(Atlassian Cloud retired v2 in 2025). Auth via JIRA_API_TOKEN (Bearer)
or JIRA_USER + JIRA_API_TOKEN (Basic). Tokens are never stored on
long-lived state; errors are sanitized to redact credentials.
"""

from __future__ import annotations

import base64
import logging
import os
import random
import re
import time
from datetime import UTC, datetime

import httpx

from ambara.core.pr_signals import CoordinationSignal
from ambara.git.config import PRSignalsConfig
from ambara.providers.errors import SignalProviderError

logger = logging.getLogger(__name__)

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+/=]{20,}")
_EXCERPT_LIMIT = 500
_MAX_RESULTS_PER_PAGE = 50
_REQUEST_TIMEOUT = 30
_MAX_RETRIES = 2
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503})

_STATUS_MAP: dict[str, str] = {
    "to do": "open",
    "in progress": "open",
    "in review": "open",
    "done": "resolved",
    "closed": "closed",
    "resolved": "resolved",
    "won't do": "closed",
    "cancelled": "closed",
}


def _sanitize_error(message: str) -> str:
    return _TOKEN_PATTERN.sub("[REDACTED]", message)


def _map_status(raw_status: str) -> str:
    return _STATUS_MAP.get(raw_status.lower(), "open")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    if "." in value and "+" in value:
        before_tz = value.split("+")[0]
        tz_part = "+" + value.split("+")[1]
        dot_part = before_tz.split(".")
        ms = dot_part[1][:6]
        value = f"{dot_part[0]}.{ms}{tz_part}"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _build_auth_headers(token: str | None) -> dict[str, str]:
    if token is None:
        token = os.environ.get("JIRA_API_TOKEN")
    if not token:
        return {}

    user = os.environ.get("JIRA_USER")
    if user:
        encoded = base64.b64encode(f"{user}:{token}".encode()).decode()
        return {"Authorization": f"Basic {encoded}"}
    return {"Authorization": f"Bearer {token}"}


def _run_jira_api(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, str | int] | None = None,
    description: str,
) -> dict[str, object] | None:
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = client.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        except httpx.TimeoutException:
            logger.warning("Jira API %s timed out", description)
            return None
        except httpx.ConnectError as exc:
            logger.warning(
                "Jira API %s connection error: %s",
                description,
                _sanitize_error(str(exc)),
            )
            return None

        if resp.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
            delay = (2**attempt) + random.uniform(0, 1)
            logger.warning(
                "Jira API %s returned %d, retrying in %.1fs (%d/%d)",
                description,
                resp.status_code,
                delay,
                attempt + 1,
                _MAX_RETRIES,
            )
            time.sleep(delay)
            continue

        if resp.status_code == 401:
            logger.warning("Jira API %s: authentication failed (401)", description)
            return None
        if resp.status_code == 403:
            logger.warning("Jira API %s: access denied (403)", description)
            return None
        if resp.status_code >= 400:
            logger.warning(
                "Jira API %s error: %d %s",
                description,
                resp.status_code,
                _sanitize_error(resp.text[:200]),
            )
            return None

        try:
            data = resp.json()
            return data if isinstance(data, dict) else None
        except ValueError:
            logger.warning("Jira API %s: invalid JSON response", description)
            return None

    return None


def _normalize_issue(
    raw: dict[str, object],
    *,
    base_url: str,
    include_body_excerpt: bool,
) -> CoordinationSignal:
    key = str(raw.get("key", ""))
    project_key = key.split("-")[0] if "-" in key else key

    fields = raw.get("fields", {})
    if not isinstance(fields, dict):
        fields = {}

    status_raw = fields.get("status", {})
    status_name = ""
    if isinstance(status_raw, dict):
        status_name = str(status_raw.get("name", ""))
    state = _map_status(status_name)

    labels_raw = fields.get("labels", [])
    labels = tuple(str(lb) for lb in labels_raw) if isinstance(labels_raw, list) else ()

    components_raw = fields.get("components", [])
    components: tuple[str, ...] = ()
    if isinstance(components_raw, list):
        components = tuple(
            str(c.get("name", "")) for c in components_raw if isinstance(c, dict) and c.get("name")
        )

    assignee_raw = fields.get("assignee")
    reporter_raw = fields.get("reporter")
    actor = "unknown"
    if isinstance(assignee_raw, dict):
        actor = str(assignee_raw.get("displayName", assignee_raw.get("name", "unknown")))
    elif isinstance(reporter_raw, dict):
        actor = str(reporter_raw.get("displayName", reporter_raw.get("name", "unknown")))

    desc_raw = fields.get("description")
    description = _extract_adf_text(desc_raw) if isinstance(desc_raw, dict) else str(desc_raw or "")
    excerpt = description[:_EXCERPT_LIMIT] if include_body_excerpt else None

    created = _parse_datetime(str(fields.get("created", "") or ""))
    updated = _parse_datetime(str(fields.get("updated", "") or ""))
    resolution_date = _parse_datetime(str(fields.get("resolutiondate", "") or ""))
    now = datetime.now(UTC)

    url = f"{base_url.rstrip('/')}/browse/{key}"

    return CoordinationSignal(
        signal_id=f"jira:{project_key}:issue:{key}",
        provider="jira",
        source=project_key,
        artifact_ref=url,
        title=str(fields.get("summary", "")),
        excerpt=excerpt,
        actor=actor,
        state=state,
        labels=labels,
        created_at=created or now,
        updated_at=updated or now,
        resolved_at=resolution_date,
        subject_refs=(),
        subject_areas=components,
        subject_refs_status="disabled",
    )


def _extract_adf_text(node: dict[str, object] | object) -> str:
    """Extract plain text from Atlassian Document Format (ADF) JSON."""
    if not isinstance(node, dict):
        return str(node) if node else ""
    if node.get("type") == "text":
        return str(node.get("text", ""))
    content = node.get("content")
    if not isinstance(content, list):
        return ""
    parts = [_extract_adf_text(child) for child in content]
    block_types = {"paragraph", "heading", "bulletList", "orderedList", "listItem", "blockquote"}
    sep = "\n" if node.get("type") in block_types else ""
    return sep.join(parts)


def _build_jql(config: PRSignalsConfig) -> str:
    parts: list[str] = []
    if config.jira_projects:
        projects = ", ".join(config.jira_projects)
        parts.append(f"project in ({projects})")
    parts.append(f'labels = "{config.label}"')
    parts.append(f'updated >= "-{config.recency_days}d"')
    return " AND ".join(parts)


def fetch_all_signals(
    config: PRSignalsConfig,
    *,
    token: str | None = None,
) -> list[CoordinationSignal]:
    base_url = config.jira_base_url
    if not base_url:
        logger.debug("Jira provider configured but no AMBARA_JIRA_BASE_URL set")
        return []

    if not config.jira_projects:
        logger.debug("Jira provider configured but no AMBARA_JIRA_PROJECTS set")
        return []

    headers = _build_auth_headers(token)
    if not headers:
        raise SignalProviderError("Jira provider authentication is not configured")

    jql = _build_jql(config)
    search_url = f"{base_url.rstrip('/')}/rest/api/3/search/jql"

    signals: list[CoordinationSignal] = []

    with httpx.Client(headers=headers) as client:
        data = _run_jira_api(
            client,
            search_url,
            params={
                "jql": jql,
                "maxResults": _MAX_RESULTS_PER_PAGE,
                "fields": (
                    "summary,status,labels,components,"
                    "assignee,reporter,description,"
                    "created,updated,resolutiondate"
                ),
            },
            description="search",
        )

        if data is None:
            raise SignalProviderError("Jira search failed")

        issues = data.get("issues", [])
        if not isinstance(issues, list):
            raise SignalProviderError("Jira search returned an invalid issues payload")

        for issue in issues:
            if not isinstance(issue, dict):
                continue
            try:
                signal = _normalize_issue(
                    issue,
                    base_url=base_url,
                    include_body_excerpt=config.include_body_excerpt,
                )
                signals.append(signal)
            except (KeyError, ValueError, TypeError) as exc:
                logger.debug("Skipping malformed Jira issue: %s", exc)

    return signals
