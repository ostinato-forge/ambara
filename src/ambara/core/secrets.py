"""Secret detection helpers shared by import and capture paths."""

from __future__ import annotations

import re

from ambara.core.secret_patterns import compile_secret_patterns

_SECRET_PATTERNS = compile_secret_patterns()


def scan_secrets(text: str, extra_patterns: list[re.Pattern[str]] | None = None) -> bool:
    """Return true when text contains credential-shaped material."""

    patterns = _SECRET_PATTERNS + (extra_patterns or [])
    return any(pattern.search(text) for pattern in patterns)
