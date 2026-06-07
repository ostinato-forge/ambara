# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Agent-safe-start posture checks."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ambara.core.secrets import scan_secrets

REQUIRED_GITIGNORE_PATTERNS = ("*.key", "*.pem", ".env", ".env.*")
GITIGNORE_SECTION_HEADER = "# Ambara agent-safe-start guardrails"
MAX_SECRET_SCAN_BYTES = 64 * 1024
_BINARY_SUFFIXES = {
    ".7z",
    ".avif",
    ".bin",
    ".bmp",
    ".bz2",
    ".class",
    ".db",
    ".dll",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".webp",
    ".zip",
}
_ALLOWED_ENV_EXAMPLES = {".env.example", ".env.sample", ".env.template"}


@dataclass(frozen=True)
class PostureFinding:
    id: str
    category: str
    level: str
    summary: str
    evidence: str | None
    remediation: str | None
    auto_fixable: bool
    paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "level": self.level,
            "summary": self.summary,
            "evidence": self.evidence,
            "remediation": self.remediation,
            "auto_fixable": self.auto_fixable,
            "paths": list(self.paths),
        }


@dataclass(frozen=True)
class PostureCheck:
    id: str
    status: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "summary": self.summary}


@dataclass(frozen=True)
class PostureReport:
    repo: str
    agent_start_guardrails_ready: bool
    checked_at: str
    checks: tuple[PostureCheck, ...]
    findings: tuple[PostureFinding, ...]
    token_cost: str = "0 Ambara tokens"

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "agent_start_guardrails_ready": self.agent_start_guardrails_ready,
            "checked_at": self.checked_at,
            "checks": [check.to_dict() for check in self.checks],
            "findings": [finding.to_dict() for finding in self.findings],
            "token_cost": self.token_cost,
        }


def check_agent_start_guardrails(repo: Path, now: datetime | None = None) -> PostureReport:
    """Check whether a repo has minimum anti-secret guardrails before agent work."""

    checked_at = _checked_at(now)
    root_result = _git_root(repo)
    if root_result is None:
        finding = PostureFinding(
            id="git.not-worktree",
            category="git",
            level="error",
            summary="Target path is not inside a git worktree",
            evidence=None,
            remediation="Run from a git repository or pass --repo-path to one.",
            auto_fixable=False,
            paths=(),
        )
        return PostureReport(
            repo=str(repo),
            agent_start_guardrails_ready=False,
            checked_at=checked_at,
            checks=(
                PostureCheck(
                    id="git.worktree",
                    status="error",
                    summary="Target path is not inside a git worktree",
                ),
            ),
            findings=(finding,),
        )

    root = root_result
    findings: list[PostureFinding] = []
    checks = [
        PostureCheck(id="git.worktree", status="ok", summary="Target path is a git worktree")
    ]

    missing_patterns = missing_gitignore_secret_patterns(root)
    if missing_patterns:
        findings.append(
            PostureFinding(
                id="gitignore.missing-secret-patterns",
                category="gitignore",
                level="error",
                summary=f".gitignore missing {', '.join(missing_patterns)}",
                evidence=", ".join(missing_patterns),
                remediation="Append Ambara's marked secret-pattern section to .gitignore.",
                auto_fixable=True,
                paths=(".gitignore",),
            )
        )
        checks.append(
            PostureCheck(
                id="gitignore.secret-coverage",
                status="error",
                summary=".gitignore is missing required secret artifact patterns",
            )
        )
    else:
        checks.append(
            PostureCheck(
                id="gitignore.secret-coverage",
                status="ok",
                summary=".gitignore covers common secret artifacts",
            )
        )

    tracked_files = _tracked_files(root)
    risky_paths = tracked_risky_secret_paths(tracked_files)
    if risky_paths:
        findings.append(
            PostureFinding(
                id="tracked-files.risky-secret-names",
                category="tracked-files",
                level="error",
                summary="Git is tracking obvious secret artifact filenames",
                evidence=f"{len(risky_paths)} tracked risky path(s)",
                remediation="Remove committed secret artifacts and rotate exposed credentials.",
                auto_fixable=False,
                paths=risky_paths,
            )
        )
        checks.append(
            PostureCheck(
                id="tracked-files.secret-names",
                status="error",
                summary="Git is tracking obvious secret artifact filenames",
            )
        )
    else:
        checks.append(
            PostureCheck(
                id="tracked-files.secret-names",
                status="ok",
                summary="Git is not tracking obvious secret artifact filenames",
            )
        )

    secret_paths = small_file_secret_smoke(root, tracked_files)
    if secret_paths:
        findings.append(
            PostureFinding(
                id="secrets.small-file-smoke",
                category="secrets",
                level="error",
                summary="Small tracked text files contain credential-shaped content",
                evidence=f"{len(secret_paths)} tracked text file(s) matched secret patterns",
                remediation="Remove secrets from tracked files and rotate exposed credentials.",
                auto_fixable=False,
                paths=secret_paths,
            )
        )
        checks.append(
            PostureCheck(
                id="secrets.small-file-smoke",
                status="error",
                summary="Small tracked text files matched secret patterns",
            )
        )
    else:
        checks.append(
            PostureCheck(
                id="secrets.small-file-smoke",
                status="ok",
                summary="Small tracked text files did not match secret patterns",
            )
        )

    return PostureReport(
        repo=str(root),
        agent_start_guardrails_ready=not findings,
        checked_at=checked_at,
        checks=tuple(checks),
        findings=tuple(findings),
    )


