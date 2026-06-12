# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Tests for ambara.cli."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import tomllib
from datetime import datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import click
import frontmatter
import git
import pytest
from click.testing import CliRunner

from ambara import __version__
from ambara import __version__ as ambara_version
from ambara.cli import main
from ambara.cli import main as ambara_main
from ambara.core.context_accounting import (
    AccountingInputs,
    append_ledger_event,
    default_ledger_path,
    ledger_event,
)

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


def _write_context_bundle(
    tmp_path: Path, manifest: dict[str, object], files: dict[str, str]
) -> Path:
    bundle = tmp_path / "context-pack.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        _add_bundle_text(tar, "manifest.json", json.dumps(manifest))
        for path, content in files.items():
            _add_bundle_text(tar, path, content)
    return bundle


def _add_bundle_text(tar: tarfile.TarFile, path: str, content: str) -> None:
    data = content.encode("utf-8")
    info = tarfile.TarInfo(path)
    info.size = len(data)
    tar.addfile(info, BytesIO(data))


def _init_git_repo(path: Path) -> git.Repo:
    repo = git.Repo.init(path)
    with repo.config_writer() as writer:
        writer.set_value("user", "name", "Ambara Test")
        writer.set_value("user", "email", "ambara-test@example.com")
    readme = path / "README.md"
    readme.write_text("# knowledge repo\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")
    return repo


def _build_local_remote(tmp_path: Path) -> git.Repo:
    bare = git.Repo.init(tmp_path / "remote.git", bare=True)
    seed = git.Repo.init(tmp_path / "seed")
    with seed.config_writer() as writer:
        writer.set_value("user", "name", "Ambara Test")
        writer.set_value("user", "email", "ambara-test@example.com")
    seed.create_remote("origin", str(bare.common_dir))
    decision = Path(seed.working_dir) / "decisions" / "test-decision.md"
    decision.parent.mkdir(parents=True)
    decision.write_text(VALID_ENTRY)
    seed.index.add(["decisions/test-decision.md"])
    seed.index.commit("add decision")
    seed.remotes.origin.push("HEAD:refs/heads/main")
    return bare


