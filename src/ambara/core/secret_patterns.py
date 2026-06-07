# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared credential pattern definitions.

These patterns back write/import policy, context rendering, and lightweight
capture checks so credential coverage cannot silently diverge by path.
"""

from __future__ import annotations

import re
from typing import Any

DEFAULT_SECRET_BLOCK_RULES: dict[str, dict[str, Any]] = {
    "secret.private_key": {
        "pattern": r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----",
        "flags": [],
    },
    "secret.github_token": {
        "pattern": r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{32,}\b",
        "flags": [],
    },
    "secret.github_fine_grained": {
        "pattern": r"\bgithub_pat_[A-Za-z0-9_]{22}_[A-Za-z0-9_]{59,}\b",
        "flags": [],
    },
    "secret.gitlab_token": {
        # GitLab's standard token prefixes are documented per token type.
        "pattern": (
            r"\b(?:glpat|gloas|gldt|glrt|glrtr|glcbt|glptt|glft|glimt|"
            r"glagent|glwt|glsoat|glffct)-[A-Za-z0-9_-]{16,}\b"
        ),
        "flags": [],
    },
    "secret.slack_token": {
        "pattern": r"\b(?:xox[baprs]-|xoxo-|xoxe[.-]|xapp-|xwfp-)[A-Za-z0-9.-]{10,}\b",
        "flags": [],
    },
    "secret.openai_key": {
        "pattern": r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b",
        "flags": [],
    },
    "secret.aws_access_key": {
        "pattern": r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        "flags": [],
    },
    "secret.stripe_live": {
        "pattern": r"\bsk_live_[A-Za-z0-9]{24,}\b",
        "flags": [],
    },
    "secret.google_api_key": {
        "pattern": r"\bAIza[0-9A-Za-z_-]{35}\b",
        "flags": [],
    },
    "secret.uri_credentials": {
        "pattern": r"\b[a-z][a-z0-9+.-]{2,}://[^/\s:@]+:[^@\s/]+@[^\s]+",
        "flags": ["ignorecase"],
    },
    "secret.password_assignment": {
        "pattern": r"\b(?:password|passwd|pwd)\b\s*[:=]\s*\S+",
        "flags": ["ignorecase"],
    },
    "secret.short_secret_assignment": {
        "pattern": r"\bsecret\b\s*[:=]\s*\S{8,}",
        "flags": ["ignorecase"],
    },
    "secret.assignment": {
        "pattern": (
            r"\b(?:password|passwd|pwd|token|secret|api[_-]?key|client_secret|"
            r"access_token|refresh_token|private_key)\b\s*[:=]\s*"
            r"""[\"']?[A-Za-z0-9_./+=-]{16,}[\"']?"""
        ),
        "flags": ["ignorecase"],
    },
    "secret.generic_api_key": {
        "pattern": r"(?:sk|pk|api[_-]?key)[_-]?[A-Za-z0-9-]{12,}",
        "flags": ["ignorecase"],
    },
}


def compile_flags(flag_list: list[str]) -> int:
    flags = 0
    for flag in flag_list:
        if flag.lower() == "ignorecase":
            flags |= re.IGNORECASE
    return flags


def compile_secret_patterns() -> list[re.Pattern[str]]:
    return [
        re.compile(str(spec["pattern"]), compile_flags(spec.get("flags", [])))
        for spec in DEFAULT_SECRET_BLOCK_RULES.values()
    ]