def missing_gitignore_secret_patterns(repo: Path) -> tuple[str, ...]:
    patterns = _gitignore_patterns(repo / ".gitignore")
    return tuple(pattern for pattern in REQUIRED_GITIGNORE_PATTERNS if pattern not in patterns)


def apply_gitignore_secret_patterns(repo: Path) -> tuple[str, ...]:
    """Append the missing Ambara .gitignore section and return added patterns."""

    root = _git_root(repo)
    if root is None:
        return ()

    missing = missing_gitignore_secret_patterns(root)
    if not missing:
        return ()

    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    lines = [GITIGNORE_SECTION_HEADER, *missing]
    if ".env" in missing or ".env.*" in missing:
        lines.append("!.env.example")
    section = "\n".join(lines) + "\n"
    if existing.strip():
        section = "\n" + section
    gitignore.write_text(existing + prefix + section, encoding="utf-8")
    return missing


def tracked_risky_secret_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(path for path in paths if _is_risky_secret_path(path))


def small_file_secret_smoke(repo: Path, tracked_files: tuple[str, ...]) -> tuple[str, ...]:
    matches: list[str] = []
    for rel_path in tracked_files:
        if _is_risky_secret_path(rel_path):
            continue
        path = repo / rel_path
        if not _should_scan_file(path):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data:
            continue
        text = data.decode("utf-8", errors="ignore")
        if scan_secrets(text):
            matches.append(rel_path)
    return tuple(matches)


def _checked_at(now: datetime | None) -> str:
    value = now or datetime.now(UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _git_root(repo: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return Path(result.stdout.strip()).resolve()


def _tracked_files(repo: Path) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repo,
            text=False,
            capture_output=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ()
    return tuple(
        path.decode("utf-8", errors="ignore") for path in result.stdout.split(b"\0") if path
    )


def _gitignore_patterns(path: Path) -> set[str]:
    if not path.exists():
        return set()

    patterns: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("!"):
            continue
        patterns.add(stripped.removeprefix("/"))
    return patterns


def _is_risky_secret_path(path: str) -> bool:
    name = Path(path).name
    lower = name.lower()
    if lower in _ALLOWED_ENV_EXAMPLES:
        return False
    if lower == ".env" or lower.startswith(".env."):
        return True
    if lower.endswith((".key", ".pem", ".p12", ".pfx")):
        return True
    if lower in {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}:
        return True
    return lower in {"credentials.json", "service-account.json"}


def _should_scan_file(path: Path) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    if not path.is_file() or stat.st_size > MAX_SECRET_SCAN_BYTES:
        return False
    return path.suffix.lower() not in _BINARY_SUFFIXES
