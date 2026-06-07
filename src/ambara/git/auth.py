# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""GitHub auth candidate generation and prompt-safe subprocess helpers."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Literal

from ambara.git.forge import parse_remote


def parse_github_remote(url: str) -> tuple[str, str] | None:
    remote = parse_remote(url)
    if remote is None or remote.forge != "github":
        return None
    if "/" in remote.namespace:
        return None
    return (remote.namespace, remote.repo)


@dataclass(frozen=True)
class AuthCandidate:
    method: Literal["api_token", "gh_cli", "branch_only"]
    source: Literal[
        "env_ambara",
        "env_gh",
        "env_gl",
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
    if candidate.source == "env_ambara":
        return os.environ.get("AMBARA_KNOWLEDGE_TOKEN")

    if candidate.source == "env_gh":
        return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    if candidate.source == "env_gl":
        return os.environ.get("GL_TOKEN") or os.environ.get("GITLAB_TOKEN")

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

    if os.environ.get("AMBARA_KNOWLEDGE_TOKEN"):
        candidates.append(
            AuthCandidate(
                method="api_token",
                source="env_ambara",
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


def generate_gitlab_candidates(namespace: str, repo: str) -> list[AuthCandidate]:
    candidates: list[AuthCandidate] = []

    if os.environ.get("AMBARA_KNOWLEDGE_TOKEN"):
        candidates.append(
            AuthCandidate(
                method="api_token",
                source="env_ambara",
                owner=namespace,
                repo=repo,
            )
        )

    if os.environ.get("GL_TOKEN") or os.environ.get("GITLAB_TOKEN"):
        candidates.append(
            AuthCandidate(
                method="api_token",
                source="env_gl",
                owner=namespace,
                repo=repo,
            )
        )

    return candidates
