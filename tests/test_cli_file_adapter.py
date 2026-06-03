"""Tests for CLI file-adapter commands: startup, record, propose, query, read."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from ambara.cli import main
from ambara.core.index import Index
from ambara.core.schema import (
    Entry,
    EntryStatus,
    EntryType,
    EscalationLevel,
    Frontmatter,
    Sensitivity,
)


def _make_entry(
    *,
    entry_id: str = "test-entry",
    title: str = "Test entry",
    entry_type: EntryType = EntryType.PROJECT,
    level: EscalationLevel = EscalationLevel.L1,
    status: EntryStatus = EntryStatus.ACTIVE,
    body: str = "Test body content.",
    projects: list[str] | None = None,
    tags: list[str] | None = None,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
) -> Entry:
    path_prefix = {
        EntryType.ACTIVE: "active",
        EntryType.PROJECT: "projects",
        EntryType.DECISION: "decisions",
        EntryType.WORKFLOW: "workflows",
        EntryType.PRINCIPLE: "principles",
    }
    return Entry(
        path=f"{path_prefix[entry_type]}/{entry_id}.md",
        frontmatter=Frontmatter(
            id=entry_id,
            title=title,
            type=entry_type,
            level=level,
            status=status,
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            updated_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            tags=tags or [],
            projects=projects or [],
            sensitivity=sensitivity,
        ),
        body=body,
    )


def _mock_index(*entries: Entry) -> Index:
    index = Index()
    for e in entries:
        index.add(e)
    return index


ENV = {
    "AMBARA_KNOWLEDGE_REMOTE": "https://example.com/kb.git",
    "AMBARA_CACHE_DIR": "/tmp/test-cache",
    "AMBARA_ACTIVE_REFS_ENABLED": "true",
}


class TestStartupCommand:
    def test_startup_json_output(self) -> None:
        index = _mock_index(
            _make_entry(entry_id="proj-status", title="Project status", body="All good."),
        )
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli.load_index_from_repo", return_value=index),
        ):
            result = runner.invoke(main, ["startup"], env=ENV)
        assert result.exit_code == 0, result.output
        assert '"action"' in result.output

    def test_startup_markdown_output(self) -> None:
        index = _mock_index(
            _make_entry(entry_id="proj-status", title="Project status"),
        )
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli.load_index_from_repo", return_value=index),
        ):
            result = runner.invoke(main, ["startup", "--format", "md"], env=ENV)
        assert result.exit_code == 0, result.output
        assert "# Team Context" in result.output

    def test_startup_writes_to_file(self, tmp_path: Path) -> None:
        index = _mock_index(
            _make_entry(entry_id="proj-status", title="Project status"),
        )
        output_file = tmp_path / "context.md"
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli.load_index_from_repo", return_value=index),
        ):
            result = runner.invoke(
                main,
                ["startup", "--format", "md", "--output", str(output_file)],
                env=ENV,
            )
        assert result.exit_code == 0, result.output
        assert output_file.exists()
        assert "# Team Context" in output_file.read_text()

    def test_startup_fails_without_remote(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["startup"], env={})
        assert result.exit_code != 0

    def test_startup_uses_project_config_remote(self, tmp_path: Path, monkeypatch) -> None:
        index = _mock_index(
            _make_entry(entry_id="proj-status", title="Project status from config"),
        )
        project = tmp_path / "project"
        project.mkdir()
        config = project / ".ambara" / "config.yaml"
        config.parent.mkdir()
        config.write_text(
            "\n".join(
                [
                    "schema_version: 1",
                    "knowledge_remote: https://example.com/kb.git",
                    "active_refs_enabled: true",
                    "",
                ]
            )
        )
        monkeypatch.chdir(project)
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo") as ensure,
            patch("ambara.cli.fetch_all") as fetch,
            patch("ambara.cli.load_index_from_repo", return_value=index),
        ):
            result = runner.invoke(main, ["startup", "--goal", "project status"], env={})
        assert result.exit_code == 0, result.output
        assert '"availability": "fresh"' in result.output
        assert ensure.call_args.args[0] == "https://example.com/kb.git"
        assert fetch.call_args.kwargs["active_refs_enabled"] is True


class TestQueryCommand:
    def test_query_returns_matching_entries(self) -> None:
        index = _mock_index(
            _make_entry(
                entry_id="task-loops",
                title="Task loops status",
                body="Loop constructs and until keywords.",
            ),
            _make_entry(
                entry_id="task-review",
                title="Task review lab",
                body="Review lab scaffold.",
            ),
        )
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli.load_index_from_repo", return_value=index),
        ):
            result = runner.invoke(main, ["query", "task loops"], env=ENV)
        assert result.exit_code == 0, result.output
        assert "Task loops status" in result.output

    def test_query_no_results(self) -> None:
        index = _mock_index(
            _make_entry(entry_id="unrelated", title="Unrelated entry", body="Nothing here."),
        )
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli.load_index_from_repo", return_value=index),
        ):
            result = runner.invoke(main, ["query", "xyznonexistent"], env=ENV)
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_query_excludes_restricted(self) -> None:
        index = _mock_index(
            _make_entry(
                entry_id="secret-entry",
                title="Secret restricted",
                body="Classified content.",
                sensitivity=Sensitivity.RESTRICTED,
            ),
        )
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli.load_index_from_repo", return_value=index),
        ):
            result = runner.invoke(main, ["query", "secret restricted"], env=ENV)
        assert "No results" in result.output


class TestReadCommand:
    def test_read_existing_entry(self) -> None:
        index = _mock_index(
            _make_entry(
                entry_id="task-loops",
                title="Task loops status",
                body="Loop constructs work.",
                projects=["AU0035l"],
                tags=["loops"],
            ),
        )
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli.load_index_from_repo", return_value=index),
        ):
            result = runner.invoke(main, ["read", "task-loops"], env=ENV)
        assert result.exit_code == 0, result.output
        assert "Task loops status" in result.output
        assert "Loop constructs work." in result.output
        assert "AU0035l" in result.output

    def test_read_missing_entry(self) -> None:
        index = _mock_index()
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli.load_index_from_repo", return_value=index),
        ):
            result = runner.invoke(main, ["read", "nonexistent"], env=ENV)
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestRecordCommand:
    def test_record_active_entry(self) -> None:
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli_write.create_branch"),
            patch("ambara.cli_write.materialize_write", return_value="abc123" + "0" * 34),
            patch("ambara.cli_write.push_active_ref"),
            patch("ambara.cli_write.cleanup_branch"),
        ):
            result = runner.invoke(
                main,
                ["record", "--type", "active", "--title", "Test handoff", "--content", "Details"],
                env=ENV,
            )
        assert result.exit_code == 0, result.output
        assert "Recorded active context" in result.output

    def test_record_project_entry(self) -> None:
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli_write.create_branch"),
            patch("ambara.cli_write.materialize_write", return_value="abc123" + "0" * 34),
            patch("ambara.cli_write.push_branch"),
            patch("ambara.cli_write.cleanup_branch"),
        ):
            result = runner.invoke(
                main,
                ["record", "--type", "project", "--title", "Status update", "--content", "Update"],
                env=ENV,
            )
        assert result.exit_code == 0, result.output
        assert "Recorded on branch" in result.output

    def test_record_blocks_secrets(self) -> None:
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
        ):
            result = runner.invoke(
                main,
                [
                    "record",
                    "--type",
                    "active",
                    "--title",
                    "Handoff with secret",
                    "--content",
                    "Token: ghp_abcdefghijklmnopqrstuvwxyz1234567890",
                ],
                env=ENV,
            )
        assert result.exit_code != 0
        assert "blocked by policy" in result.output.lower()

    def test_record_active_disabled_fails(self) -> None:
        runner = CliRunner()
        env_disabled = {**ENV, "AMBARA_ACTIVE_REFS_ENABLED": "false"}
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
        ):
            result = runner.invoke(
                main,
                ["record", "--type", "active", "--title", "Handoff", "--content", "Content"],
                env=env_disabled,
            )
        assert result.exit_code != 0
        assert "disabled" in result.output.lower()

    def test_record_with_projects_and_tags(self) -> None:
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli_write.create_branch"),
            patch("ambara.cli_write.materialize_write", return_value="abc123" + "0" * 34),
            patch("ambara.cli_write.push_active_ref"),
            patch("ambara.cli_write.cleanup_branch"),
        ):
            result = runner.invoke(
                main,
                [
                    "record",
                    "--type",
                    "active",
                    "--title",
                    "Tagged handoff",
                    "--content",
                    "Content with tags",
                    "--projects",
                    "AU0035l,AU0036l",
                    "--tags",
                    "spike,test",
                ],
                env=ENV,
            )
        assert result.exit_code == 0, result.output


class TestProposeCommand:
    def test_propose_decision(self) -> None:
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli_write.create_branch"),
            patch("ambara.cli_write.materialize_write", return_value="abc123" + "0" * 34),
            patch("ambara.cli_write.push_branch"),
            patch("ambara.cli_write.cleanup_branch"),
        ):
            result = runner.invoke(
                main,
                [
                    "propose",
                    "--type",
                    "decision",
                    "--title",
                    "Use file adapter",
                    "--content",
                    "We decided to use file-based context injection.",
                ],
                env=ENV,
            )
        assert result.exit_code == 0, result.output
        assert "Proposed on branch" in result.output

    def test_propose_workflow(self) -> None:
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
            patch("ambara.cli_write.create_branch"),
            patch("ambara.cli_write.materialize_write", return_value="abc123" + "0" * 34),
            patch("ambara.cli_write.push_branch"),
            patch("ambara.cli_write.cleanup_branch"),
        ):
            result = runner.invoke(
                main,
                [
                    "propose",
                    "--type",
                    "workflow",
                    "--title",
                    "Review process",
                    "--content",
                    "Each section follows this order.",
                ],
                env=ENV,
            )
        assert result.exit_code == 0, result.output

    def test_propose_blocks_secrets(self) -> None:
        runner = CliRunner()
        with (
            patch("ambara.cli.ensure_repo", return_value="/repo"),
            patch("ambara.cli.fetch_all"),
        ):
            result = runner.invoke(
                main,
                [
                    "propose",
                    "--type",
                    "decision",
                    "--title",
                    "Secret decision",
                    "--content",
                    "password=SuperSecret123456",
                ],
                env=ENV,
            )
        assert result.exit_code != 0
        assert "blocked by policy" in result.output.lower()

    def test_propose_fails_without_remote(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["propose", "--type", "decision", "--title", "Test", "--content", "Test"],
            env={},
        )
        assert result.exit_code != 0
