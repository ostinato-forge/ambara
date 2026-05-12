"""Secret detection helpers shared by import and capture paths."""

from __future__ import annotations

import re

_SECRET_PATTERNS = [
    re.compile(r"(?:sk|pk|api[_-]?key)[_-]?[a-zA-Z0-9-]{12,}", re.IGNORECASE),
    re.compile(r"ghp_[a-zA-Z0-9]{32,}"),
    re.compile(r"gho_[a-zA-Z0-9]{32,}"),
    re.compile(r"password\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"token\s*[=:]\s*\S{16,}", re.IGNORECASE),
    re.compile(r"secret\s*[=:]\s*\S{8,}", re.IGNORECASE),
    re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),
    re.compile(r"[a-z+]+://[^:]+:[^@]+@", re.IGNORECASE),
]


def scan_secrets(text: str, extra_patterns: list[re.Pattern[str]] | None = None) -> bool:
    """Return true when text contains credential-shaped material."""

    patterns = _SECRET_PATTERNS + (extra_patterns or [])
    return any(pattern.search(text) for pattern in patterns)
