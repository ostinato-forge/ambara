"""Context rendering with content safety annotations.

Pure module. Uses cached annotation records to decide what content
appears in context/query/search/read responses without re-scanning.
Also provides signal text sanitization for untrusted external content.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from jurati.core.content_annotations import AnnotationRecord
from jurati.core.content_policy import PolicyAction
from jurati.core.pr_signals import PRSignalEvidence

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_BLANK = re.compile(r"\n{3,}")

_CREDENTIAL_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22}_[A-Za-z0-9_]{59,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bsk_live_[A-Za-z0-9]{24,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\b[a-z][a-z0-9+.-]{2,}://[^/\s:@]+:[^@\s/]{3,}@[^\s]+", re.IGNORECASE),
    re.compile(
        r"\b(?:password|passwd|pwd|token|secret|api[_-]?key|client_secret|"
        r"access_token|refresh_token|private_key)\b\s*[:=]\s*"
        r"""[\"']?[A-Za-z0-9_./+=-]{16,}[\"']?""",
        re.IGNORECASE,
    ),
]

_SAFE_PATH = re.compile(r"^[A-Za-z0-9._/\-]+$")


def sanitize_untrusted_signal_text(
    raw: str | None,
    *,
    field: Literal["title", "excerpt"] = "excerpt",
    max_chars: int = 360,
) -> str | None:
    """Sanitize untrusted external text from PR/Jira signals."""
    if not raw:
        return None

    text = raw.strip()
    if not text:
        return None

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _ANSI_ESCAPE.sub("", text)
    text = _CONTROL_CHARS.sub(" ", text)

    for pattern in _CREDENTIAL_PATTERNS:
        text = pattern.sub("[redacted:credential]", text)

    text = _MULTI_BLANK.sub("\n\n", text)
    text = text.strip()

    if len(text) > max_chars:
        text = text[:max_chars] + "..."

    return text if text else None


def sanitize_signal_paths(
    paths: tuple[str, ...],
    *,
    max_paths: int = 20,
    max_path_len: int = 200,
) -> tuple[str, ...]:
    """Filter signal paths to safe values only."""
    safe: list[str] = []
    for p in paths:
        if not p or len(p) > max_path_len:
            continue
        if ".." in p or p.startswith("/"):
            continue
        if not _SAFE_PATH.match(p):
            continue
        safe.append(p)
        if len(safe) >= max_paths:
            break
    return tuple(safe)


class ContextRenderer:
    """Uses cached annotations to filter content on the read path."""

    def __init__(
        self,
        annotations: Mapping[str, AnnotationRecord],
        *,
        signal_title_max: int = 160,
        signal_excerpt_max: int = 360,
        signal_max_paths: int = 20,
    ) -> None:
        self._annotations = annotations
        self._signal_title_max = signal_title_max
        self._signal_excerpt_max = signal_excerpt_max
        self._signal_max_paths = signal_max_paths

    def should_include_entry(
        self,
        content_hash: str,
        *,
        mode: Literal["context", "search", "list", "read"] = "context",
    ) -> bool:
        """Decide whether an entry should appear in results."""
        record = self._annotations.get(content_hash)
        if record is None:
            return True

        if record.action == PolicyAction.BLOCK:
            return False

        if record.action == PolicyAction.REQUIRE_REVIEW and mode in (
            "context",
            "search",
            "list",
        ):
            return True

        return True

    def should_include_body(
        self,
        content_hash: str,
        *,
        mode: Literal["context", "search", "list", "read"] = "context",
    ) -> bool:
        """Decide whether an entry's body should be included."""
        record = self._annotations.get(content_hash)
        if record is None:
            return True

        if record.action == PolicyAction.BLOCK:
            return False

        return not (record.action == PolicyAction.REQUIRE_REVIEW and mode != "read")

    def render_signal_evidence(
        self,
        evidence: PRSignalEvidence,
    ) -> dict[str, Any]:
        """Render signal evidence with sanitization."""
        return {
            "repo": evidence.repo,
            "number": evidence.number,
            "url": evidence.url,
            "title": sanitize_untrusted_signal_text(
                evidence.title,
                field="title",
                max_chars=self._signal_title_max,
            ),
            "state": evidence.state,
            "updated_at": evidence.updated_at.isoformat(),
            "matched_paths": sanitize_signal_paths(
                evidence.matched_paths,
                max_paths=self._signal_max_paths,
            ),
            "reason": evidence.reason,
            "body_excerpt": sanitize_untrusted_signal_text(
                evidence.body_excerpt,
                field="excerpt",
                max_chars=self._signal_excerpt_max,
            ),
            "text_trust": "untrusted_external",
        }
