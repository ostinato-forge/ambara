"""Tests for agent-safe-start posture checks."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import git

from jurati.core.posture import (
    apply_gitignore_secret_patterns,
    check_agent_start_guardrails,
    missing_gitignore_secret_patterns,
)


def _init_repo(path: Path) -> git.Repo:
    path.mkdir()
    return git.Repo.init(path)


def _write_guarded_gitignore(repo_path: Path) -> None:
    (repo_path / ".gitignore").write_text("*.key\n*.pem\n.env\n.env.*\n!.env.example\n")


def test_agent_start_guardrails_ready_when_checks_pass(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo = _init_repo(repo_path)
    _write_guarded_gitignore(repo_path)
    (repo_path / "README.md").write_text("normal project notes\n")
    repo.index.add([".gitignore", "README.md"])

    report = check_agent_start_guardrails(
        repo_path,
        now=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )

    assert report.agent_start_guardrails_ready is True
    assert report.token_cost == "0 Nodrel tokens"
    assert report.checked_at == "2026-06-02T12:00:00Z"
    assert [check.status for check in report.checks] == ["ok", "ok", "ok", "ok"]
    assert report.findings == ()


def test_missing_gitignore_patterns_are_auto_fixable(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _init_repo(repo_path)
    (repo_path / ".gitignore").write_text("*.key\n")

    report = check_agent_start_guardrails(repo_path)

    assert report.agent_start_guardrails_ready is False
    assert report.findings[0].id == "gitignore.missing-secret-patterns"
    assert report.findings[0].auto_fixable is True
    assert report.findings[0].paths == (".gitignore",)
    assert missing_gitignore_secret_patterns(repo_path) == ("*.pem", ".env", ".env.*")


def test_apply_gitignore_fix_appends_only_missing_patterns(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _init_repo(repo_path)
    (repo_path / ".gitignore").write_text("*.key\n")

    added = apply_gitignore_secret_patterns(repo_path)

    assert added == ("*.pem", ".env", ".env.*")
    text = (repo_path / ".gitignore").read_text()
    assert text.count("*.key") == 1
    assert "# Nodrel agent-safe-start guardrails" in text
    assert "*.pem" in text
    assert "!.env.example" in text


def test_tracked_risky_secret_filename_blocks_ready(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo = _init_repo(repo_path)
    _write_guarded_gitignore(repo_path)
    (repo_path / ".env").write_text("placeholder=true\n")
    repo.index.add([".gitignore", ".env"])

    report = check_agent_start_guardrails(repo_path)

    assert report.agent_start_guardrails_ready is False
    finding = next(finding for finding in report.findings if finding.category == "tracked-files")
    assert finding.paths == (".env",)
    assert "placeholder=true" not in (finding.evidence or "")


def test_small_file_secret_smoke_reports_path_without_value(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo = _init_repo(repo_path)
    _write_guarded_gitignore(repo_path)
    secret_value = "abcdefgh" + "ijklmnop" + "1234"
    (repo_path / "config.txt").write_text(f"token = {secret_value}\n")
    repo.index.add([".gitignore", "config.txt"])

    report = check_agent_start_guardrails(repo_path)

    assert report.agent_start_guardrails_ready is False
    finding = next(finding for finding in report.findings if finding.category == "secrets")
    assert finding.paths == ("config.txt",)
    assert secret_value not in finding.summary
    assert secret_value not in (finding.evidence or "")
