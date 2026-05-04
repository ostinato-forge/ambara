"""GitHub auth candidate generation and prompt-safe subprocess helpers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal

_SSH_COLON = re.compile(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$")
_HTTPS = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$")
_SSH_URL = re.compile(r"^ssh://git@github\.com/([^/]+)/([^/]+?)(?:\.git)?$")


def parse_github_remote(url: str) -> tuple[str, str] | None:
    for pattern in (_SSH_COLON, _HTTPS, _SSH_URL):
        m = pattern.match(url)
        if m:
            return (m.group(1), m.group(2))
    return None


@dataclass(frozen=True)
class AuthCandidate:
    method: Literal["api_token", "gh_cli", "branch_only"]
    source: Literal[
        "env_jurati",
        "env_gh",
        "gh_user_token",
        "gh_cli_pr",
        "none",
    ]
    owner: str | None = None
    repo: str | None = None
    gh_user: str | None = None


def discover_gh_users() -> list[str]:
    return []


def generate_candidates(owner: str, repo: str) -> list[AuthCandidate]:
    candidates: list[AuthCandidate] = []

    if os.environ.get("JURATI_KNOWLEDGE_TOKEN"):
        candidates.append(
            AuthCandidate(
                method="api_token",
                source="env_jurati",
                owner=owner,
                repo=repo,
            )
        )

    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        candidates.append(
            AuthCandidate(
                method="api_token",
                source="env_gh",
                owner=owner,
                repo=repo,
            )
        )

    for user in discover_gh_users():
        candidates.append(
            AuthCandidate(
                method="api_token",
                source="gh_user_token",
                owner=owner,
                repo=repo,
                gh_user=user,
            )
        )

    candidates.append(
        AuthCandidate(
            method="gh_cli",
            source="gh_cli_pr",
            owner=owner,
            repo=repo,
        )
    )

    return candidates