class TestCLI:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "ambara" in result.output.lower()

    def test_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_ambara_version_surface(self) -> None:
        runner = CliRunner()
        result = runner.invoke(ambara_main, ["--version"], prog_name="ambara")
        assert result.exit_code == 0
        assert ambara_version in result.output
        assert "ambara" in result.output.lower()

    def test_package_version_matches_pyproject(self) -> None:
        pyproject = tomllib.loads(Path("pyproject.toml").read_text())
        assert __version__ == pyproject["project"]["version"]

    def test_ambara_console_script_is_declared(self) -> None:
        pyproject = tomllib.loads(Path("pyproject.toml").read_text())
        assert pyproject["project"]["scripts"]["ambara"] == "ambara.cli:main"

    def test_ambara_posture_check_ready(self, tmp_path: Path) -> None:
        repo = git.Repo.init(tmp_path)
        (tmp_path / ".gitignore").write_text("*.key\n*.pem\n.env\n.env.*\n!.env.example\n")
        (tmp_path / "README.md").write_text("normal project notes\n")
        repo.index.add([".gitignore", "README.md"])

        runner = CliRunner()
        result = runner.invoke(
            ambara_main,
            ["posture-check", "--repo-path", str(tmp_path)],
            prog_name="ambara",
        )

        assert result.exit_code == 0
        assert "Ambara agent-safe-start guardrails: ready" in result.output
        assert "0 Ambara tokens" in result.output

    def test_legacy_posture_check_alias_ready(self, tmp_path: Path) -> None:
        repo = git.Repo.init(tmp_path)
        (tmp_path / ".gitignore").write_text("*.key\n*.pem\n.env\n.env.*\n!.env.example\n")
        (tmp_path / "README.md").write_text("normal project notes\n")
        repo.index.add([".gitignore", "README.md"])

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["posture-check", "--repo-path", str(tmp_path)],
            prog_name="ambara",
        )

        assert result.exit_code == 0
        assert "Ambara agent-safe-start guardrails: ready" in result.output

    def test_ambara_posture_check_json_reports_gaps(self, tmp_path: Path) -> None:
        git.Repo.init(tmp_path)
        (tmp_path / ".gitignore").write_text("*.key\n")

        runner = CliRunner()
        result = runner.invoke(
            ambara_main,
            ["posture-check", "--repo-path", str(tmp_path), "--json"],
            prog_name="ambara",
        )

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["agent_start_guardrails_ready"] is False
        assert payload["token_cost"] == "0 Ambara tokens"
        assert payload["findings"][0]["id"] == "gitignore.missing-secret-patterns"

    def test_ambara_posture_check_fix_appends_gitignore_patterns(self, tmp_path: Path) -> None:
        git.Repo.init(tmp_path)
        (tmp_path / ".gitignore").write_text("*.key\n")

        runner = CliRunner()
        result = runner.invoke(
            ambara_main,
            ["posture-check", "--repo-path", str(tmp_path), "--fix"],
            prog_name="ambara",
        )

        assert result.exit_code == 0
        assert "Applied auto-fix" in result.output
        assert "Ambara agent-safe-start guardrails: ready" in result.output
        gitignore = (tmp_path / ".gitignore").read_text()
        assert "*.pem" in gitignore
        assert ".env" in gitignore
        assert ".env.*" in gitignore

    def test_serve_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0

    def test_explain(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["explain"])
        assert result.exit_code == 0
        assert "shared, reviewable context" in result.output
        assert "not Markdown treated as a database" in result.output
        assert "does not" in result.output

    def test_privacy_salt(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["privacy-salt", "--bytes", "16"])
        assert result.exit_code == 0
        assert result.output.startswith("base64:")

    def test_value_json_empty_ledger(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main, ["value", "--json", "--ledger", str(tmp_path / "missing.jsonl")]
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["last_7_days"]["event_count"] == 0
        assert payload["last_30_days"]["app_payload_only"] is True

    def test_value_human_summary(self, tmp_path: Path) -> None:
        ledger = tmp_path / "value-ledger.jsonl"
        append_ledger_event(
            ledger,
            ledger_event(
                AccountingInputs(
                    tool_name="context",
                    context_schema="compiler-v1",
                    response_payload={"ok": True},
                    full_context_tokens_est=1000,
                    entries_omitted_count=3,
                )
            ),
        )

        runner = CliRunner()
        result = runner.invoke(main, ["value", "--ledger", str(ledger)])

        assert result.exit_code == 0
        assert "Ambara value" in result.output
        assert "last 7 days: 1 events" in result.output
        assert "app-payload only" in result.output

    def test_value_human_summary_uses_managed_price(self, tmp_path: Path) -> None:
        ledger = tmp_path / "value-ledger.jsonl"
        append_ledger_event(
            ledger,
            ledger_event(
                AccountingInputs(
                    tool_name="context",
                    context_schema="compiler-v1",
                    response_payload={"ok": True},
                    full_context_tokens_est=2_000_000,
                )
            ),
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["value", "--ledger", str(ledger)],
            env={"AMBARA_INPUT_PRICE_PER_MILLION": "2.0", "AMBARA_PRICE_CURRENCY": "usd"},
        )

        assert result.exit_code == 0
        assert "(~$4.00 saved)" in result.output

    def test_value_rejects_invalid_managed_price(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["value", "--ledger", str(tmp_path / "value-ledger.jsonl")],
            env={"AMBARA_INPUT_PRICE_PER_MILLION": "-1"},
        )

        assert result.exit_code == 1
        assert "AMBARA_INPUT_PRICE_PER_MILLION" in result.output

    def test_value_explain(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["value", "--explain", "--ledger", str(tmp_path / "v.jsonl")])

        assert result.exit_code == 0
        assert "naive_full_eligible_context" in result.output
        assert "no query text" in result.output

    def test_feedback_records_local_project_config(self, tmp_path: Path) -> None:
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["feedback", "entry-1", "not-useful", "--repo-path", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert "Recorded local Ambara feedback" in result.output
        config = (tmp_path / ".ambara" / "config.yaml").read_text()
        assert "entry_feedback:" in config
        assert "entry-1: not_useful" in config

    def test_feedback_useful_clears_local_project_config(self, tmp_path: Path) -> None:
        runner = CliRunner()
        first = runner.invoke(
            main,
            ["feedback", "entry-1", "stale", "--repo-path", str(tmp_path)],
        )
        second = runner.invoke(
            main,
            ["feedback", "entry-1", "useful", "--repo-path", str(tmp_path)],
        )

        assert first.exit_code == 0
        assert second.exit_code == 0
        config = (tmp_path / ".ambara" / "config.yaml").read_text()
        assert "entry_feedback:" not in config


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

    def test_unresolved_wiki_link_fails_validation(self, tmp_path: Path) -> None:
        decisions = tmp_path / "decisions"
        decisions.mkdir()
        entry = VALID_ENTRY.replace("Test body.", "See [[missing-decision]].")
        (decisions / "test-decision.md").write_text(entry)

        runner = CliRunner()
        result = runner.invoke(main, ["validate", str(tmp_path)])

        assert result.exit_code == 1
        assert "unresolved wiki link" in result.output


class TestImportContext:
    def test_dry_run_prints_create_plan(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        bundle = _write_context_bundle(
            tmp_path,
            {
                "name": "Team Pack",
                "items": [
                    {
                        "path": "Repos/api.md",
                        "category": "repo profile",
                        "id": "api-service",
                        "title": "API Service",
                    }
                ],
            },
            {"Repos/api.md": "API context."},
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["import-context", "--dry-run", "--repo", str(repo), str(bundle)],
        )

        assert result.exit_code == 0
        assert "Context import dry run" in result.output
        assert "Summary: 1 create, 0 skip, 0 reject" in result.output
        assert "Repos/api.md -> projects/api-service.md" in result.output
        assert "No files written." in result.output

    def test_dry_run_rejects_invalid_items(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        bundle = _write_context_bundle(
            tmp_path,
            {
                "name": "Team Pack",
                "items": [
                    {
                        "path": "Notes/unknown.md",
                        "category": "misc",
                        "id": "unknown-note",
                        "title": "Unknown",
                    }
                ],
            },
            {"Notes/unknown.md": "Unknown context."},
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["import-context", "--dry-run", "--repo", str(repo), str(bundle)],
        )

        assert result.exit_code == 1
        assert "Summary: 0 create, 0 skip, 1 reject" in result.output
        assert "unknown category" in result.output

    def test_write_mode_creates_review_branch(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        git_repo = _init_git_repo(repo)
        bundle = _write_context_bundle(
            tmp_path,
            {
                "name": "Team Pack",
                "items": [
                    {
                        "path": "Repos/api.md",
                        "category": "repo profile",
                        "id": "api-service",
                        "title": "API Service",
                    }
                ],
            },
            {"Repos/api.md": "API context."},
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "import-context",
                "--repo",
                str(repo),
                "--branch",
                "ambara/import-context-test",
                str(bundle),
            ],
        )

        assert result.exit_code == 0
        assert "Wrote import review branch" in result.output
        assert git_repo.active_branch.name == "ambara/import-context-test"
        assert (repo / "projects" / "api-service.md").exists()

    def test_import_docs_dry_run_prints_create_plan(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        source = tmp_path / "source-docs" / "adr"
        source.mkdir(parents=True)
        (source / "0001-use-sqlite.md").write_text(
            "# Use SQLite\n\nUse SQLite for the local read model.\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "import-docs",
                "--dry-run",
                "--repo",
                str(repo),
                "--mode",
                "adr",
                "--project",
                "read-model",
                str(source),
            ],
        )

        assert result.exit_code == 0
        assert "Context import dry run" in result.output
        assert "Markdown import: adr markdown" in result.output
        assert "Summary: 1 create, 0 skip, 0 reject" in result.output
        assert "adr/0001-use-sqlite.md -> decisions/use-sqlite.md" in result.output
        assert "No files written." in result.output

    def test_import_docs_write_mode_creates_review_branch(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        git_repo = _init_git_repo(repo)
        source = tmp_path / "docs"
        source.mkdir()
        (source / "architecture.md").write_text(
            "# Architecture\n\nCurrent project architecture.\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "import-docs",
                "--repo",
                str(repo),
                "--branch",
                "ambara/import-docs-test",
                "--mode",
                "docs",
                str(source),
            ],
        )

        assert result.exit_code == 0
        assert "Wrote import review branch" in result.output
        assert git_repo.active_branch.name == "ambara/import-docs-test"
        assert (repo / "projects" / "architecture.md").exists()
        assert "import docs markdown" in git_repo.head.commit.message

    def test_import_docs_obsidian_dry_run_prints_review_plan(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        vault = tmp_path / "vault"
        (vault / "Decisions").mkdir(parents=True)
        (vault / "Decisions" / "token-rotation.md").write_text(
            "# Token Rotation\n\nUse server-driven rotation.\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "import-docs",
                "--dry-run",
                "--repo",
                str(repo),
                "--mode",
                "obsidian",
                "--project",
                "auth",
                str(vault),
            ],
        )

        assert result.exit_code == 0
        assert "Obsidian import: obsidian vault" in result.output
        assert "Summary: 1 create, 0 skip, 0 reject" in result.output
        assert "vault/Decisions/token-rotation.md -> decisions/token-rotation.md" in result.output
        assert "No files written." in result.output


class TestHtml:
    def test_html_generates_static_site(self, tmp_path: Path) -> None:
        decisions = tmp_path / "decisions"
        decisions.mkdir()
        (decisions / "test-decision.md").write_text(VALID_ENTRY)

        runner = CliRunner()
        result = runner.invoke(main, ["html", str(tmp_path)])

        assert result.exit_code == 0
        assert "Generated 2 page(s)" in result.output
        assert (tmp_path / "_site" / "index.html").exists()
        assert (tmp_path / "_site" / "entries" / "test-decision.html").exists()


class TestReadModel:
    def test_read_model_rebuild_and_query(self, tmp_path: Path) -> None:
        decisions = tmp_path / "decisions"
        decisions.mkdir()
        entry = VALID_ENTRY.replace("Test body.", "API validation context.")
        (decisions / "test-decision.md").write_text(entry)

        runner = CliRunner()
        rebuild = runner.invoke(main, ["read-model", "rebuild", str(tmp_path)])

        assert rebuild.exit_code == 0
        assert "Indexed entries: 1" in rebuild.output
        assert (tmp_path / ".ambara" / "read-model.sqlite3").exists()

        query = runner.invoke(
            main,
            ["read-model", "query", "API validation", "--repo", str(tmp_path)],
        )

        assert query.exit_code == 0
        assert "test-decision" in query.output

    def test_read_model_query_missing_database_is_clear(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["read-model", "query", "API validation", "--repo", str(tmp_path)],
        )

        assert result.exit_code != 0
        assert "Read model not found" in result.output


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
        assert (target / ".ambara" / "config.yaml").exists()
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

        config = (target / ".ambara" / "config.yaml").read_text()
        assert "schema_version: 1" in config
        assert "main_branch: main" in config
        assert "active_refs_enabled: true" in config

    def test_init_examples_use_fresh_timestamps(self, tmp_path: Path) -> None:
        target = tmp_path / "repo"
        runner = CliRunner()
        result = runner.invoke(main, ["init", str(target)])
        assert result.exit_code == 0

        content = (target / "projects" / "first-shared-context.md").read_text()
        assert "2026-05-03T00:00:00Z" not in content
        created_line = next(
            line for line in content.splitlines() if line.startswith("created_at: ")
        )
        updated_line = next(
            line for line in content.splitlines() if line.startswith("updated_at: ")
        )
        assert created_line.replace("created_at: ", "") == updated_line.replace("updated_at: ", "")
        created_at = datetime.fromisoformat(
            created_line.removeprefix("created_at: ").replace("Z", "+00:00")
        )
        assert created_at.tzinfo is not None

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
        target = tmp_path / "ambara-knowledge"
        runner = CliRunner()
        result = runner.invoke(main, ["quickstart", str(target)])

        assert result.exit_code == 0
        assert "Ambara quickstart" in result.output
        assert "Validated knowledge repo: 2 entries valid" in result.output
        assert "What Ambara will do:" in result.output
        assert "ambara mcp-config --remote <git-url>" in result.output
        assert "GitHub and GitLab are first-class review backends." in result.output
        assert (target / ".ambara" / "config.yaml").exists()
        assert (target / "projects" / "first-shared-context.md").exists()

        validate_result = runner.invoke(main, ["validate", str(target)])
        assert validate_result.exit_code == 0
        assert "2 entries valid" in validate_result.output

    def test_quickstart_with_remote_prints_mcp_config(self, tmp_path: Path) -> None:
        target = tmp_path / "ambara-knowledge"
        remote = "git@github.com:org/ambara-knowledge.git"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "quickstart",
                "--remote",
                remote,
                "--client-slug",
                "codex",
                str(target),
            ],
        )

        assert result.exit_code == 0
        assert "MCP config:" in result.output
        assert '"AMBARA_KNOWLEDGE_REMOTE": "git@github.com:org/ambara-knowledge.git"' in (
            result.output
        )
        assert '"AMBARA_CLIENT_SLUG": "codex"' in result.output
        assert "Paste the MCP config above into your client" in result.output
        assert "GitHub and GitLab are first-class review backends." in result.output
        data = json.loads((target / ".claude" / "settings.json").read_text())
        from ambara.cli.install import _mcp_server_name

        server_name = _mcp_server_name(remote)
        assert f"mcp__{server_name}__context" in data["permissions"]["allow"]
        assert f"mcp__{server_name}__sync" in data["permissions"]["allow"]

    def test_quickstart_pack_prints_selected_pack(self, tmp_path: Path) -> None:
        target = tmp_path / "ambara-knowledge"
        runner = CliRunner()
        result = runner.invoke(main, ["quickstart", "--pack", "training", str(target)])

        assert result.exit_code == 0
        assert "Starter pack: training" in result.output
        assert "5 entries valid" in result.output

    def test_demo_creates_runnable_local_proof(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        demo_root = tmp_path / "ambara-demo"
        runner = CliRunner()

        result = runner.invoke(main, ["demo", "--path", str(demo_root)])

        assert result.exit_code == 0, result.output
        assert "Ambara demo created" in result.output
        assert "source fixture:" in result.output
        assert "signal fixture:" not in result.output
        assert "Proof commands:" in result.output
        assert (demo_root / "knowledge" / ".git").exists()
        assert (demo_root / "project" / ".git").exists()
        assert (demo_root / "signals.json").exists()
        assert (demo_root / "project" / ".ambara" / "config.yaml").exists()
        assert (demo_root / "project" / ".mcp.json").exists()
        assert (demo_root / "run-proof.sh").exists()
        proof_text = (demo_root / "run-proof.sh").read_text()
        assert 'export GIT_CONFIG_GLOBAL="$ROOT/gitconfig"' in proof_text
        assert "hooksPath = $ROOT/no-git-hooks" in proof_text
        for repo_name in ("knowledge", "project"):
            hooks_path = demo_root / repo_name / ".git" / "ambara-disabled-hooks"
            assert hooks_path.is_dir()
            config = subprocess.run(
                ["git", "-C", str(demo_root / repo_name), "config", "--get", "core.hooksPath"],
                check=True,
                capture_output=True,
                text=True,
            )
            assert config.stdout.strip() == str(hooks_path)
        signal_fixture = json.loads((demo_root / "signals.json").read_text())
        assert any(item.get("provider") == "gitlab" for item in signal_fixture["signals"])
        assert any(
            item.get("url") == "https://gitlab.com/org/api/-/merge_requests/77"
            for item in signal_fixture["signals"]
        )

        validate = runner.invoke(main, ["validate", str(demo_root / "knowledge")])
        assert validate.exit_code == 0, validate.output
        assert "6 entries valid" in validate.output

        mcp = json.loads((demo_root / "project" / ".mcp.json").read_text())
        server = next(iter(mcp["mcpServers"].values()))
        assert server["env"]["AMBARA_KNOWLEDGE_REMOTE"] == str((demo_root / "knowledge").resolve())
        assert server["env"]["AMBARA_SOURCE_REPOS"] == "org/api"
        assert server["env"]["AMBARA_SOURCE_FIXTURE"] == str((demo_root / "signals.json").resolve())
        assert "AMBARA_PR_SIGNAL_FIXTURE" not in server["env"]

        monkeypatch.chdir(demo_root / "project")
        startup = runner.invoke(
            main,
            ["startup", "--goal", "continue the API handoff"],
            env={
                "AMBARA_KNOWLEDGE_REMOTE": "",
                "AMBARA_CACHE_DIR": str(demo_root / "cache"),
                "AMBARA_VALUE_LEDGER_PATH": str(demo_root / "value-ledger.jsonl"),
                "AMBARA_SOURCE_REPOS": "org/api",
                "AMBARA_SOURCE_FIXTURE": str(demo_root / "signals.json"),
            },
        )
        assert startup.exit_code == 0, startup.output
        packet = json.loads(startup.output)
        assert packet["v"] == "s2"
        assert "body" not in json.dumps(packet)
        assert "demo-restricted-token-policy" not in json.dumps(packet)
        assert (demo_root / "value-ledger.jsonl").exists()

        wrapper_dir = tmp_path / "bin"
        wrapper_dir.mkdir()
        wrapper = wrapper_dir / "ambara"
        wrapper.write_text(
            f"#!/bin/sh\nexec {sys.executable} -c 'from ambara.cli import main; main()' \"$@\"\n"
        )
        wrapper.chmod(0o755)
        repo_src = Path(__file__).resolve().parents[1] / "src"
        hostile_template = tmp_path / "hostile-git-template"
        hostile_hooks = hostile_template / "hooks"
        hostile_hooks.mkdir(parents=True)
        hostile_pre_commit = hostile_hooks / "pre-commit"
        hostile_pre_commit.write_text("#!/bin/sh\necho hostile git hook ran >&2\nexit 1\n")
        hostile_pre_commit.chmod(0o755)
        hostile_gitconfig = tmp_path / "hostile-gitconfig"
        hostile_gitconfig.write_text(
            f"[init]\n  templateDir = {hostile_template}\n[core]\n  hooksPath = {hostile_hooks}\n"
        )

        env = os.environ.copy()
        env["PATH"] = f"{wrapper_dir}{os.pathsep}{env.get('PATH', '')}"
        env["PYTHONPATH"] = f"{repo_src}{os.pathsep}{env.get('PYTHONPATH', '')}"
        env["GIT_CONFIG_GLOBAL"] = str(hostile_gitconfig)
        env["GIT_CONFIG_SYSTEM"] = os.devnull
        proof = subprocess.run(
            [str(demo_root / "run-proof.sh")],
            cwd=demo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proof.returncode == 0, proof.stdout + proof.stderr
        assert "Ambara release proof passed." in proof.stdout
        assert (demo_root / "startup.json").exists()
        assert (demo_root / "posture.json").exists()

        read = runner.invoke(
            main,
            ["read", "demo-api-handoff"],
            env={
                "AMBARA_KNOWLEDGE_REMOTE": "",
                "AMBARA_CACHE_DIR": str(demo_root / "cache"),
            },
        )
        assert read.exit_code == 0, read.output
        assert "Continue the API handoff" in read.output

        html = runner.invoke(
            main,
            [
                "html",
                str(demo_root / "knowledge"),
                "--output",
                str(demo_root / "site"),
            ],
        )
        assert html.exit_code == 0, html.output
        assert "Skipped 1 restricted entries" in html.output
        index_html = (demo_root / "site" / "index.html").read_text()
        assert "demo-restricted-token-policy" not in index_html

    def test_onboard_prompts_and_wires_project(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "ambara-knowledge"
        project = tmp_path / "project"
        project.mkdir()
        remote = "git@github.com:org/ambara-knowledge.git"
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["onboard"],
            input=f"{remote}\n{knowledge}\n{project}\nengineering\n",
        )

        assert result.exit_code == 0
        assert "Ambara onboarding" in result.output
        assert "Knowledge repo remote URL" in result.output
        assert "Onboarding complete." in result.output
        assert "git push -u origin main" in result.output
        assert "ambara doctor --check-startup" in result.output
        assert "GitHub and GitLab are first-class review backends." in result.output
        assert (knowledge / ".ambara" / "config.yaml").exists()
        assert (knowledge / "workflows" / "engineering-change-loop.md").exists()
        assert (project / "CLAUDE.md").exists()
        assert (project / ".ambara" / "config.yaml").exists()
        assert (project / ".claude" / "settings.json").exists()
        assert (project / ".mcp.json").exists()

        project_config = (project / ".ambara" / "config.yaml").read_text()
        assert f"knowledge_remote: {remote}" in project_config
        assert "active_refs_enabled: true" in project_config
        assert "client_slug" not in project_config

        mcp = json.loads((project / ".mcp.json").read_text())
        server = next(iter(mcp["mcpServers"].values()))
        assert server["env"]["AMBARA_KNOWLEDGE_REMOTE"] == remote
        assert server["env"]["AMBARA_CLIENT_SLUG"] == "claude-code"

    def test_onboard_flags_skip_optional_prompts(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "ambara-knowledge"
        project = tmp_path / "project"
        project.mkdir()
        remote = "git@github.com:org/ambara-knowledge.git"
        runner = CliRunner()

        result = runner.invoke(
            main,
            [
                "onboard",
                "--yes",
                "--remote",
                remote,
                "--knowledge-repo",
                str(knowledge),
                "--project-repo",
                str(project),
                "--pack",
                "training",
                "--client-slug",
                "codex",
            ],
        )

        assert result.exit_code == 0
        assert "Knowledge repo path" not in result.output
        assert "Starter pack: training" in result.output
        assert (knowledge / "projects" / "course-refresh-status.md").exists()

        mcp = json.loads((project / ".mcp.json").read_text())
        server = next(iter(mcp["mcpServers"].values()))
        assert server["env"]["AMBARA_CLIENT_SLUG"] == "codex"

    def test_onboard_dry_run_prints_plan_without_writing(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "ambara-knowledge"
        project = tmp_path / "project"
        project.mkdir()
        remote = "git@github.com:org/ambara-knowledge.git"
        runner = CliRunner()

        result = runner.invoke(
            main,
            [
                "onboard",
                "--dry-run",
                "--yes",
                "--remote",
                remote,
                "--knowledge-repo",
                str(knowledge),
                "--project-repo",
                str(project),
                "--client",
                "gemini",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Ambara onboarding (dry run)" in result.output
        assert "GEMINI.md" in result.output
        assert "No files were written." in result.output
        assert not knowledge.exists()
        assert not (project / "GEMINI.md").exists()

    def test_onboard_can_generate_cursor_project_files(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "ambara-knowledge"
        project = tmp_path / "project"
        project.mkdir()
        remote = "git@github.com:org/ambara-knowledge.git"
        runner = CliRunner()

        result = runner.invoke(
            main,
            [
                "onboard",
                "--yes",
                "--remote",
                remote,
                "--knowledge-repo",
                str(knowledge),
                "--project-repo",
                str(project),
                "--client",
                "cursor",
            ],
        )

        assert result.exit_code == 0, result.output
        cursor_rules = project / ".cursor" / "rules" / "ambara.mdc"
        cursor_mcp = project / ".cursor" / "mcp.json"
        assert cursor_rules.exists()
        assert cursor_mcp.exists()
        assert "alwaysApply: true" in cursor_rules.read_text()
        mcp = json.loads(cursor_mcp.read_text())
        server = next(iter(mcp["mcpServers"].values()))
        assert server["command"] == "ambara"
        assert server["env"]["AMBARA_KNOWLEDGE_REMOTE"] == remote
        assert not (project / ".claude" / "settings.json").exists()

    def test_mcp_config_uses_remote(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "mcp-config",
                "--remote",
                "git@github.com:org/ambara-knowledge.git",
                "--client-slug",
                "codex",
            ],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        server_names = list(data["mcpServers"].keys())
        assert len(server_names) == 1
        assert server_names[0].startswith("ambara-")
        server = data["mcpServers"][server_names[0]]
        assert server["command"] == "ambara"
        assert server["args"] == ["serve"]
        assert server["env"]["AMBARA_KNOWLEDGE_REMOTE"] == (
            "git@github.com:org/ambara-knowledge.git"
        )
        assert server["env"]["AMBARA_CLIENT_SLUG"] == "codex"

    def test_mcp_config_carries_non_secret_source_env(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "mcp-config",
                "--remote",
                "git@github.com:org/ambara-knowledge.git",
            ],
            env={
                "AMBARA_SOURCE_PROVIDER": "fixture",
                "AMBARA_SOURCE_REPOS": "org/api",
                "AMBARA_SOURCE_FIXTURE": "/tmp/source-fixture.json",
            },
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        server = next(iter(data["mcpServers"].values()))
        assert server["env"]["AMBARA_SOURCE_PROVIDER"] == "fixture"
        assert server["env"]["AMBARA_SOURCE_REPOS"] == "org/api"
        assert server["env"]["AMBARA_SOURCE_FIXTURE"] == "/tmp/source-fixture.json"

    def test_mcp_config_preserves_non_secret_legacy_signal_env(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "mcp-config",
                "--remote",
                "git@github.com:org/ambara-knowledge.git",
            ],
            env={
                "AMBARA_SOURCE_REPOS": "org/api",
                "AMBARA_SOURCE_FIXTURE": "/tmp/source.json",
            },
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        server = next(iter(data["mcpServers"].values()))
        assert server["env"]["AMBARA_SOURCE_REPOS"] == "org/api"
        assert server["env"]["AMBARA_SOURCE_FIXTURE"] == "/tmp/source.json"

    def test_mcp_config_write_project_carries_repo_active_refs_policy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:org/ambara-knowledge.git"
        config = tmp_path / ".ambara" / "config.yaml"
        config.parent.mkdir()
        config.write_text(
            "schema_version: 1\n"
            f"knowledge_remote: {remote}\n"
            "active_refs_enabled: true\n"
            "expiry:\n"
            "  active_ttl_hours: 8\n"
        )
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["mcp-config", "--remote", remote, "--write-project"],
        )

        assert result.exit_code == 0
        data = json.loads((tmp_path / ".mcp.json").read_text())
        server = next(iter(data["mcpServers"].values()))
        assert server["env"]["AMBARA_ACTIVE_REFS_ENABLED"] == "true"
        assert server["env"]["AMBARA_ACTIVE_REF_TTL_HOURS"] == "8"

    def test_mcp_config_write_project_carries_nested_active_refs_policy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:org/ambara-knowledge.git"
        config = tmp_path / ".ambara" / "config.yaml"
        config.parent.mkdir()
        config.write_text(
            "schema_version: 1\n"
            f"knowledge_remote: {remote}\n"
            "active_refs:\n"
            "  enabled: true\n"
            "  ttl_hours: 8\n"
        )
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(main, ["mcp-config", "--write-project"])

        assert result.exit_code == 0
        data = json.loads((tmp_path / ".mcp.json").read_text())
        server = next(iter(data["mcpServers"].values()))
        assert server["env"]["AMBARA_KNOWLEDGE_REMOTE"] == remote
        assert server["env"]["AMBARA_ACTIVE_REFS_ENABLED"] == "true"
        assert server["env"]["AMBARA_ACTIVE_REF_TTL_HOURS"] == "8"
        updated_config = config.read_text()
        assert "active_refs_enabled: true" not in updated_config

    def test_mcp_config_write_project_rejects_invalid_repo_ttl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:org/ambara-knowledge.git"
        config = tmp_path / ".ambara" / "config.yaml"
        config.parent.mkdir()
        config.write_text(
            "schema_version: 1\n"
            f"knowledge_remote: {remote}\n"
            "active_refs_enabled: true\n"
            "expiry:\n"
            "  active_ttl_hours: 169\n"
        )
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(main, ["mcp-config", "--write-project"])

        assert result.exit_code == 1
        assert "active ref TTL must be an integer between 1 and 168 hours" in result.output

        result_with_remote = runner.invoke(
            main,
            ["mcp-config", "--remote", remote, "--write-project"],
        )
        assert result_with_remote.exit_code == 1
        assert (
            "active ref TTL must be an integer between 1 and 168 hours" in result_with_remote.output
        )

    def test_doctor_without_remote_explains_fast_path(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})
        assert result.exit_code == 0
        assert "Ready for `ambara serve`: no" in result.output
        assert "Fast path:" in result.output
        assert "Agent startup:" in result.output

    def test_doctor_strict_without_remote_fails(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "--strict"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})
        assert result.exit_code == 1
        assert "Ambara is not ready" in result.output

    def test_doctor_audit_gate_blocks_compliance_claims(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/kb.git"
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        install = runner.invoke(main, ["install-claude-md", "--remote", remote])

        result = runner.invoke(
            main,
            ["doctor", "--audit"],
            env={"AMBARA_KNOWLEDGE_REMOTE": remote},
        )
        strict = runner.invoke(
            main,
            ["doctor", "--strict", "--audit"],
            env={"AMBARA_KNOWLEDGE_REMOTE": remote},
        )

        assert install.exit_code == 0
        assert result.exit_code == 0
        assert "Audit/compliance claim gate:" in result.output
        assert "reviewable git-backed context: yes" in result.output
        assert "immutable ledger claim:       no" in result.output
        assert "tamper-evident ledger claim:  no" in result.output
        assert "SOC2-ready audit evidence:    no" in result.output
        assert "Ready for `ambara serve`: yes" in result.output
        assert "Ready for audit ledger claims: no" in result.output
        assert "Ambara-created commits are not signed or verified" in result.output
        assert strict.exit_code == 1
        assert "Ambara is not ready" in strict.output

    def test_disable_writes_project_config_and_startup_packet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(main, ["disable"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})
        startup = runner.invoke(main, ["startup"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})

        assert result.exit_code == 0
        assert "Disabled Ambara" in result.output
        assert "enabled: false" in (tmp_path / ".ambara" / "config.yaml").read_text()
        assert startup.exit_code == 0
        packet = json.loads(startup.output)
        assert packet["availability"] == "disabled"
        assert packet["action"] == "proceed_local_only"

    def test_status_payload_refresh_uses_side_effect_free_startup_compiler(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ambara.cli.status import StartupCliResult, _status_payload

        calls: list[dict[str, object]] = []
        ledger = tmp_path / "value-ledger.jsonl"
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/kb.git")
        monkeypatch.setenv("AMBARA_VALUE_LEDGER_PATH", str(ledger))

        def compile_startup(**kwargs: object) -> StartupCliResult:
            calls.append(kwargs)
            return StartupCliResult(
                packet={
                    "v": "s2",
                    "availability": "fresh",
                    "action": "continue",
                    "value": {"packet_tokens_est": 9},
                    "entries": [],
                }
            )

        payload = _status_payload(
            refresh=True,
            repo="org/api",
            goal="ship the setup spine",
            max_entries=2,
            compile_startup=compile_startup,
        )

        assert calls == [
            {
                "repo": "org/api",
                "goal": "ship the setup spine",
                "max_entries": 2,
                "include_muted": False,
                "record_value": False,
            }
        ]
        assert payload["startup_packet"]["status"] == "ok"
        assert payload["startup_packet"]["packet_tokens_est"] == 9
        assert payload["value_ledger"]["path"] == str(ledger)
        assert payload["value_ledger"]["exists"] is False
        assert not ledger.exists()

    def test_status_payload_refresh_maps_startup_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ambara.cli.status import StartupCliResult, _status_payload

        ledger = tmp_path / "value-ledger.jsonl"
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AMBARA_KNOWLEDGE_REMOTE", "https://example.com/kb.git")
        monkeypatch.setenv("AMBARA_VALUE_LEDGER_PATH", str(ledger))

        def compile_startup(**_kwargs: object) -> StartupCliResult:
            raise click.ClickException("synthetic startup failure")

        payload = _status_payload(
            refresh=True,
            repo=None,
            goal="status check",
            max_entries=5,
            compile_startup=compile_startup,
        )

        assert payload["status"] == "needs_attention"
        assert payload["startup_packet"] == {
            "status": "error",
            "error": "synthetic startup failure",
        }
        assert payload["source_inputs"]["reason"] == "startup refresh failed"
        assert payload["value_ledger"]["path"] == str(ledger)
        assert not ledger.exists()

    def test_status_without_remote_points_to_demo_or_onboard(self) -> None:
        runner = CliRunner()

        result = runner.invoke(main, ["status"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})

        assert result.exit_code == 0, result.output
        assert "Ambara status" in result.output
        assert "overall:        needs_setup" in result.output
        assert "knowledge repo: missing" in result.output
        assert "Startup packet:" in result.output
        assert "status:          not checked" in result.output
        assert "Source inputs:" in result.output
        assert "status:          not_configured" in result.output
        assert "Next repair:" in result.output
        assert "ambara demo" in result.output
        assert "ambara onboard --local" in result.output

    def test_status_json_without_remote_does_not_overclaim_ready(self) -> None:
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["status", "--json"],
            env={"AMBARA_KNOWLEDGE_REMOTE": ""},
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "needs_setup"
        assert payload["knowledge_repo"]["remote"] is None
        assert payload["startup_packet"]["status"] == "not_checked"
        assert payload["source_inputs"]["status"] == "not_configured"
        assert "ambara demo" in payload["next_repair"]

    def test_status_refresh_reports_startup_without_writing_value_ledger(
        self, tmp_path: Path
    ) -> None:
        remote = _build_local_remote(tmp_path)
        ledger = tmp_path / "value-ledger.jsonl"
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["status", "--refresh", "--json", "--goal", "test decision"],
            env={
                "AMBARA_KNOWLEDGE_REMOTE": str(remote.common_dir),
                "AMBARA_CACHE_DIR": str(tmp_path / "cache"),
                "AMBARA_VALUE_LEDGER_PATH": str(ledger),
            },
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["startup_packet"]["status"] == "ok"
        assert payload["startup_packet"]["availability"] == "fresh"
        assert payload["startup_packet"]["packet_tokens_est"] > 0
        assert payload["startup_packet"]["entry_count"] >= 0
        assert payload["source_inputs"]["status"] == "not_configured"
        assert payload["value_ledger"]["path"] == str(ledger)
        assert payload["value_ledger"]["exists"] is False
        assert payload["value_ledger"]["event_count"] == 0
        assert not ledger.exists()

    def test_status_refresh_reports_fresh_configured_source(self, tmp_path: Path) -> None:
        remote = _build_local_remote(tmp_path)
        fixture = tmp_path / "signals.json"
        fixture.write_text(
            json.dumps(
                {
                    "signals": [
                        {
                            "provider": "github",
                            "repo": "org/api",
                            "number": 42,
                            "url": "https://github.com/org/api/pull/42",
                            "title": "Auth migration blocks rollout",
                            "body_excerpt": "Wait for the reviewed auth contract.",
                            "author": "alice@example.com",
                            "state": "open",
                            "labels": ["ambara"],
                            "created_at": "2026-06-11T00:00:00Z",
                            "updated_at": "2026-06-11T00:00:00Z",
                            "changed_paths": ["contracts/auth/session.json"],
                        }
                    ]
                }
            )
        )
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["status", "--refresh", "--json"],
            env={
                "AMBARA_KNOWLEDGE_REMOTE": str(remote.common_dir),
                "AMBARA_CACHE_DIR": str(tmp_path / "cache"),
                "AMBARA_SOURCE_REPOS": "org/api",
                "AMBARA_SOURCE_FIXTURE": str(fixture),
            },
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["source_inputs"]["status"] == "configured_fresh"
        assert payload["source_inputs"]["configured"] is True
        assert payload["source_inputs"]["source_count"] == 1
        assert payload["source_inputs"]["artifact_count"] == 1
        assert payload["source_inputs"]["counts"]["fresh"] == 1
        assert payload["source_inputs"]["sources"][0]["provider"] == "fixture"
        assert payload["startup_packet"]["status"] == "ok"

    def test_status_refresh_reports_missing_source_without_leaking_path(
        self, tmp_path: Path
    ) -> None:
        remote = _build_local_remote(tmp_path)
        missing = tmp_path / "missing-source-fixture.json"
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["status", "--refresh", "--json"],
            env={
                "AMBARA_KNOWLEDGE_REMOTE": str(remote.common_dir),
                "AMBARA_CACHE_DIR": str(tmp_path / "cache"),
                "AMBARA_SOURCE_REPOS": "org/api",
                "AMBARA_SOURCE_FIXTURE": str(missing),
            },
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "needs_attention"
        assert payload["startup_packet"]["status"] == "ok"
        assert payload["startup_packet"]["availability"] == "unavailable"
        assert payload["startup_packet"]["action"] == "stop_context_unavailable"
        assert payload["source_inputs"]["status"] == "configured_unavailable"
        assert payload["source_inputs"]["configured"] is True
        assert payload["source_inputs"]["counts"]["unavailable"] == 1
        assert payload["source_inputs"]["omissions"]["source_error"] == 1
        assert str(missing) not in json.dumps(payload)
        assert payload["next_repair"] == "Run `ambara sources doctor` for source input details."

    def test_startup_records_local_value_ledger(self, tmp_path: Path) -> None:
        remote = _build_local_remote(tmp_path)
        ledger = tmp_path / "value-ledger.jsonl"
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["startup", "--goal", "test decision"],
            env={
                "AMBARA_KNOWLEDGE_REMOTE": str(remote.common_dir),
                "AMBARA_CACHE_DIR": str(tmp_path / "cache"),
                "AMBARA_VALUE_LEDGER_PATH": str(ledger),
            },
        )

        assert result.exit_code == 0
        packet = json.loads(result.output)
        assert "value" in packet
        assert ledger.exists()
        event = json.loads(ledger.read_text().splitlines()[0])
        assert event["tool_name"] == "startup"
        assert event["context_schema"] == "startup-s2"
        assert event["selected_entry_count"] == len(packet.get("entries", ()))
        assert "test-decision" not in str(event)
        assert "Test body" not in str(event)

    def test_startup_records_default_local_value_rollup(self, tmp_path: Path) -> None:
        remote = _build_local_remote(tmp_path)
        cache_dir = tmp_path / "cache"
        ledger = default_ledger_path(str(cache_dir))
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["startup", "--goal", "test decision"],
            env={
                "AMBARA_KNOWLEDGE_REMOTE": str(remote.common_dir),
                "AMBARA_CACHE_DIR": str(cache_dir),
            },
        )

        assert result.exit_code == 0
        packet = json.loads(result.output)
        assert ledger.exists()
        assert packet["value_rollup"]["events"] == 1
        assert packet["value_rollup"]["net_savings_tokens_est"] >= 0
        assert "net_savings_cost_est" not in packet["value_rollup"]

    @pytest.mark.parametrize("client", ["claude-code", "codex", "cursor", "gemini"])
    def test_client_smoke_writes_file_adapter_context(self, tmp_path: Path, client: str) -> None:
        remote = _build_local_remote(tmp_path)
        project = tmp_path / f"project-{client}"
        runner = CliRunner()

        result = runner.invoke(
            main,
            [
                "client-smoke",
                "--client",
                client,
                "--remote",
                str(remote.common_dir),
                "--project-path",
                str(project),
                "--goal",
                "test decision",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["client"] == client
        assert payload["adapter"] == "file"
        assert payload["knowledge_entry_count"] >= 1
        assert payload["value_rollup_events"] == 1
        context = project / ".ambara" / "context.md"
        assert context.exists()
        assert "# Team Context" in context.read_text()
        if client == "cursor":
            assert (project / ".cursor" / "rules" / "ambara.mdc").exists()
            assert (project / ".cursor" / "mcp.json").exists()
        elif client == "gemini":
            assert (project / "GEMINI.md").exists()
            assert (project / ".mcp.json").exists()
        elif client == "claude-code":
            assert (project / "CLAUDE.md").exists()
            assert (project / ".mcp.json").exists()
        else:
            assert payload["instructions_path"] is None

    def test_disable_marks_project_mcp_server_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/kb.git"
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        mcp = runner.invoke(main, ["mcp-config", "--remote", remote, "--write-project"])
        result = runner.invoke(main, ["disable"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})

        assert mcp.exit_code == 0
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".mcp.json").read_text())
        server = next(iter(data["mcpServers"].values()))
        assert server["env"]["AMBARA_DISABLED"] == "true"

    def test_enable_restores_project_config_and_mcp_server(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/kb.git"
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        mcp = runner.invoke(main, ["mcp-config", "--remote", remote, "--write-project"])
        disable = runner.invoke(main, ["disable"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})
        enable = runner.invoke(main, ["enable"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})

        assert mcp.exit_code == 0
        assert disable.exit_code == 0
        assert enable.exit_code == 0
        config = (tmp_path / ".ambara" / "config.yaml").read_text()
        assert "enabled: true" in config
        data = json.loads((tmp_path / ".mcp.json").read_text())
        server = next(iter(data["mcpServers"].values()))
        assert "AMBARA_DISABLED" not in server["env"]

    def test_mute_scope_writes_project_config_and_doctor_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(
            main,
            [
                "mute-scope",
                "--project",
                "LEGACY-PROJ",
                "--repo",
                "Org/API",
                "--source-input",
                "GitHub",
                "--tag",
                "stale",
            ],
            env={"AMBARA_KNOWLEDGE_REMOTE": ""},
        )
        doctor = runner.invoke(main, ["doctor"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})

        assert result.exit_code == 0
        assert "Muted Ambara scope(s)" in result.output
        config = (tmp_path / ".ambara" / "config.yaml").read_text()
        assert "muted_scopes:" in config
        assert "- legacy-proj" in config
        assert "- org/api" in config
        assert "- github" in config
        assert "- stale" in config
        assert doctor.exit_code == 0
        assert "muted scopes: 4" in doctor.output
        assert "projects: legacy-proj" in doctor.output
        assert "source_inputs: github" in doctor.output
        assert "signal_sources: github" not in doctor.output

    def test_mute_scope_preserves_legacy_signal_source_alias(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(
            main,
            [
                "mute-scope",
                "--signal-source",
                "GitHub",
            ],
            env={"AMBARA_KNOWLEDGE_REMOTE": ""},
        )

        assert result.exit_code == 0
        assert "source_inputs: github" in result.output
        config = (tmp_path / ".ambara" / "config.yaml").read_text()
        assert "signal_sources:" in config
        assert "- github" in config

    def test_unmute_scope_removes_project_config_scopes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        mute = runner.invoke(
            main,
            ["mute-scope", "--source-input", "GitHub", "--tag", "stale"],
            env={"AMBARA_KNOWLEDGE_REMOTE": ""},
        )
        unmute = runner.invoke(
            main,
            ["unmute-scope", "--source-input", "GitHub", "--tag", "stale"],
            env={"AMBARA_KNOWLEDGE_REMOTE": ""},
        )

        assert mute.exit_code == 0
        assert unmute.exit_code == 0
        assert "muted scopes: none" in unmute.output
        config = (tmp_path / ".ambara" / "config.yaml").read_text()
        assert "muted_scopes:" not in config

    def test_retire_scope_creates_review_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        repo = _init_git_repo(tmp_path)
        entry = tmp_path / "projects" / "legacy-proj-summary.md"
        entry.parent.mkdir()
        entry.write_text(
            """---
schema_version: 1
id: legacy-proj-summary
title: LEGACY-PROJ summary
type: project
level: L1
status: active
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
expires_at: null
projects: [LEGACY-PROJ]
tags: []
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: false
  pr: null
---

Old project context.
"""
        )
        repo.index.add(["projects/legacy-proj-summary.md"])
        repo.index.commit("add project")
        runner = CliRunner()

        result = runner.invoke(
            main,
            [
                "retire-scope",
                "--repo-path",
                str(tmp_path),
                "--project",
                "LEGACY-PROJ",
                "--branch",
                "ambara/retire-test",
            ],
        )

        assert result.exit_code == 0
        assert "Retired scope on branch ambara/retire-test" in result.output
        assert repo.active_branch.name == "ambara/retire-test"
        post = frontmatter.load(entry)
        assert post.metadata["status"] == "expired"
        assert (tmp_path / ".ambara" / "lifecycle").exists()

    def test_clear_requires_all_or_filter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(main, ["clear", "--repo-path", str(tmp_path)])

        assert result.exit_code == 1
        assert "Pass --all or at least one filter" in result.output

    def test_clear_all_cannot_combine_with_selectors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["clear", "--repo-path", str(tmp_path), "--all", "--project", "demo"],
        )

        assert result.exit_code == 1
        assert "Use --all by itself" in result.output

    def test_clear_dry_run_lists_matches_without_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _init_git_repo(tmp_path)
        entry = tmp_path / "projects" / "demo-context.md"
        entry.parent.mkdir()
        entry.write_text(
            """---
schema_version: 1
id: demo-context
title: Demo context
type: project
level: L1
status: active
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
expires_at: null
projects: [demo]
tags: []
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: false
  pr: null
source: null
---

Demo context.
"""
        )
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["clear", "--repo-path", str(tmp_path), "--project", "demo", "--dry-run"],
        )

        assert result.exit_code == 0
        assert "Matched 1 entry to clear" in result.output
        assert "demo-context" in result.output
        assert "No files written." in result.output
        post = frontmatter.load(entry)
        assert post.metadata["status"] == "active"

    def test_clear_creates_review_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        repo = _init_git_repo(tmp_path)
        demo_entry = tmp_path / "projects" / "demo-context.md"
        other_entry = tmp_path / "projects" / "other-context.md"
        demo_entry.parent.mkdir()
        demo_entry.write_text(
            """---
schema_version: 1
id: demo-context
title: Demo context
type: project
level: L1
status: active
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
expires_at: null
projects: [demo]
tags: [cleanup]
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: false
  pr: null
source: null
---

Demo context.
"""
        )
        other_entry.write_text(
            """---
schema_version: 1
id: other-context
title: Other context
type: project
level: L1
status: active
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
expires_at: null
projects: [other]
tags: []
supersedes: []
superseded_by: null
sensitivity: normal
review:
  required: false
  pr: null
source: null
---

Other context.
"""
        )
        repo.index.add(["projects/demo-context.md", "projects/other-context.md"])
        repo.index.commit("add projects")
        runner = CliRunner()

        result = runner.invoke(
            main,
            [
                "clear",
                "--repo-path",
                str(tmp_path),
                "--tag",
                "cleanup",
                "--branch",
                "ambara/clear-test",
            ],
        )

        assert result.exit_code == 0
        assert "Cleared context on branch ambara/clear-test" in result.output
        assert repo.active_branch.name == "ambara/clear-test"
        demo_post = frontmatter.load(demo_entry)
        other_post = frontmatter.load(other_entry)
        assert demo_post.metadata["status"] == "expired"
        assert other_post.metadata["status"] == "active"
        assert (tmp_path / ".ambara" / "lifecycle").exists()

    def test_doctor_disabled_is_intentional_without_remote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        runner = CliRunner()
        disable = runner.invoke(main, ["disable"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})

        result = runner.invoke(
            main,
            ["doctor", "--strict", "--check-startup", "--team"],
            env={"AMBARA_KNOWLEDGE_REMOTE": ""},
        )

        assert disable.exit_code == 0
        assert result.exit_code == 0
        assert "Ambara disabled:         yes" in result.output
        assert "disabled behavior:      local-only; no knowledge repo fetch" in result.output
        assert "startup(): disabled (agents proceed local-only)" in result.output
        assert "Ready for `ambara serve`: yes" in result.output
        assert "Fast path:" not in result.output

    def test_doctor_fix_project_config_requires_remote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["doctor", "--fix-project-config"],
            env={"AMBARA_KNOWLEDGE_REMOTE": ""},
        )

        assert result.exit_code == 1
        assert "Cannot repair project config without a knowledge repo remote" in result.output
        assert not (tmp_path / "CLAUDE.md").exists()
        assert not (tmp_path / ".mcp.json").exists()

    def test_doctor_fix_project_config_repairs_project_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/kb.git"
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["doctor", "--fix-project-config", "--strict"],
            env={"AMBARA_KNOWLEDGE_REMOTE": remote},
        )

        assert result.exit_code == 0
        assert "Project config repair" in result.output
        assert "Ready for `ambara serve`: yes" in result.output
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / ".claude" / "settings.json").exists()
        assert (tmp_path / ".mcp.json").exists()

        mcp = json.loads((tmp_path / ".mcp.json").read_text())
        server = next(iter(mcp["mcpServers"].values()))
        assert server["env"]["AMBARA_KNOWLEDGE_REMOTE"] == remote

    def test_doctor_fix_project_config_preserves_unrelated_mcp_servers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/kb.git"
        (tmp_path / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "jira": {
                            "command": "jira-mcp",
                            "args": ["serve"],
                        }
                    }
                }
            )
            + "\n"
        )
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["doctor", "--fix-project-config"],
            env={"AMBARA_KNOWLEDGE_REMOTE": remote},
        )

        assert result.exit_code == 0
        config = json.loads((tmp_path / ".mcp.json").read_text())
        assert "jira" in config["mcpServers"]
        assert any(name.startswith("ambara-") for name in config["mcpServers"])

    def test_doctor_fix_project_config_is_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/kb.git"
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        first = runner.invoke(
            main,
            ["doctor", "--fix-project-config"],
            env={"AMBARA_KNOWLEDGE_REMOTE": remote},
        )
        second = runner.invoke(
            main,
            ["doctor", "--fix-project-config"],
            env={"AMBARA_KNOWLEDGE_REMOTE": remote},
        )

        assert first.exit_code == 0
        assert second.exit_code == 0
        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        mcp = json.loads((tmp_path / ".mcp.json").read_text())
        assert len(settings["permissions"]["allow"]) == 30
        assert len(mcp["mcpServers"]) == 1

    def test_doctor_fix_project_config_can_run_startup_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = _build_local_remote(tmp_path)
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["doctor", "--fix-project-config", "--check-startup"],
            env={
                "AMBARA_KNOWLEDGE_REMOTE": str(remote.common_dir),
                "AMBARA_CACHE_DIR": str(tmp_path / "cache"),
            },
        )

        assert result.exit_code == 0
        assert "Project config repair" in result.output
        assert "Startup probe:" in result.output
        assert "sync():    ok (1 entries indexed)" in result.output
        assert "context(): ok" in result.output

    def test_doctor_reports_startup_contract_and_auto_approval(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        runner = CliRunner()
        install = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert install.exit_code == 0

        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main, ["doctor"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})

        assert result.exit_code == 0
        assert "CLAUDE.md startup contract: yes" in result.output
        assert "read-only tools auto-approved: yes" in result.output
        assert "write tools auto-approved:     yes" in result.output

    def test_startup_contract_requires_halt_on_failure_rule(self) -> None:
        from ambara.cli.install import _has_startup_contract

        old_contract = (
            "## Ambara — Team Knowledge\n\nBefore reading files, call sync() then context().\n"
        )
        new_contract = (
            "## Ambara — Team Knowledge\n\n"
            "Before reading files, call sync() then context().\n"
            "Treat this as a hard precondition.\n"
            "If either fails, team context is unavailable.\n"
            "Do not proceed from local-only context.\n"
            "Follow the verdict.\n"
            "Use read_many() only for entries you rely on.\n"
        )

        assert not _has_startup_contract(old_contract)
        assert _has_startup_contract(new_contract)

    def test_startup_contract_accepts_v2_template(self) -> None:
        from ambara.cli.install import _ambara_claude_md_section_v2, _has_startup_contract

        v2_content = _ambara_claude_md_section_v2("https://example.com/kb.git")
        assert _has_startup_contract(v2_content)

        minimal_v2 = (
            "## Ambara — Team Knowledge\n\n"
            "Call startup(repo=...) before reading files.\n"
            "Follow the action field.\n"
            "If startup fails or returns unavailable context, stop.\n"
        )
        assert _has_startup_contract(minimal_v2)

    def test_doctor_reports_missing_hash_specific_permissions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/kb.git"
        runner = CliRunner()
        install = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert install.exit_code == 0

        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main, ["doctor"], env={"AMBARA_KNOWLEDGE_REMOTE": remote})

        from ambara.cli.install import _mcp_server_name

        server_name = _mcp_server_name(remote)
        assert result.exit_code == 0
        assert "read-only tools auto-approved: no" in result.output
        assert f"mcp__{server_name}__context" in result.output
        assert "Ready for `ambara serve`: no" in result.output

    def test_doctor_accepts_hash_specific_permissions_without_stable_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/kb.git"
        runner = CliRunner()
        install = runner.invoke(
            main,
            ["install-claude-md", "--repo-path", str(tmp_path), "--remote", remote],
        )
        assert install.exit_code == 0

        from ambara.cli.install import _mcp_server_name

        server_name = _mcp_server_name(remote)
        settings_file = tmp_path / ".claude" / "settings.json"
        data = json.loads(settings_file.read_text())
        data["permissions"]["allow"] = [
            item for item in data["permissions"]["allow"] if f"mcp__{server_name}__" in item
        ]
        settings_file.write_text(json.dumps(data, indent=2) + "\n")

        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main, ["doctor"], env={"AMBARA_KNOWLEDGE_REMOTE": remote})

        assert result.exit_code == 0
        assert "read-only tools auto-approved: yes" in result.output
        assert "write tools auto-approved:     yes" in result.output

    def test_doctor_check_startup_verifies_sync_and_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = _build_local_remote(tmp_path)
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["doctor", "--check-startup"],
            env={
                "AMBARA_KNOWLEDGE_REMOTE": str(remote.common_dir),
                "AMBARA_CACHE_DIR": str(tmp_path / "cache"),
            },
        )

        assert result.exit_code == 0
        assert "Startup probe:" in result.output
        assert "sync():    ok (1 entries indexed)" in result.output
        assert "context(): ok" in result.output

    def test_doctor_check_startup_explains_unusable_cache_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = _build_local_remote(tmp_path)
        bad_cache = tmp_path / "cache-file"
        bad_cache.write_text("not a directory")
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["doctor", "--check-startup"],
            env={
                "AMBARA_KNOWLEDGE_REMOTE": str(remote.common_dir),
                "AMBARA_CACHE_DIR": str(bad_cache),
            },
        )

        assert result.exit_code == 0
        assert "sync():    failed" in result.output
        assert "set AMBARA_CACHE_DIR to a writable directory" in result.output

    def test_doctor_finds_url_in_claude_md(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "## Shared Knowledge\n\nKnowledge repo: git@github.com:acme/ambara-knowledge.git\n"
        )
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["doctor"],
            env={"AMBARA_KNOWLEDGE_REMOTE": ""},
        )
        assert "git@github.com:acme/ambara-knowledge.git" in result.output

    def test_doctor_finds_url_in_ambara_remote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote_file = tmp_path / ".ambara-remote"
        remote_file.write_text("git@github.com:acme/ambara-knowledge.git\n")
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["doctor"],
            env={"AMBARA_KNOWLEDGE_REMOTE": ""},
        )
        assert result.exit_code == 0

    def test_doctor_finds_url_in_project_team_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / ".ambara" / "config.yaml"
        config.parent.mkdir()
        config.write_text(
            "schema_version: 1\n"
            "knowledge_remote: git@github.com:acme/ambara-knowledge.git\n"
            "active_refs_enabled: true\n"
        )
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(main, ["doctor"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})

        assert result.exit_code == 0
        assert "git@github.com:acme/ambara-knowledge.git" in result.output

    def test_doctor_team_reports_repo_readiness(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/ambara-knowledge.git"
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        install = runner.invoke(main, ["install-claude-md", "--remote", remote])
        assert install.exit_code == 0
        mcp = runner.invoke(main, ["mcp-config", "--remote", remote, "--write-project"])
        assert mcp.exit_code == 0

        result = runner.invoke(
            main,
            ["doctor", "--team", "--strict"],
            env={"AMBARA_KNOWLEDGE_REMOTE": ""},
        )

        assert result.exit_code == 0
        assert "Team readiness:" in result.output
        assert "repo participation marker: yes" in result.output
        assert "active refs policy:        disabled" in result.output
        assert "active refs TTL:           72h" in result.output
        assert (
            "privacy boundary:          repo readiness only; no teammate install/presence tracking"
            in result.output
        )
        assert "Team ready:                yes" in result.output

    def test_serve_check_missing_remote_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--check"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})
        assert result.exit_code == 1
        assert "AMBARA_KNOWLEDGE_REMOTE is required" in result.output

    def test_serve_check_disabled_without_remote_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        disable = runner.invoke(main, ["disable"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})
        result = runner.invoke(main, ["serve", "--check"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})

        assert disable.exit_code == 0
        assert result.exit_code == 0
        assert "state:           disabled" in result.output
        assert "skip knowledge repo clone, fetch, and indexing" in result.output

    def test_serve_check_explains_runtime_plan(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["serve", "--check"],
            env={"AMBARA_KNOWLEDGE_REMOTE": "https://example.com/repo.git"},
        )
        assert result.exit_code == 0
        assert "Ambara serve preflight" in result.output
        assert "clone or reuse the local cache" in result.output
        assert "Privacy boundary" in result.output

    def test_serve_check_discovers_onboarded_project_remote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "https://example.com/team-knowledge.git"
        runner = CliRunner()
        monkeypatch.chdir(tmp_path)

        onboard = runner.invoke(
            main,
            [
                "onboard",
                "--remote",
                remote,
                "--knowledge-repo",
                str(tmp_path / "knowledge"),
                "--project-repo",
                str(tmp_path),
                "--yes",
            ],
            env={"AMBARA_KNOWLEDGE_REMOTE": ""},
        )
        result = runner.invoke(
            main,
            ["serve", "--check"],
            env={"AMBARA_KNOWLEDGE_REMOTE": ""},
        )

        assert onboard.exit_code == 0
        assert result.exit_code == 0
        assert f"knowledge remote: {remote}" in result.output
        assert "clone or reuse the local cache" in result.output

    def test_wrapper_does_not_reference_old_local_checkout(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = (repo_root / "bin" / "ambara-mcp.sh").read_text()
        assert "/home/alice/ambara" not in wrapper
        assert "AMBARA_KNOWLEDGE_REMOTE is required" in wrapper


class TestInstallHook:
    def test_install_hook_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["install-hook", "--help"])
        assert result.exit_code == 0
        assert "post-commit" in result.output.lower() or "hook" in result.output.lower()

    def test_install_with_pre_push(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git" / "hooks"
        git_dir.mkdir(parents=True)
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            (Path(td) / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
            (Path(td) / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            result = runner.invoke(main, ["install-hook", "--with-pre-push"])
            assert result.exit_code == 0
            assert "pre-push" in result.output.lower()
            assert (Path(td) / ".git" / "hooks" / "pre-push").exists()


class TestCaptureCommand:
    def test_capture_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["capture", "--help"])
        assert result.exit_code == 0

    def test_capture_non_ambara_message(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["capture", "--message", "feat: normal commit"])
        assert "no ambara" in result.output.lower() or result.exit_code == 0

    def test_capture_queues_pending_marker(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            git_dir = Path(td) / ".git"
            git_dir.mkdir()

            result = runner.invoke(
                main,
                [
                    "capture",
                    "--message",
                    "ambara: postgres pool at 20 max",
                    "--commit",
                    "abc1234",
                    "--author",
                    "dev@co.com",
                    "--repo-slug",
                    "api-service",
                ],
            )

            assert result.exit_code == 0, result.output
            assert "[ambara] queued" in result.output
            data = json.loads((git_dir / "ambara-pending" / "abc1234.json").read_text())
            assert data == {
                "commit_sha": "abc1234",
                "message": "ambara: postgres pool at 20 max",
                "author": "dev@co.com",
                "repo_slug": "api-service",
            }


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

    def test_flush_processes_and_removes_pending_marker(self, tmp_path: Path) -> None:
        from ambara.capture.pending import save_pending
        from ambara.capture.pipeline import CaptureOutcome
        from ambara.core.schema import EscalationLevel

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            git_dir = Path(td) / ".git"
            git_dir.mkdir()
            marker_sha = "abc1234"
            save_pending(
                str(git_dir),
                marker_sha,
                "ambara: postgres pool at 20 max",
                author="dev@co.com",
                repo_slug="api-service",
            )

            with (
                patch("ambara.cli.capture.ensure_repo", return_value="/knowledge") as mock_ensure,
                patch("ambara.cli.capture.fetch_all") as mock_fetch,
                patch(
                    "ambara.capture.pipeline.run_capture",
                    return_value=CaptureOutcome(
                        entry_id="api-service-postgres-pool-at-20-max",
                        level=EscalationLevel.L1,
                        sha="def5678",
                        branch="ambara/api-service/postgres-pool-at-20-max",
                        secret_detected=False,
                    ),
                ) as mock_run_capture,
            ):
                result = runner.invoke(
                    main,
                    ["flush"],
                    env={
                        "AMBARA_KNOWLEDGE_REMOTE": "https://example.com/kb.git",
                        "AMBARA_CACHE_DIR": str(Path(td) / ".cache"),
                    },
                )

            assert result.exit_code == 0, result.output
            assert "Flushed abc1234" in result.output
            assert not (git_dir / "ambara-pending" / f"{marker_sha}.json").exists()
            mock_ensure.assert_called_once_with(
                "https://example.com/kb.git",
                str(Path(td) / ".cache"),
            )
            mock_fetch.assert_called_once()
            assert mock_run_capture.call_args.kwargs["repo_slug"] == "api-service"
            assert mock_run_capture.call_args.kwargs["source_author"] == "dev@co.com"

    def test_flush_keeps_pending_marker_on_failure(self, tmp_path: Path) -> None:
        from ambara.capture.pending import save_pending

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            git_dir = Path(td) / ".git"
            git_dir.mkdir()
            marker_sha = "abc1234"
            save_pending(str(git_dir), marker_sha, "ambara: postgres pool at 20 max")

            with (
                patch("ambara.cli.capture.ensure_repo", return_value="/knowledge"),
                patch("ambara.cli.capture.fetch_all"),
                patch("ambara.capture.pipeline.run_capture", side_effect=RuntimeError("boom")),
            ):
                result = runner.invoke(
                    main,
                    ["flush"],
                    env={
                        "AMBARA_KNOWLEDGE_REMOTE": "https://example.com/kb.git",
                        "AMBARA_CACHE_DIR": str(Path(td) / ".cache"),
                    },
                )

            assert result.exit_code != 0
            assert "boom" in result.output
            assert (git_dir / "ambara-pending" / f"{marker_sha}.json").exists()


class TestInstallClaudeMd:
    def test_creates_claude_md(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0

        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "Ambara" in content
        assert "Startup contract" in content
        assert "startup(repo=" in content
        assert "action" in content
        assert "record(" in content
        assert "propose(" in content
        assert "entry IDs" in content

    def test_creates_settings_json(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0

        settings = tmp_path / ".claude" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "mcp__ambara__context" in data["permissions"]["allow"]
        assert "mcp__ambara__read_many" in data["permissions"]["allow"]
        assert "mcp__ambara__record" in data["permissions"]["allow"]
        assert "mcp__ambara__expire" in data["permissions"]["allow"]
        assert len(data["permissions"]["allow"]) == 15

    def test_appends_to_existing_claude_md(self, tmp_path: Path) -> None:
        existing = tmp_path / "CLAUDE.md"
        existing.write_text("# My Project\n\nExisting content.\n")

        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0

        content = existing.read_text()
        assert "Existing content." in content
        assert "Ambara" in content

    def test_skips_if_current_section_already_present(self, tmp_path: Path) -> None:
        runner = CliRunner()
        first = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert first.exit_code == 0

        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "already current" in result.output

    def test_appends_when_project_title_mentions_ambara(self, tmp_path: Path) -> None:
        existing = tmp_path / "CLAUDE.md"
        existing.write_text("# Ambara\n\nProject-specific guidance.\n")

        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "Appended Ambara section" in result.output

        content = existing.read_text()
        assert "# Ambara" in content
        assert "Project-specific guidance." in content
        assert "## Ambara — Team Knowledge" in content
        assert "Startup contract" in content
        assert "startup(repo=" in content

    def test_replaces_stale_ambara_section(self, tmp_path: Path) -> None:
        existing = tmp_path / "CLAUDE.md"
        existing.write_text(
            "# Project\n\n"
            "## Ambara — Team Knowledge\n\n"
            "Already here.\n\n"
            "## Local Notes\n\n"
            "Keep this section.\n"
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "install-claude-md",
                "--repo-path",
                str(tmp_path),
                "--remote",
                "git@github.com:org/kb.git",
            ],
        )
        assert result.exit_code == 0
        assert "Updated Ambara section" in result.output

        content = existing.read_text()
        assert "Already here." not in content
        assert "Startup contract" in content
        assert "git@github.com:org/kb.git" in content
        assert "## Local Notes" in content
        assert "Keep this section." in content

    def test_merges_with_existing_settings_json(self, tmp_path: Path) -> None:
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings_file = settings_dir / "settings.json"
        settings_file.write_text(json.dumps({"permissions": {"allow": ["custom_tool"]}}) + "\n")

        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0

        data = json.loads(settings_file.read_text())
        assert "custom_tool" in data["permissions"]["allow"]
        assert "mcp__ambara__context" in data["permissions"]["allow"]

    def test_malformed_settings_json_reports_click_error(self, tmp_path: Path) -> None:
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text("{not json")

        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])

        assert result.exit_code != 0
        assert "invalid JSON" in result.output

    def test_includes_remote_when_provided(self, tmp_path: Path) -> None:
        remote = "git@github.com:org/kb.git"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "install-claude-md",
                "--repo-path",
                str(tmp_path),
                "--remote",
                remote,
            ],
        )
        assert result.exit_code == 0
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "git@github.com:org/kb.git" in content
        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        from ambara.cli.install import _mcp_server_name

        server_name = _mcp_server_name(remote)
        assert "mcp__ambara__context" in settings["permissions"]["allow"]
        assert f"mcp__{server_name}__context" in settings["permissions"]["allow"]
        assert f"mcp__{server_name}__record" in settings["permissions"]["allow"]
        assert len(settings["permissions"]["allow"]) == 30


class TestInstallClaudeMdV2:
    def test_default_creates_compact_v2_template(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0

        content = (tmp_path / "CLAUDE.md").read_text()
        assert "Ambara" in content
        assert "Startup contract" in content
        assert "startup(repo=" in content
        assert "`action` field" in content
        assert "availability: disabled" in content
        assert "read()" in content
        assert "unavailable" in content
        assert "record(" in content
        assert "propose(" in content
        assert "Never expose entry IDs" in content
        assert "Run startup and write tools silently" in content
        assert "first visible reply should be the final work-focused answer" in content

        assert "sync()" not in content
        assert "context()" not in content
        assert "Anti-patterns" not in content
        assert "Tool quick-reference" not in content
        assert "Normal request mapping" not in content
        assert "Content safety" not in content

    def test_v2_is_smaller_than_v1(self) -> None:
        from ambara.cli.install import _ambara_claude_md_section, _ambara_claude_md_section_v2

        v1 = _ambara_claude_md_section("https://example.com/kb.git")
        v2 = _ambara_claude_md_section_v2("https://example.com/kb.git")
        assert len(v2) < len(v1) * 0.5

    def test_default_includes_remote(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "install-claude-md",
                "--repo-path",
                str(tmp_path),
                "--remote",
                "git@github.com:org/kb.git",
            ],
        )
        assert result.exit_code == 0
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "git@github.com:org/kb.git" in content

    def test_v1_flag_gives_verbose_template(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path), "--v1"])
        assert result.exit_code == 0
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "sync()" in content
        assert "hard precondition" in content

    def test_default_passes_startup_contract_check(self, tmp_path: Path) -> None:
        from ambara.cli.install import _has_startup_contract

        runner = CliRunner()
        runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        content = (tmp_path / "CLAUDE.md").read_text()
        assert _has_startup_contract(content)


