"""Tests for jurati.cli."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
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

    def test_explain(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["explain"])
        assert result.exit_code == 0
        assert "shared memory" in result.output
        assert "does not" in result.output


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
        (decisions / "test-decision-copy.md").write_text(VALID_ENTRY)

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
        assert (target / "README.md").exists()
        assert (target / "projects" / "first-shared-context.md").exists()
        assert (target / "workflows" / "daily-shared-context-loop.md").exists()

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
        assert "active_refs_enabled: true" in config

    def test_init_examples_validate(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        runner = CliRunner()
        init_result = runner.invoke(main, ["init", str(target)])
        assert init_result.exit_code == 0

        validate_result = runner.invoke(main, ["validate", str(target)])
        assert validate_result.exit_code == 0
        assert "2 entries valid" in validate_result.output

    def test_init_without_examples(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        runner = CliRunner()
        result = runner.invoke(main, ["init", "--no-examples", str(target)])
        assert result.exit_code == 0
        assert not (target / "README.md").exists()
        assert not (target / "projects" / "first-shared-context.md").exists()

    def test_init_training_pack_validates(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        runner = CliRunner()
        result = runner.invoke(main, ["init", "--pack", "training", str(target)])
        assert result.exit_code == 0
        assert (target / "workflows" / "course-development-daily-loop.md").exists()
        assert (target / "decisions" / "validate-labs-before-review.md").exists()

        validate_result = runner.invoke(main, ["validate", str(target)])
        assert validate_result.exit_code == 0
        assert "5 entries valid" in validate_result.output

    def test_init_engineering_pack_validates(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        runner = CliRunner()
        result = runner.invoke(main, ["init", "--pack", "engineering", str(target)])
        assert result.exit_code == 0
        assert (target / "workflows" / "engineering-change-loop.md").exists()
        assert (target / "decisions" / "capture-architecture-decisions.md").exists()

        validate_result = runner.invoke(main, ["validate", str(target)])
        assert validate_result.exit_code == 0
        assert "5 entries valid" in validate_result.output


class TestAdoptionHelpers:
    def test_quickstart_creates_valid_starter_repo(self, tmp_path: Path) -> None:
        target = tmp_path / "jurati-knowledge"
        runner = CliRunner()
        result = runner.invoke(main, ["quickstart", str(target)])

        assert result.exit_code == 0
        assert "Jurati quickstart" in result.output
        assert "Validated knowledge repo: 2 entries valid" in result.output
        assert "What Jurati will do:" in result.output
        assert "jurati mcp-config --remote <git-url>" in result.output
        assert (target / ".jurati" / "config.yaml").exists()
        assert (target / "projects" / "first-shared-context.md").exists()

        validate_result = runner.invoke(main, ["validate", str(target)])
        assert validate_result.exit_code == 0
        assert "2 entries valid" in validate_result.output

    def test_quickstart_with_remote_prints_mcp_config(self, tmp_path: Path) -> None:
        target = tmp_path / "jurati-knowledge"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "quickstart",
                "--remote",
                "git@github.com:org/jurati-knowledge.git",
                "--client-slug",
                "codex",
                str(target),
            ],
        )

        assert result.exit_code == 0
        assert "MCP config:" in result.output
        assert '"JURATI_KNOWLEDGE_REMOTE": "git@github.com:org/jurati-knowledge.git"' in (
            result.output
        )
        assert '"JURATI_CLIENT_SLUG": "codex"' in result.output
        assert "Paste the MCP config above into your client" in result.output

    def test_quickstart_pack_prints_selected_pack(self, tmp_path: Path) -> None:
        target = tmp_path / "jurati-knowledge"
        runner = CliRunner()
        result = runner.invoke(main, ["quickstart", "--pack", "training", str(target)])

        assert result.exit_code == 0
        assert "Starter pack: training" in result.output
        assert "5 entries valid" in result.output

    def test_mcp_config_uses_remote(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "mcp-config",
                "--remote",
                "git@github.com:org/jurati-knowledge.git",
                "--client-slug",
                "codex",
            ],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        server = data["mcpServers"]["jurati"]
        assert server["command"] == "jurati"
        assert server["args"] == ["serve"]
        assert server["env"]["JURATI_KNOWLEDGE_REMOTE"] == (
            "git@github.com:org/jurati-knowledge.git"
        )
        assert server["env"]["JURATI_CLIENT_SLUG"] == "codex"

    def test_doctor_without_remote_explains_fast_path(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"], env={"JURATI_KNOWLEDGE_REMOTE": ""})
        assert result.exit_code == 0
        assert "Ready for `jurati serve`: no" in result.output
        assert "Fast path:" in result.output

    def test_doctor_strict_without_remote_fails(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "--strict"], env={"JURATI_KNOWLEDGE_REMOTE": ""})
        assert result.exit_code == 1
        assert "Jurati is not ready" in result.output

    def test_doctor_finds_url_in_claude_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "## Shared Knowledge\n\nKnowledge repo: git@github.com:acme/jurati-knowledge.git\n"
        )
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["doctor"],
            env={"JURATI_KNOWLEDGE_REMOTE": ""},
        )
        assert "git@github.com:acme/jurati-knowledge.git" in result.output

    def test_doctor_finds_url_in_jurati_remote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote_file = tmp_path / ".jurati-remote"
        remote_file.write_text("git@github.com:acme/jurati-knowledge.git\n")
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["doctor"],
            env={"JURATI_KNOWLEDGE_REMOTE": ""},
        )
        assert result.exit_code == 0

    def test_serve_check_missing_remote_fails(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--check"], env={"JURATI_KNOWLEDGE_REMOTE": ""})
        assert result.exit_code == 1
        assert "JURATI_KNOWLEDGE_REMOTE is required" in result.output

    def test_serve_check_explains_runtime_plan(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["serve", "--check"],
            env={"JURATI_KNOWLEDGE_REMOTE": "https://example.com/repo.git"},
        )
        assert result.exit_code == 0
        assert "Jurati serve preflight" in result.output
        assert "clone or reuse the local cache" in result.output
        assert "Privacy boundary" in result.output

    def test_wrapper_does_not_reference_old_local_checkout(self) -> None:
        wrapper = Path("bin/jurati-mcp.sh").read_text()
        assert "/home/eparenti/jurati" not in wrapper
        assert "JURATI_KNOWLEDGE_REMOTE is required" in wrapper


class TestInstallHook:
    def test_install_hook_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["install-hook", "--help"])
        assert result.exit_code == 0
        assert "post-commit" in result.output.lower() or "hook" in result.output.lower()


class TestCaptureCommand:
    def test_capture_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["capture", "--help"])
        assert result.exit_code == 0

    def test_capture_non_jurati_message(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["capture", "--message", "feat: normal commit"])
        assert "no jurati" in result.output.lower() or result.exit_code == 0


class TestActiveCommand:
    def test_active_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["active", "--help"])
        assert result.exit_code == 0


class TestFlushCommand:
    def test_flush_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["flush", "--help"])
        assert result.exit_code == 0


class TestSearchCommand:
    def test_search_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["search", "--help"])
        assert result.exit_code == 0
