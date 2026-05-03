"""Commit message parsing and ID derivation for the jurati: capture pipeline."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from jurati.core.schema import EntryType, EscalationLevel

_JURATI_RE = re.compile(r"^jurati(?:\(([a-z]+)\))?:\s*(.+)$", re.MULTILINE)

_TAG_MAP: dict[str, tuple[EntryType, EscalationLevel]] = {
    "decision": (EntryType.DECISION, EscalationLevel.L2),
    "principle": (EntryType.PRINCIPLE, EscalationLevel.L3),
    "workflow": (EntryType.WORKFLOW, EscalationLevel.L2),
}

_DEFAULT_TYPE = EntryType.PROJECT
_DEFAULT_LEVEL = EscalationLevel.L1

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

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class CaptureResult:
    title: str
    body: str
    tag: str | None
    entry_type: EntryType
    level: EscalationLevel


def parse_commit_message(message: str) -> CaptureResult | None:
    first_line = message.split("\n", 1)[0]
    match = _JURATI_RE.match(first_line)
    if not match:
        return None

    tag = match.group(1)
    title = match.group(2).strip()
    if not title:
        return None

    entry_type, level = _TAG_MAP.get(tag, (_DEFAULT_TYPE, _DEFAULT_LEVEL))

    body = ""
    parts = message.split("\n", 1)
    if len(parts) > 1:
        body = parts[1].strip()

    return CaptureResult(
        title=title,
        body=body,
        tag=tag,
        entry_type=entry_type,
        level=level,
    )


def derive_entry_id(
    repo_slug: str,
    title: str,
    *,
    commit_sha: str | None = None,
    collision: bool = False,
) -> str:
    slug = _SLUG_RE.sub("-", f"{repo_slug}-{title}".lower()).strip("-")
    if len(slug) > 120:
        slug = slug[:120].rstrip("-")

    if collision and commit_sha:
        raw = f"{repo_slug}:{commit_sha}:{title}"
        short_hash = hashlib.sha256(raw.encode()).hexdigest()[:6]
        suffix = f"-{short_hash}"
        if len(slug) + len(suffix) > 120:
            slug = slug[: 120 - len(suffix)]
        slug = f"{slug}{suffix}"

    return slug


def scan_secrets(text: str, extra_patterns: list[re.Pattern[str]] | None = None) -> bool:
    patterns = _SECRET_PATTERNS + (extra_patterns or [])
    return any(p.search(text) for p in patterns)
