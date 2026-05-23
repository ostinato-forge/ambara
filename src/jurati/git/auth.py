"""GitHub auth candidate generation and prompt-safe subprocess helpers."""

from __future__ import annotations

import json
import os
import re
import subprocess
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


def _gh_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GH_PROMPT_DISABLED"] = "1"
    return env


def discover_gh_users() -> list[str]:
    try:
        result = subprocess.run(
            ["gh", "auth", "status", "--hostname", "github.com", "--json", "hosts"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            env=_gh_subprocess_env(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    if result.returncode != 0:
        return []

    try:
        data = json.loads(result.stdout)
        accounts = data.get("hosts", {}).get("github.com", [])
        if not isinstance(accounts, list):
            return []
        return sorted(
            a["login"]
            for a in accounts
            if isinstance(a, dict) and a.get("state") == "success" and "login" in a
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def read_token(candidate: AuthCandidate) -> str | None:
    if candidate.source == "env_jurati":
        return os.environ.get("JURATI_KNOWLEDGE_TOKEN")

    if candidate.source == "env_gh":
        return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    if candidate.source == "gh_user_token" and candidate.gh_user:
        try:
            result = subprocess.run(
                [
                    "gh",
                    "auth",
                    "token",
                    "--hostname",
                    "github.com",
                    "--user",
                    candidate.gh_user,
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=15,
                env=_gh_subprocess_env(),
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    return None


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
