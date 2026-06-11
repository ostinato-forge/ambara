# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for agent-safe-start posture checks."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import git

from ambara.core.posture import (
    _gitignore_patterns,
    _is_risky_secret_path,
    _should_scan_file,
    _tracked_files,
    apply_gitignore_secret_patterns,
    check_agent_start_guardrails,
    missing_gitignore_secret_patterns,
    small_file_secret_smoke,
)
from ambara.posture import check_agent_start_guardrails as ambara_check_agent_start_guardrails


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
    assert report.token_cost == "0 Ambara tokens"
    assert report.checked_at == "2026-06-02T12:00:00Z"
    assert [check.status for check in report.checks] == ["ok", "ok", "ok", "ok"]
    assert report.findings == ()


def test_ambara_posture_import_surface_delegates(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo = _init_repo(repo_path)
    _write_guarded_gitignore(repo_path)
    (repo_path / "README.md").write_text("normal project notes\n")
    repo.index.add([".gitignore", "README.md"])

    report = ambara_check_agent_start_guardrails(repo_path)

    assert report.agent_start_guardrails_ready is True


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
    assert "# Ambara agent-safe-start guardrails" in text
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


def test_check_reports_error_when_path_is_not_a_git_worktree(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()

    report = check_agent_start_guardrails(
        not_a_repo,
        now=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )

    assert report.agent_start_guardrails_ready is False
    assert [check.id for check in report.checks] == ["git.worktree"]
    assert report.checks[0].status == "error"
    assert report.findings[0].id == "git.not-worktree"
    assert report.findings[0].auto_fixable is False
    assert report.checked_at == "2026-06-02T12:00:00Z"


def test_apply_gitignore_is_noop_outside_a_git_worktree(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "plain-dir"
    not_a_repo.mkdir()

    assert apply_gitignore_secret_patterns(not_a_repo) == ()


def test_apply_gitignore_is_noop_when_patterns_already_present(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    _init_repo(repo_path)
    _write_guarded_gitignore(repo_path)

    assert apply_gitignore_secret_patterns(repo_path) == ()


class TestSmallFileSecretSmokeEdgeCases:
    def test_risky_named_files_are_skipped_by_smoke(self, tmp_path: Path) -> None:
        # Risky-named files are handled by the tracked-name check, so the smoke
        # scan skips them even when they hold secret-shaped content.
        secret_value = "abcdefgh" + "ijklmnop" + "1234"
        (tmp_path / ".env").write_text(f"token = {secret_value}\n")

        assert small_file_secret_smoke(tmp_path, (".env",)) == ()

    def test_missing_tracked_file_is_skipped(self, tmp_path: Path) -> None:
        assert small_file_secret_smoke(tmp_path, ("not-on-disk.txt",)) == ()

    def test_binary_content_is_skipped(self, tmp_path: Path) -> None:
        secret_value = "abcdefgh" + "ijklmnop" + "1234"
        (tmp_path / "blob.txt").write_bytes(b"\x00token = " + secret_value.encode() + b"\n")

        assert small_file_secret_smoke(tmp_path, ("blob.txt",)) == ()


class TestPostureHelpers:
    def test_tracked_files_returns_empty_outside_git(self, tmp_path: Path) -> None:
        not_a_repo = tmp_path / "plain-dir"
        not_a_repo.mkdir()

        assert _tracked_files(not_a_repo) == ()

    def test_gitignore_patterns_empty_when_file_missing(self, tmp_path: Path) -> None:
        assert _gitignore_patterns(tmp_path / "no-such-gitignore") == set()

    def test_is_risky_secret_path_classification(self) -> None:
        assert _is_risky_secret_path(".env.example") is False
        assert _is_risky_secret_path(".env.sample") is False
        assert _is_risky_secret_path("secrets/server.key") is True
        assert _is_risky_secret_path("tls/cert.pem") is True
        assert _is_risky_secret_path(".ssh/id_rsa") is True
        assert _is_risky_secret_path("creds/credentials.json") is True
        assert _is_risky_secret_path("src/main.py") is False

    def test_should_scan_file_decisions(self, tmp_path: Path) -> None:
        text_file = tmp_path / "notes.txt"
        text_file.write_text("hello\n")
        assert _should_scan_file(text_file) is True

        binary_file = tmp_path / "image.png"
        binary_file.write_bytes(b"\x89PNG\r\n")
        assert _should_scan_file(binary_file) is False

        # A path that stats cleanly but is not a regular file (a directory) is
        # rejected before the suffix check.
        directory = tmp_path / "subdir"
        directory.mkdir()
        assert _should_scan_file(directory) is False

        assert _should_scan_file(tmp_path / "missing.txt") is False

    def test_should_scan_file_rejects_oversized_files(self, tmp_path: Path) -> None:
        big = tmp_path / "big.txt"
        big.write_bytes(b"x" * (64 * 1024 + 1))
        assert _should_scan_file(big) is False
