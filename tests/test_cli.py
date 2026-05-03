"""Tests for jurati.cli."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from jurati.cli import main

VALID_ENTRY = """\
---
schema_version: 1
id: test-decision
title: Test decision
type: decision
level: L2
status: active
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
expires_at: null
projects: []
tags: []
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: "https://github.com/org/repo/pull/1"
---

Test body.
"""

INVALID_ENTRY = """\
---
schema_version: 1
id: bad-entry
title: Bad entry
type: decision
level: L2
status: active
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
expires_at: null
projects: []
tags: []
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: true
  pr: null
---

Missing review PR for active L2.
"""


class TestCLI:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "jurati" in result.output.lower()

    def test_serve_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0


class TestValidate:
    def test_valid_entries(self, tmp_path: Path) -> None:
        decisions = tmp_path / "decisions"
        decisions.mkdir()
        (decisions / "test-decision.md").write_text(VALID_ENTRY)

        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(tmp_path)])
        assert result.exit_code == 0
        assert "1 entries valid" in result.output

    def test_invalid_entry_fails(self, tmp_path: Path) -> None:
        decisions = tmp_path / "decisions"
        decisions.mkdir()
        (decisions / "bad-entry.md").write_text(INVALID_ENTRY)

        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(tmp_path)])
        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_duplicate_ids(self, tmp_path: Path) -> None:
        decisions = tmp_path / "decisions"
        decisions.mkdir()
        (decisions / "test-decision.md").write_text(VALID_ENTRY)
        (decisions / "test-decision-copy.md").write_text(
            VALID_ENTRY.replace("test-decision-copy", "test-decision")
        )

        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(tmp_path)])
        assert result.exit_code == 1
        assert "duplicate" in result.output.lower()

    def test_parse_error(self, tmp_path: Path) -> None:
        decisions = tmp_path / "decisions"
        decisions.mkdir()
        (decisions / "broken.md").write_text("{{{{ not valid")

        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(tmp_path)])
        assert result.exit_code == 1
        assert "error" in result.output.lower()

    def test_empty_dir_passes(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(tmp_path)])
        assert result.exit_code == 0
        assert "0 entries valid" in result.output

    def test_missing_expiry_on_active(self, tmp_path: Path) -> None:
        active = tmp_path / "active"
        active.mkdir()
        entry = VALID_ENTRY.replace("type: decision", "type: active")
        entry = entry.replace("level: L2", "level: L0")
        entry = entry.replace("id: test-decision", "id: active-entry")
        entry = entry.replace("status: active", "status: active")
        entry = entry.replace(
            "review:\n  required: true\n  pr:",
            "review:\n  required: false\n  pr:",
        )
        (active / "active-entry.md").write_text(entry)

        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(tmp_path)])
        assert result.exit_code == 1
        assert "expires_at" in result.output


class TestInit:
    def test_creates_scaffold(self, tmp_path: Path) -> None:
        target = tmp_path / "new-repo"
        runner = CliRunner()
        result = runner.invoke(main, ["init", str(target)])
        assert result.exit_code == 0

        assert (target / "principles").is_dir()
        assert (target / "decisions").is_dir()
        assert (target / "workflows").is_dir()
        assert (target / "projects").is_dir()
        assert (target / "active").is_dir()
        assert (target / "archive").is_dir()
        assert (target / ".jurati" / "config.yaml").exists()

    def test_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        runner = CliRunner()
        runner.invoke(main, ["init", str(target)])
        result = runner.invoke(main, ["init", str(target)])
        assert result.exit_code == 0
        assert "already exists" in result.output

    def test_config_content(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        runner = CliRunner()
        runner.invoke(main, ["init", str(target)])

        config = (target / ".jurati" / "config.yaml").read_text()
        assert "schema_version: 1" in config
        assert "main_branch: main" in config
