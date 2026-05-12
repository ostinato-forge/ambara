"""Tests for jurati.cli."""

from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path

import git
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

    def test_doctor_reports_startup_contract_and_auto_approval(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = CliRunner()
        install = runner.invoke(main, ["install-claude-md", "--repo-path", str(tmp_path)])
        assert install.exit_code == 0

        monkeypatch.chdir(tmp_path)
        result = runner.invoke(main, ["doctor"], env={"JURATI_KNOWLEDGE_REMOTE": ""})

        assert result.exit_code == 0
        assert "CLAUDE.md startup contract: yes" in result.output
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
        assert "sync()" in content
        assert "context()" in content
        assert "Normal request mapping" in content
        assert '"Record this as a team decision."' in content
        assert '"Save this handoff for the next agent."' in content
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
        assert "mcp__jurati__record" in data["permissions"]["allow"]
        assert "mcp__jurati__expire" in data["permissions"]["allow"]
        assert len(data["permissions"]["allow"]) == 13

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
        from jurati.cli import _mcp_server_name

        name_a = _mcp_server_name("https://github.com/org/repo-a.git")
        name_b = _mcp_server_name("https://github.com/org/repo-b.git")
        assert name_a != name_b
        assert name_a.startswith("jurati-")
        assert name_b.startswith("jurati-")

    def test_same_remote_gets_same_name(self) -> None:
        from jurati.cli import _mcp_server_name

        name_1 = _mcp_server_name("https://github.com/org/kb.git")
        name_2 = _mcp_server_name("https://github.com/org/kb.git")
        assert name_1 == name_2

    def test_doctor_discovers_hash_based_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from jurati.cli import _mcp_server_name

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
        assert len(data["permissions"]["allow"]) == 13


class TestSearchCommand:
    def test_search_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["search", "--help"])
        assert result.exit_code == 0
