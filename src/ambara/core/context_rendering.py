# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Context rendering with content safety annotations.

Pure module. Uses cached annotation records to decide what content
appears in context/query/search/read responses without re-scanning.
Also provides source text sanitization for untrusted external content.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

from ambara.core.content_annotations import AnnotationRecord
from ambara.core.content_policy import PolicyAction
from ambara.core.pr_signals import PRSignalEvidence
from ambara.core.secret_patterns import compile_secret_patterns

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MARKDOWN_FENCE_LINE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_MARKDOWN_CONTROL_PREFIX = re.compile(
    r"^\s{0,3}(?:"
    r"#{1,6}\s+|"
    r">\s*|"
    r"[-*+]\s+\[[ xX]\]\s*|"
    r"[-*+]\s+|"
    r"\d+[.)]\s+"
    r")"
)
_MARKDOWN_LINK = re.compile(r"!?\[([^\]\n]+)\]\([^)]+\)")
_MARKDOWN_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_MARKDOWN_INLINE_MARKERS = re.compile(r"\*\*|__|~~")

_CREDENTIAL_PATTERNS = compile_secret_patterns()

_SAFE_PATH = re.compile(r"^[A-Za-z0-9._/\-]+$")


def sanitize_untrusted_source_text(
    raw: str | None,
    *,
    field: Literal["title", "excerpt"] = "excerpt",
    max_chars: int = 360,
) -> str | None:
    """Sanitize untrusted external text from source artifacts."""
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

    text = " ".join(
        line for line in (_plain_source_line(line) for line in text.split("\n")) if line
    )
    text = text.strip()

    if len(text) > max_chars:
        text = text[:max_chars] + "..."

    return text if text else None


def source_text_contains_markdown_syntax(raw: str | None) -> bool:
    """Return whether source text contains markdown that core will flatten."""
    if not raw:
        return False

    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    for line in text.split("\n"):
        if _MARKDOWN_FENCE_LINE.match(line) or _MARKDOWN_CONTROL_PREFIX.match(line):
            return True
        if _MARKDOWN_LINK.search(line) or _MARKDOWN_CODE_SPAN.search(line):
            return True
        if _MARKDOWN_INLINE_MARKERS.search(line):
            return True
    return False


def _plain_source_line(line: str) -> str:
    """Flatten provider-authored markdown into plain inline evidence."""
    stripped = line.strip()
    if not stripped or _MARKDOWN_FENCE_LINE.match(stripped):
        return ""

    text = _MARKDOWN_CONTROL_PREFIX.sub("", stripped).strip()
    text = _MARKDOWN_LINK.sub(lambda match: match.group(1).strip(), text)
    text = _MARKDOWN_CODE_SPAN.sub(lambda match: match.group(1).strip(), text)
    text = _MARKDOWN_INLINE_MARKERS.sub("", text)
    return " ".join(text.split())


def sanitize_untrusted_signal_text(
    raw: str | None,
    *,
    field: Literal["title", "excerpt"] = "excerpt",
    max_chars: int = 360,
) -> str | None:
    return sanitize_untrusted_source_text(raw, field=field, max_chars=max_chars)


def sanitize_source_paths(
    paths: tuple[str, ...],
    *,
    max_paths: int = 20,
    max_path_len: int = 200,
) -> tuple[str, ...]:
    """Filter source-provided paths to safe values only."""
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


def sanitize_signal_paths(
    paths: tuple[str, ...],
    *,
    max_paths: int = 20,
    max_path_len: int = 200,
) -> tuple[str, ...]:
    return sanitize_source_paths(paths, max_paths=max_paths, max_path_len=max_path_len)


def safe_artifact_ref(value: str) -> str | None:
    try:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        if parsed.username or parsed.password:
            return None
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    except ValueError:
        # Malformed refs (e.g. unterminated IPv6 literals, invalid ports) are
        # untrusted input: reject them rather than letting the parse error escape.
        return None


class ContextRenderer:
    """Uses cached annotations to filter content on the read path."""

    def __init__(
        self,
        annotations: Mapping[str, AnnotationRecord],
        *,
        source_title_max: int | None = None,
        source_excerpt_max: int | None = None,
        source_max_paths: int | None = None,
        signal_title_max: int | None = None,
        signal_excerpt_max: int | None = None,
        signal_max_paths: int | None = None,
    ) -> None:
        self._annotations = annotations
        self._source_title_max = (
            source_title_max if source_title_max is not None else signal_title_max or 160
        )
        self._source_excerpt_max = (
            source_excerpt_max if source_excerpt_max is not None else signal_excerpt_max or 360
        )
        self._source_max_paths = (
            source_max_paths if source_max_paths is not None else signal_max_paths or 20
        )

    def should_include_entry(
        self,
        content_hash: str,
        *,
        mode: Literal["context", "search", "list", "read"] = "context",
    ) -> bool:
        """Decide whether an entry should appear in results."""
        record = self._annotations.get(content_hash)
        return not (record is not None and record.action == PolicyAction.BLOCK)

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

    def render_source_evidence(
        self,
        evidence: PRSignalEvidence,
    ) -> dict[str, Any]:
        """Render source evidence with central sanitization."""
        return {
            "repo": evidence.repo,
            "number": evidence.number,
            "url": evidence.url,
            "title": sanitize_untrusted_source_text(
                evidence.title,
                field="title",
                max_chars=self._source_title_max,
            ),
            "state": evidence.state,
            "updated_at": evidence.updated_at.isoformat(),
            "matched_paths": sanitize_source_paths(
                evidence.matched_paths,
                max_paths=self._source_max_paths,
            ),
            "reason": evidence.reason,
            "body_excerpt": sanitize_untrusted_source_text(
                evidence.body_excerpt,
                field="excerpt",
                max_chars=self._source_excerpt_max,
            ),
            "text_trust": "untrusted_external",
        }

    def render_signal_evidence(
        self,
        evidence: PRSignalEvidence,
    ) -> dict[str, Any]:
        return self.render_source_evidence(evidence)
