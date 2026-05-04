"""GitHub auth candidate generation and prompt-safe subprocess helpers."""

from __future__ import annotations

import re

_SSH_COLON = re.compile(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$")
_HTTPS = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$")
_SSH_URL = re.compile(r"^ssh://git@github\.com/([^/]+)/([^/]+?)(?:\.git)?$")


def parse_github_remote(url: str) -> tuple[str, str] | None:
    for pattern in (_SSH_COLON, _HTTPS, _SSH_URL):
        m = pattern.match(url)
        if m:
            return (m.group(1), m.group(2))
    return None
