"""Tests for jurati.cli."""

from __future__ import annotations

import json
import tarfile
import tomllib
from datetime import datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import frontmatter
import git
import pytest
from click.testing import CliRunner

from jurati import __version__
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
        writer.set_value("user", "name", "Jurati Test")
        writer.set_value("user", "email", "jurati-test@example.com")
    readme = path / "README.md"
    readme.write_text("# knowledge repo\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")
    return repo


def _build_local_remote(tmp_path: Path) -> git.Repo:
    bare = git.Repo.init(tmp_path / "remote.git", bare=True)
    seed = git.Repo.init(tmp_path / "seed")
    with seed.config_writer() as writer:
        writer.set_value("user", "name", "Jurati Test")
        writer.set_value("user", "email", "jurati-test@example.com")
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
        assert "jurati" in result.output.lower()

    def test_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_package_version_matches_pyproject(self) -> None:
        pyproject = tomllib.loads(Path("pyproject.toml").read_text())
        assert __version__ == pyproject["project"]["version"]

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
                "jurati/import-context-test",
                str(bundle),
            ],
        )

        assert result.exit_code == 0
        assert "Wrote import review branch" in result.output
        assert git_repo.active_branch.name == "jurati/import-context-test"
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
                "jurati/import-docs-test",
                "--mode",
                "docs",
                str(source),
            ],
        )

        assert result.exit_code == 0
        assert "Wrote import review branch" in result.output
        assert git_repo.active_branch.name == "jurati/import-docs-test"
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
        assert (tmp_path / ".jurati" / "read-model.sqlite3").exists()

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
        assert "active_refs_enabled: false" in config

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
        remote = "git@github.com:org/jurati-knowledge.git"
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
        assert '"JURATI_KNOWLEDGE_REMOTE": "git@github.com:org/jurati-knowledge.git"' in (
            result.output
        )
        assert '"JURATI_CLIENT_SLUG": "codex"' in result.output
        assert "Paste the MCP config above into your client" in result.output
        data = json.loads((target / ".claude" / "settings.json").read_text())
        from jurati.cli_install import _mcp_server_name

        server_name = _mcp_server_name(remote)
        assert f"mcp__{server_name}__context" in data["permissions"]["allow"]
        assert f"mcp__{server_name}__sync" in data["permissions"]["allow"]

    def test_quickstart_pack_prints_selected_pack(self, tmp_path: Path) -> None:
        target = tmp_path / "jurati-knowledge"
        runner = CliRunner()
        result = runner.invoke(main, ["quickstart", "--pack", "training", str(target)])

        assert result.exit_code == 0
        assert "Starter pack: training" in result.output
        assert "5 entries valid" in result.output

    def test_onboard_prompts_and_wires_project(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "jurati-knowledge"
        project = tmp_path / "project"
        project.mkdir()
        remote = "git@github.com:org/jurati-knowledge.git"
        runner = CliRunner()

        result = runner.invoke(
            main,
            ["onboard"],
            input=f"{remote}\n{knowledge}\n{project}\nengineering\n",
        )

        assert result.exit_code == 0
        assert "Jurati onboarding" in result.output
        assert "Knowledge repo remote URL" in result.output
        assert "Local onboarding complete." in result.output
        assert "git push -u origin main" in result.output
        assert "jurati doctor --check-startup" in result.output
        assert "sync(), context(repo=<current repo>, goal=<user request>), then work." in (
            result.output
        )
        assert "explain(), status()" not in result.output
        assert (knowledge / ".jurati" / "config.yaml").exists()
        assert (knowledge / "workflows" / "engineering-change-loop.md").exists()
        assert (project / "CLAUDE.md").exists()
        assert (project / ".jurati" / "config.yaml").exists()
        assert (project / ".claude" / "settings.json").exists()
        assert (project / ".mcp.json").exists()

        project_config = (project / ".jurati" / "config.yaml").read_text()
        assert f"knowledge_remote: {remote}" in project_config
        assert "active_refs_enabled: false" in project_config
        assert "client_slug" not in project_config

        mcp = json.loads((project / ".mcp.json").read_text())
        server = next(iter(mcp["mcpServers"].values()))
        assert server["env"]["JURATI_KNOWLEDGE_REMOTE"] == remote
        assert server["env"]["JURATI_CLIENT_SLUG"] == "claude-code"

    def test_onboard_flags_skip_optional_prompts(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "jurati-knowledge"
        project = tmp_path / "project"
        project.mkdir()
        remote = "git@github.com:org/jurati-knowledge.git"
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
        assert server["env"]["JURATI_CLIENT_SLUG"] == "codex"

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
        server_names = list(data["mcpServers"].keys())
        assert len(server_names) == 1
        assert server_names[0].startswith("jurati-")
        server = data["mcpServers"][server_names[0]]
        assert server["command"] == "jurati"
        assert server["args"] == ["serve"]
        assert server["env"]["JURATI_KNOWLEDGE_REMOTE"] == (
            "git@github.com:org/jurati-knowledge.git"
        )
        assert server["env"]["JURATI_CLIENT_SLUG"] == "codex"

    def test_mcp_config_carries_non_secret_pr_signal_env(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "mcp-config",
                "--remote",
                "git@github.com:org/jurati-knowledge.git",
            ],
            env={
                "JURATI_PR_SIGNAL_REPOS": "org/api",
                "JURATI_PR_SIGNAL_FIXTURE": "/tmp/pr-signals.json",
            },
        )

        assert result.exit_code == 0
        data = json.loads(result.output)
        server = next(iter(data["mcpServers"].values()))
        assert server["env"]["JURATI_PR_SIGNAL_REPOS"] == "org/api"
        assert server["env"]["JURATI_PR_SIGNAL_FIXTURE"] == "/tmp/pr-signals.json"

    def test_mcp_config_write_project_carries_repo_active_refs_policy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:org/jurati-knowledge.git"
        config = tmp_path / ".jurati" / "config.yaml"
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
        assert server["env"]["JURATI_ACTIVE_REFS_ENABLED"] == "true"
        assert server["env"]["JURATI_ACTIVE_REF_TTL_HOURS"] == "8"

    def test_mcp_config_write_project_carries_nested_active_refs_policy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:org/jurati-knowledge.git"
        config = tmp_path / ".jurati" / "config.yaml"
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
        assert server["env"]["JURATI_KNOWLEDGE_REMOTE"] == remote
        assert server["env"]["JURATI_ACTIVE_REFS_ENABLED"] == "true"
        assert server["env"]["JURATI_ACTIVE_REF_TTL_HOURS"] == "8"
        updated_config = config.read_text()
        assert "active_refs_enabled: false" not in updated_config

    def test_mcp_config_write_project_rejects_invalid_repo_ttl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:org/jurati-knowledge.git"
        config = tmp_path / ".jurati" / "config.yaml"
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
        result = runner.invoke(main, ["doctor"], env={"JURATI_KNOWLEDGE_REMOTE": ""})
        assert result.exit_code == 0
        assert "Ready for `jurati serve`: no" in result.output
        assert "Fast path:" in result.output
        assert "Agent startup:" in result.output

    def test_doctor_strict_without_remote_fails(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "--strict"], env={"JURATI_KNOWLEDGE_REMOTE": ""})
        assert result.exit_code == 1
        assert "Jurati is not ready" in result.output

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
            env={"JURATI_KNOWLEDGE_REMOTE": remote},
        )
        strict = runner.invoke(
            main,
            ["doctor", "--strict", "--audit"],
            env={"JURATI_KNOWLEDGE_REMOTE": remote},
        )

        assert install.exit_code == 0
        assert result.exit_code == 0
        assert "Audit/compliance claim gate:" in result.output
        assert "reviewable git-backed context: yes" in result.output
        assert "immutable ledger claim:       no" in result.output
        assert "tamper-evident ledger claim:  no" in result.output
        assert "SOC2-ready audit evidence:    no" in result.output
        assert "Ready for `jurati serve`: yes" in result.output
        assert "Ready for audit ledger claims: no" in result.output
        assert "Jurati-created commits are not signed or verified" in result.output
        assert strict.exit_code == 1
        assert "Jurati is not ready" in strict.output

    def test_disable_writes_project_config_and_startup_packet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(main, ["disable"], env={"JURATI_KNOWLEDGE_REMOTE": ""})
        startup = runner.invoke(main, ["startup"], env={"JURATI_KNOWLEDGE_REMOTE": ""})

        assert result.exit_code == 0
        assert "Disabled Jurati" in result.output
        assert "enabled: false" in (tmp_path / ".jurati" / "config.yaml").read_text()
        assert startup.exit_code == 0
        packet = json.loads(startup.output)
        assert packet["availability"] == "disabled"
        assert packet["action"] == "proceed_local_only"

    def test_disable_marks_project_mcp_server_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/kb.git"
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        mcp = runner.invoke(main, ["mcp-config", "--remote", remote, "--write-project"])
        result = runner.invoke(main, ["disable"], env={"JURATI_KNOWLEDGE_REMOTE": ""})

        assert mcp.exit_code == 0
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".mcp.json").read_text())
        server = next(iter(data["mcpServers"].values()))
        assert server["env"]["JURATI_DISABLED"] == "true"

    def test_enable_restores_project_config_and_mcp_server(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/kb.git"
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        mcp = runner.invoke(main, ["mcp-config", "--remote", remote, "--write-project"])
        disable = runner.invoke(main, ["disable"], env={"JURATI_KNOWLEDGE_REMOTE": ""})
        enable = runner.invoke(main, ["enable"], env={"JURATI_KNOWLEDGE_REMOTE": ""})

        assert mcp.exit_code == 0
        assert disable.exit_code == 0
        assert enable.exit_code == 0
        config = (tmp_path / ".jurati" / "config.yaml").read_text()
        assert "enabled: true" in config
        data = json.loads((tmp_path / ".mcp.json").read_text())
        server = next(iter(data["mcpServers"].values()))
        assert "JURATI_DISABLED" not in server["env"]

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
                "AU0035L",
                "--repo",
                "Org/API",
                "--signal-source",
                "GitHub",
                "--tag",
                "stale",
            ],
            env={"JURATI_KNOWLEDGE_REMOTE": ""},
        )
        doctor = runner.invoke(main, ["doctor"], env={"JURATI_KNOWLEDGE_REMOTE": ""})

        assert result.exit_code == 0
        assert "Muted Jurati scope(s)" in result.output
        config = (tmp_path / ".jurati" / "config.yaml").read_text()
        assert "muted_scopes:" in config
        assert "- au0035l" in config
        assert "- org/api" in config
        assert "- github" in config
        assert "- stale" in config
        assert doctor.exit_code == 0
        assert "muted scopes: 4" in doctor.output
        assert "projects: au0035l" in doctor.output

    def test_unmute_scope_removes_project_config_scopes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        mute = runner.invoke(
            main,
            ["mute-scope", "--project", "AU0035L", "--tag", "stale"],
            env={"JURATI_KNOWLEDGE_REMOTE": ""},
        )
        unmute = runner.invoke(
            main,
            ["unmute-scope", "--project", "AU0035L", "--tag", "stale"],
            env={"JURATI_KNOWLEDGE_REMOTE": ""},
        )

        assert mute.exit_code == 0
        assert unmute.exit_code == 0
        assert "muted scopes: none" in unmute.output
        config = (tmp_path / ".jurati" / "config.yaml").read_text()
        assert "muted_scopes:" not in config

    def test_retire_scope_creates_review_branch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        repo = _init_git_repo(tmp_path)
        entry = tmp_path / "projects" / "au0035l-summary.md"
        entry.parent.mkdir()
        entry.write_text(
            """---
schema_version: 1
id: au0035l-summary
title: AU0035L summary
type: project
level: L1
status: active
created_at: 2026-05-01T12:00:00Z
updated_at: 2026-05-01T12:00:00Z
expires_at: null
projects: [AU0035L]
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
        repo.index.add(["projects/au0035l-summary.md"])
        repo.index.commit("add project")
        runner = CliRunner()

        result = runner.invoke(
            main,
            [
                "retire-scope",
                "--repo-path",
                str(tmp_path),
                "--project",
                "AU0035L",
                "--branch",
                "jurati/retire-test",
            ],
        )

        assert result.exit_code == 0
        assert "Retired scope on branch jurati/retire-test" in result.output
        assert repo.active_branch.name == "jurati/retire-test"
        post = frontmatter.load(entry)
        assert post.metadata["status"] == "expired"
        assert (tmp_path / ".jurati" / "lifecycle").exists()

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
                "jurati/clear-test",
            ],
        )

        assert result.exit_code == 0
        assert "Cleared context on branch jurati/clear-test" in result.output
        assert repo.active_branch.name == "jurati/clear-test"
        demo_post = frontmatter.load(demo_entry)
        other_post = frontmatter.load(other_entry)
        assert demo_post.metadata["status"] == "expired"
        assert other_post.metadata["status"] == "active"
        assert (tmp_path / ".jurati" / "lifecycle").exists()

    def test_doctor_disabled_is_intentional_without_remote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        runner = CliRunner()
        disable = runner.invoke(main, ["disable"], env={"JURATI_KNOWLEDGE_REMOTE": ""})

        result = runner.invoke(
            main,
            ["doctor", "--strict", "--check-startup", "--team"],
            env={"JURATI_KNOWLEDGE_REMOTE": ""},
        )

        assert disable.exit_code == 0
        assert result.exit_code == 0
        assert "Jurati disabled:         yes" in result.output
        assert "disabled behavior:      local-only; no knowledge repo fetch" in result.output
        assert "startup(): disabled (agents proceed local-only)" in result.output
        assert "Ready for `jurati serve`: yes" in result.output
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
            env={"JURATI_KNOWLEDGE_REMOTE": ""},
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
            env={"JURATI_KNOWLEDGE_REMOTE": remote},
        )

        assert result.exit_code == 0
        assert "Project config repair" in result.output
        assert "Ready for `jurati serve`: yes" in result.output
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / ".claude" / "settings.json").exists()
        assert (tmp_path / ".mcp.json").exists()

        mcp = json.loads((tmp_path / ".mcp.json").read_text())
        server = next(iter(mcp["mcpServers"].values()))
        assert server["env"]["JURATI_KNOWLEDGE_REMOTE"] == remote

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
            env={"JURATI_KNOWLEDGE_REMOTE": remote},
        )

        assert result.exit_code == 0
        config = json.loads((tmp_path / ".mcp.json").read_text())
        assert "jira" in config["mcpServers"]
        assert any(name.startswith("jurati-") for name in config["mcpServers"])

    def test_doctor_fix_project_config_is_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/kb.git"
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        first = runner.invoke(
            main,
            ["doctor", "--fix-project-config"],
            env={"JURATI_KNOWLEDGE_REMOTE": remote},
        )
        second = runner.invoke(
            main,
            ["doctor", "--fix-project-config"],
            env={"JURATI_KNOWLEDGE_REMOTE": remote},
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
                "JURATI_KNOWLEDGE_REMOTE": str(remote.common_dir),
                "JURATI_CACHE_DIR": str(tmp_path / "cache"),
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
        result = runner.invoke(main, ["doctor"], env={"JURATI_KNOWLEDGE_REMOTE": ""})

        assert result.exit_code == 0
        assert "CLAUDE.md startup contract: yes" in result.output
        assert "read-only tools auto-approved: yes" in result.output
        assert "write tools auto-approved:     yes" in result.output

    def test_startup_contract_requires_halt_on_failure_rule(self) -> None:
        from jurati.cli_install import _has_startup_contract

        old_contract = (
            "## Jurati — Team Knowledge\n\nBefore reading files, call sync() then context().\n"
        )
        new_contract = (
            "## Jurati — Team Knowledge\n\n"
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
        from jurati.cli_install import _has_startup_contract, _jurati_claude_md_section_v2

        v2_content = _jurati_claude_md_section_v2("https://example.com/kb.git")
        assert _has_startup_contract(v2_content)

        minimal_v2 = (
            "## Jurati — Team Knowledge\n\n"
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
        result = runner.invoke(main, ["doctor"], env={"JURATI_KNOWLEDGE_REMOTE": remote})

        from jurati.cli_install import _mcp_server_name

        server_name = _mcp_server_name(remote)
        assert result.exit_code == 0
        assert "read-only tools auto-approved: no" in result.output
        assert f"mcp__{server_name}__context" in result.output
        assert "Ready for `jurati serve`: no" in result.output

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

        from jurati.cli_install import _mcp_server_name

        server_name = _mcp_server_name(remote)
        settings_file = tmp_path / ".claude" / "settings.json"
        data = json.loads(settings_file.read_text())
        data["permissions"]["allow"] = [
            item for item in data["permissions"]["allow"] if f"mcp__{server_name}__" in item
        ]
        settings_file.write_text(json.dumps(data, indent=2) + "\n")

        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main, ["doctor"], env={"JURATI_KNOWLEDGE_REMOTE": remote})

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
                "JURATI_KNOWLEDGE_REMOTE": str(remote.common_dir),
                "JURATI_CACHE_DIR": str(tmp_path / "cache"),
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
                "JURATI_KNOWLEDGE_REMOTE": str(remote.common_dir),
                "JURATI_CACHE_DIR": str(bad_cache),
            },
        )

        assert result.exit_code == 0
        assert "sync():    failed" in result.output
        assert "set JURATI_CACHE_DIR to a writable directory" in result.output

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

    def test_doctor_finds_url_in_project_team_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / ".jurati" / "config.yaml"
        config.parent.mkdir()
        config.write_text(
            "schema_version: 1\n"
            "knowledge_remote: git@github.com:acme/jurati-knowledge.git\n"
            "active_refs_enabled: false\n"
        )
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        result = runner.invoke(main, ["doctor"], env={"JURATI_KNOWLEDGE_REMOTE": ""})

        assert result.exit_code == 0
        assert "git@github.com:acme/jurati-knowledge.git" in result.output

    def test_doctor_team_reports_repo_readiness(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = "git@github.com:acme/jurati-knowledge.git"
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        install = runner.invoke(main, ["install-claude-md", "--remote", remote])
        assert install.exit_code == 0
        mcp = runner.invoke(main, ["mcp-config", "--remote", remote, "--write-project"])
        assert mcp.exit_code == 0

        result = runner.invoke(
            main,
            ["doctor", "--team", "--strict"],
            env={"JURATI_KNOWLEDGE_REMOTE": ""},
        )

        assert result.exit_code == 0
        assert "Team readiness:" in result.output
        assert "repo participation marker: yes" in result.output
        assert "active refs policy:        disabled" in result.output
        assert "active refs TTL:           72h" in result.output
        assert (
            "privacy boundary:          repo readiness only; no teammate presence" in result.output
        )
        assert "Team ready:                yes" in result.output

    def test_serve_check_missing_remote_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--check"], env={"JURATI_KNOWLEDGE_REMOTE": ""})
        assert result.exit_code == 1
        assert "JURATI_KNOWLEDGE_REMOTE is required" in result.output

    def test_serve_check_disabled_without_remote_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        disable = runner.invoke(main, ["disable"], env={"JURATI_KNOWLEDGE_REMOTE": ""})
        result = runner.invoke(main, ["serve", "--check"], env={"JURATI_KNOWLEDGE_REMOTE": ""})

        assert disable.exit_code == 0
        assert result.exit_code == 0
        assert "state:           disabled" in result.output
        assert "skip knowledge repo clone, fetch, and indexing" in result.output

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
            env={"JURATI_KNOWLEDGE_REMOTE": ""},
        )
        result = runner.invoke(
            main,
            ["serve", "--check"],
            env={"JURATI_KNOWLEDGE_REMOTE": ""},
        )

        assert onboard.exit_code == 0
        assert result.exit_code == 0
        assert f"knowledge remote: {remote}" in result.output
        assert "clone or reuse the local cache" in result.output

    def test_wrapper_does_not_reference_old_local_checkout(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = (repo_root / "bin" / "jurati-mcp.sh").read_text()
        assert "/home/eparenti/jurati" not in wrapper
        assert "JURATI_KNOWLEDGE_REMOTE is required" in wrapper


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

    def test_capture_non_jurati_message(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["capture", "--message", "feat: normal commit"])
        assert "no jurati" in result.output.lower() or result.exit_code == 0

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
                    "jurati: postgres pool at 20 max",
                    "--commit",
                    "abc1234",
                    "--author",
                    "dev@co.com",
                    "--repo-slug",
                    "api-service",
                ],
            )

            assert result.exit_code == 0, result.output
            assert "[jurati] queued" in result.output
            data = json.loads((git_dir / "jurati-pending" / "abc1234.json").read_text())
            assert data == {
                "commit_sha": "abc1234",
                "message": "jurati: postgres pool at 20 max",
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
        from jurati.capture.pending import save_pending
        from jurati.capture.pipeline import CaptureOutcome
        from jurati.core.schema import EscalationLevel

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            git_dir = Path(td) / ".git"
            git_dir.mkdir()
            marker_sha = "abc1234"
            save_pending(
                str(git_dir),
                marker_sha,
                "jurati: postgres pool at 20 max",
                author="dev@co.com",
                repo_slug="api-service",
            )

            with (
                patch("jurati.cli.ensure_repo", return_value="/knowledge") as mock_ensure,
                patch("jurati.cli.fetch_all") as mock_fetch,
                patch(
                    "jurati.capture.pipeline.run_capture",
                    return_value=CaptureOutcome(
                        entry_id="api-service-postgres-pool-at-20-max",
                        level=EscalationLevel.L1,
                        sha="def5678",
                        branch="jurati/api-service/postgres-pool-at-20-max",
                        secret_detected=False,
                    ),
                ) as mock_run_capture,
            ):
                result = runner.invoke(
                    main,
                    ["flush"],
                    env={
                        "JURATI_KNOWLEDGE_REMOTE": "https://example.com/kb.git",
                        "JURATI_CACHE_DIR": str(Path(td) / ".cache"),
                    },
                )

            assert result.exit_code == 0, result.output
            assert "Flushed abc1234" in result.output
            assert not (git_dir / "jurati-pending" / f"{marker_sha}.json").exists()
            mock_ensure.assert_called_once_with(
                "https://example.com/kb.git",
                str(Path(td) / ".cache"),
            )
            mock_fetch.assert_called_once()
            assert mock_run_capture.call_args.kwargs["repo_slug"] == "api-service"
            assert mock_run_capture.call_args.kwargs["source_author"] == "dev@co.com"

    def test_flush_keeps_pending_marker_on_failure(self, tmp_path: Path) -> None:
        from jurati.capture.pending import save_pending

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            git_dir = Path(td) / ".git"
            git_dir.mkdir()
            marker_sha = "abc1234"
            save_pending(str(git_dir), marker_sha, "jurati: postgres pool at 20 max")

            with (
                patch("jurati.cli.ensure_repo", return_value="/knowledge"),
                patch("jurati.cli.fetch_all"),
                patch("jurati.capture.pipeline.run_capture", side_effect=RuntimeError("boom")),
            ):
                result = runner.invoke(
                    main,
                    ["flush"],
                    env={
                        "JURATI_KNOWLEDGE_REMOTE": "https://example.com/kb.git",
                        "JURATI_CACHE_DIR": str(Path(td) / ".cache"),
                    },
                )

            assert result.exit_code != 0
            assert "boom" in result.output
            assert (git_dir / "jurati-pending" / f"{marker_sha}.json").exists()


class TestInstallClaudeMd:
    def test_creates_claude_md(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0

        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "Jurati" in content
        assert "Startup contract" in content
        assert "Before reading files" in content
        assert "hard precondition" in content
        assert "If `sync()` or `context()` fails" in content
        assert "reports `disabled`" in content
        assert "should not proceed from local-only context" in content
        assert "Follow any verdict" in content
        assert "read_many()" in content
        assert "Do not bulk-read every entry" in content
        assert "sync()" in content
        assert "context()" in content
        assert "Normal request mapping" in content
        assert '"Record this decision"' in content
        assert '"Save this handoff"' in content
        assert "Good developer-facing confirmations" in content
        assert '"Recorded the token format decision."' in content
        assert '"Cleared the stale handoff."' in content
        assert "entry IDs, branch names, ref paths, PR numbers" in content

    def test_creates_settings_json(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0

        settings = tmp_path / ".claude" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "mcp__jurati__context" in data["permissions"]["allow"]
        assert "mcp__jurati__read_many" in data["permissions"]["allow"]
        assert "mcp__jurati__record" in data["permissions"]["allow"]
        assert "mcp__jurati__expire" in data["permissions"]["allow"]
        assert len(data["permissions"]["allow"]) == 15

    def test_appends_to_existing_claude_md(self, tmp_path: Path) -> None:
        existing = tmp_path / "CLAUDE.md"
        existing.write_text("# My Project\n\nExisting content.\n")

        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0

        content = existing.read_text()
        assert "Existing content." in content
        assert "Jurati" in content

    def test_skips_if_current_section_already_present(self, tmp_path: Path) -> None:
        runner = CliRunner()
        first = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert first.exit_code == 0

        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "already current" in result.output

    def test_appends_when_project_title_mentions_jurati(self, tmp_path: Path) -> None:
        existing = tmp_path / "CLAUDE.md"
        existing.write_text("# Jurati\n\nProject-specific guidance.\n")

        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert result.exit_code == 0
        assert "Appended Jurati section" in result.output

        content = existing.read_text()
        assert "# Jurati" in content
        assert "Project-specific guidance." in content
        assert "## Jurati — Team Knowledge" in content
        assert "Startup contract" in content
        assert "Before reading files" in content
        assert "hard precondition" in content

    def test_replaces_stale_jurati_section(self, tmp_path: Path) -> None:
        existing = tmp_path / "CLAUDE.md"
        existing.write_text(
            "# Project\n\n"
            "## Jurati — Team Knowledge\n\n"
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
        assert "Updated Jurati section" in result.output

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
        assert "mcp__jurati__context" in data["permissions"]["allow"]

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
        from jurati.cli_install import _mcp_server_name

        server_name = _mcp_server_name(remote)
        assert "mcp__jurati__context" in settings["permissions"]["allow"]
        assert f"mcp__{server_name}__context" in settings["permissions"]["allow"]
        assert f"mcp__{server_name}__record" in settings["permissions"]["allow"]
        assert len(settings["permissions"]["allow"]) == 30


class TestInstallClaudeMdV2:
    def test_v2_creates_compact_template(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path), "--v2"])
        assert result.exit_code == 0

        content = (tmp_path / "CLAUDE.md").read_text()
        assert "Jurati" in content
        assert "Startup contract" in content
        assert "startup(repo=" in content
        assert "`action` field" in content
        assert "availability: disabled" in content
        assert "read()" in content
        assert "unavailable" in content
        assert "record(" in content
        assert "propose(" in content
        assert "Never expose entry IDs" in content

        assert "sync()" not in content
        assert "context()" not in content
        assert "Anti-patterns" not in content
        assert "Tool quick-reference" not in content
        assert "Normal request mapping" not in content
        assert "Content safety" not in content

    def test_v2_is_smaller_than_v1(self) -> None:
        from jurati.cli_install import _jurati_claude_md_section, _jurati_claude_md_section_v2

        v1 = _jurati_claude_md_section("https://example.com/kb.git")
        v2 = _jurati_claude_md_section_v2("https://example.com/kb.git")
        assert len(v2) < len(v1) * 0.5

    def test_v2_includes_remote(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "install-claude-md",
                "--repo-path",
                str(tmp_path),
                "--remote",
                "git@github.com:org/kb.git",
                "--v2",
            ],
        )
        assert result.exit_code == 0
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "git@github.com:org/kb.git" in content

    def test_v2_replaces_v1_section(self, tmp_path: Path) -> None:
        runner = CliRunner()
        runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        content_v1 = (tmp_path / "CLAUDE.md").read_text()
        assert "sync()" in content_v1

        result = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path), "--v2"])
        assert result.exit_code == 0
        assert "Updated Jurati section" in result.output

        content_v2 = (tmp_path / "CLAUDE.md").read_text()
        assert "startup(repo=" in content_v2
        assert "sync()" not in content_v2

    def test_v2_passes_startup_contract_check(self, tmp_path: Path) -> None:
        from jurati.cli_install import _has_startup_contract

        runner = CliRunner()
        runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path), "--v2"])
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
        assert server_names[0].startswith("jurati-")
        assert len(server_names[0]) > 7

    def test_different_remotes_get_different_names(self) -> None:
        from jurati.cli_install import _mcp_server_name

        name_a = _mcp_server_name("https://github.com/org/repo-a.git")
        name_b = _mcp_server_name("https://github.com/org/repo-b.git")
        assert name_a != name_b
        assert name_a.startswith("jurati-")
        assert name_b.startswith("jurati-")

    def test_same_remote_gets_same_name(self) -> None:
        from jurati.cli_install import _mcp_server_name

        name_1 = _mcp_server_name("https://github.com/org/kb.git")
        name_2 = _mcp_server_name("https://github.com/org/kb.git")
        assert name_1 == name_2

    def test_doctor_discovers_hash_based_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from jurati.cli_install import _mcp_server_name

        server_name = _mcp_server_name("git@github.com:acme/kb.git")
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        server_name: {
                            "env": {"JURATI_KNOWLEDGE_REMOTE": "git@github.com:acme/kb.git"}
                        }
                    }
                }
            )
        )
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"], env={"JURATI_KNOWLEDGE_REMOTE": ""})
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
        assert names[0].startswith("jurati-")
        assert names[0] != "jurati"
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
                        "jurati": {
                            "command": "jurati",
                            "args": ["serve"],
                            "env": {"JURATI_KNOWLEDGE_REMOTE": "git@github.com:acme/kb.git"},
                        }
                    }
                }
            )
        )
        (home / ".claude" / "mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "jurati": {
                            "command": "jurati",
                            "args": ["serve"],
                            "env": {"JURATI_KNOWLEDGE_REMOTE": "git@github.com:acme/kb.git"},
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
            env={"JURATI_KNOWLEDGE_REMOTE": "git@github.com:acme/kb.git"},
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
        from jurati.cli_install import _mcp_config_payload, _write_project_mcp_config

        _write_project_mcp_config(
            project / ".mcp.json",
            _mcp_config_payload(remote, "claude-code", "jurati"),
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
            env={"JURATI_KNOWLEDGE_REMOTE": remote},
        )

        assert result.exit_code == 0
        assert "collision risk: duplicate MCP server names detected" in result.output
        assert "jira" in result.output
        assert "duplicate non-Jurati servers do not block Jurati startup" in result.output
        assert "Ready for `jurati serve`: yes" in result.output


class TestQuickstartSettings:
    def test_quickstart_creates_settings_json(self, tmp_path: Path) -> None:
        target = tmp_path / "jurati-knowledge"
        runner = CliRunner()
        result = runner.invoke(main, ["quickstart", str(target)])
        assert result.exit_code == 0

        settings = target / ".claude" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "mcp__jurati__context" in data["permissions"]["allow"]
        assert "mcp__jurati__read_many" in data["permissions"]["allow"]
        assert len(data["permissions"]["allow"]) == 15


class TestSearchCommand:
    def test_search_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["search", "--help"])
        assert result.exit_code == 0