class TestMcpConfigCollision:
    def test_hash_based_server_name(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["mcp-config", "--remote", "https://github.com/org/kb.git"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        server_names = list(data["mcpServers"].keys())
        assert len(server_names) == 1
        assert server_names[0].startswith("ambara-")
        assert len(server_names[0]) > 7

    def test_different_remotes_get_different_names(self) -> None:
        from ambara.cli.install import _mcp_server_name

        name_a = _mcp_server_name("https://github.com/org/repo-a.git")
        name_b = _mcp_server_name("https://github.com/org/repo-b.git")
        assert name_a != name_b
        assert name_a.startswith("ambara-")
        assert name_b.startswith("ambara-")

    def test_same_remote_gets_same_name(self) -> None:
        from ambara.cli.install import _mcp_server_name

        name_1 = _mcp_server_name("https://github.com/org/kb.git")
        name_2 = _mcp_server_name("https://github.com/org/kb.git")
        assert name_1 == name_2

    def test_doctor_discovers_hash_based_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ambara.cli.install import _mcp_server_name

        server_name = _mcp_server_name("git@github.com:acme/kb.git")
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        server_name: {
                            "env": {"AMBARA_KNOWLEDGE_REMOTE": "git@github.com:acme/kb.git"}
                        }
                    }
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"], env={"AMBARA_KNOWLEDGE_REMOTE": ""})
        assert "git@github.com:acme/kb.git" in result.output

    def test_write_project_mcp_config_uses_hash_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(
            main,
            [
                "mcp-config",
                "--remote",
                "git@github.com:acme/kb.git",
                "--write-project",
            ],
        )

        assert result.exit_code == 0
        config = json.loads((tmp_path / ".mcp.json").read_text())
        names = list(config["mcpServers"])
        assert len(names) == 1
        assert names[0].startswith("ambara-")
        assert names[0] != "ambara"
        assert "collision risk" not in result.output

    def test_doctor_detects_global_project_server_name_collision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "project"
        home = tmp_path / "home"
        project.mkdir()
        (home / ".claude").mkdir(parents=True)
        (project / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "ambara": {
                            "command": "ambara",
                            "args": ["serve"],
                            "env": {"AMBARA_KNOWLEDGE_REMOTE": "git@github.com:acme/kb.git"},
                        }
                    }
                }
            )
        )
        (home / ".claude" / "mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "ambara": {
                            "command": "ambara",
                            "args": ["serve"],
                            "env": {"AMBARA_KNOWLEDGE_REMOTE": "git@github.com:acme/kb.git"},
                        }
                    }
                }
            )
        )
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.chdir(project)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["doctor", "--strict"],
            env={"AMBARA_KNOWLEDGE_REMOTE": "git@github.com:acme/kb.git"},
        )

        assert result.exit_code == 1
        assert "collision risk: duplicate MCP server names detected" in result.output
        assert "claude mcp remove <name> -s user" in result.output
        assert "mcp-config --remote <url> --write-project" in result.output
        assert "tools/call" not in result.output

    def test_doctor_does_not_block_on_unrelated_server_name_collision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "project"
        home = tmp_path / "home"
        project.mkdir()
        (home / ".claude").mkdir(parents=True)
        remote = "git@github.com:acme/kb.git"

        runner = CliRunner()
        install = runner.invoke(
            main,
            ["install-claude-md", "--repo-path", str(project), "--remote", remote],
        )
        assert install.exit_code == 0

        # Write the real project MCP config while using a duplicated unrelated
        # user-level server to match a messy real developer machine.
        from ambara.cli.install import _mcp_config_payload, _write_project_mcp_config

        _write_project_mcp_config(
            project / ".mcp.json",
            _mcp_config_payload(remote, "claude-code", "ambara"),
        )
        unrelated = {
            "mcpServers": {
                "jira": {
                    "command": "jira-mcp",
                    "args": ["serve"],
                }
            }
        }
        (home / ".claude" / "mcp.json").write_text(json.dumps(unrelated))
        (home / ".claude.json").write_text(json.dumps(unrelated))
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.chdir(project)

        result = runner.invoke(
            main,
            ["doctor", "--strict"],
            env={"AMBARA_KNOWLEDGE_REMOTE": remote},
        )

        assert result.exit_code == 0
        assert "collision risk: duplicate MCP server names detected" in result.output
        assert "jira" in result.output
        assert "duplicate non-Ambara servers do not block Ambara startup" in result.output
        assert "Ready for `ambara serve`: yes" in result.output


class TestQuickstartSettings:
    def test_quickstart_creates_settings_json(self, tmp_path: Path) -> None:
        target = tmp_path / "ambara-knowledge"
        runner = CliRunner()
        result = runner.invoke(main, ["quickstart", str(target)])
        assert result.exit_code == 0

        settings = target / ".claude" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "mcp__ambara__context" in data["permissions"]["allow"]
        assert "mcp__ambara__read_many" in data["permissions"]["allow"]
        assert len(data["permissions"]["allow"]) == 15


class TestSearchCommand:
    def test_search_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["search", "--help"])
        assert result.exit_code == 0

    def test_search_prints_query_guidance(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["search", "release checklist"])
        assert result.exit_code == 0
        assert "Searching for: release checklist" in result.output
        assert "AMBARA_KNOWLEDGE_REMOTE" in result.output
