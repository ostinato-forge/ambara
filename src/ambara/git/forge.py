# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Forge-aware remote parsing and branch review URLs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode, urlparse

ForgeKind = Literal["github", "gitlab", "unknown"]


@dataclass(frozen=True)
class RemoteRef:
    forge: ForgeKind
    host: str
    namespace: str
    repo: str

    @property
    def path(self) -> str:
        return f"{self.namespace}/{self.repo}"

    @property
    def web_base(self) -> str:
        return f"https://{self.host}/{self.path}"


def detect_forge(host: str) -> ForgeKind:
    normalized = host.lower().strip()
    if normalized == "github.com" or normalized.endswith(".github.com"):
        return "github"
    if normalized == "gitlab.com" or normalized.endswith(".gitlab.com") or "gitlab" in normalized:
        return "gitlab"
    return "unknown"


def parse_remote(url: str) -> RemoteRef | None:
    raw = url.strip()
    if not raw:
        return None

    host: str | None = None
    path: str | None = None

    if raw.startswith(("https://", "http://", "ssh://")):
        parsed = urlparse(raw)
        if not parsed.hostname or not parsed.path:
            return None
        host = parsed.hostname
        path = parsed.path.lstrip("/")
    elif ":" in raw and "@" in raw:
        prefix, suffix = raw.split(":", 1)
        if "@" not in prefix or not suffix:
            return None
        host = prefix.rsplit("@", 1)[-1]
        path = suffix
    else:
        return None

    cleaned = path.removesuffix(".git").strip("/")
    parts = [part for part in cleaned.split("/") if part]
    if len(parts) < 2:
        return None

    return RemoteRef(
        forge=detect_forge(host),
        host=host,
        namespace="/".join(parts[:-1]),
        repo=parts[-1],
    )


def branch_review_url(remote: RemoteRef, *, base: str, branch: str) -> str | None:
    if remote.forge == "github":
        return f"{remote.web_base}/compare/{base}...{branch}?expand=1"
    if remote.forge == "gitlab":
        params = urlencode(
            {
                "merge_request[source_branch]": branch,
                "merge_request[target_branch]": base,
            }
        )
        return f"{remote.web_base}/-/merge_requests/new?{params}"
    return None
