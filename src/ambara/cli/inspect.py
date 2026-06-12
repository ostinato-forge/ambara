# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""CLI commands for inspecting and explaining Ambara.

Registered onto the main CLI via ``register_inspect_commands`` so the command
bodies live outside the historical ``cli/__init__.py`` facade.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from ambara.cli.project_config import (
    _read_project_team_config,
    _set_project_enabled,
    _set_project_mcp_disabled,
    _update_project_entry_feedback,
)
from ambara.cli.value import (
    _print_value_explain,
    _print_value_window,
    _resolve_value_price_from_env,
    _value_ledger_path_from_env,
)
from ambara.core.context_accounting import summary_windows


def register_inspect_commands(main: click.Group) -> None:
    """Register inspection and explanation commands onto the main CLI."""

    @main.command()
    def explain() -> None:
        """Explain what Ambara does in plain language."""
        click.echo(
            "\n".join(
                [
                    "Ambara gives people and AI agents shared, reviewable context backed by git.",
                    "",
                    "It reads:",
                    (
                        "  - project status, decisions, workflows, and principles "
                        "from a knowledge repo"
                    ),
                    "  - local cached content when answering query/read/list requests",
                    "  - derived indexes built from Markdown, not Markdown treated as a database",
                    "",
                    "It writes only when explicitly asked:",
                    "  - record(active): short-lived current work on an active git ref",
                    (
                        "  - record(project): lightweight review branch; a review request "
                        "may be opened later"
                    ),
                    (
                        "  - propose(workflow/decision/principle): reviewed branch; a "
                        "review request may be opened later"
                    ),
                    "  - expire(id): active ref deletion or review branch, depending on entry type",
                    "",
                    "It does not:",
                    "  - log query text",
                    "  - track who read what",
                    "  - infer presence from editor, terminal, or agent activity",
                    "  - bypass normal git provenance or review",
                ]
            )
        )

    @main.command("disable")
    @click.option(
        "--repo-path",
        default=".",
        show_default=True,
        type=click.Path(file_okay=False, dir_okay=True),
        help="Project repo to disable Ambara in.",
    )
    def disable_cmd(repo_path: str) -> None:
        """Disable Ambara for a project without contacting the knowledge repo."""
        repo = Path(repo_path)
        config_path = _set_project_enabled(repo, enabled=False)
        updated_servers = _set_project_mcp_disabled(repo, disabled=True)
        click.echo(f"Disabled Ambara for {repo}.")
        click.echo(f"Updated {config_path}.")
        if updated_servers:
            click.echo(f"Marked {updated_servers} project MCP server(s) disabled.")
        else:
            click.echo("No project MCP server needed updating.")
        click.echo("Agents should treat this as intentional local-only work, not a sync failure.")

    @main.command("enable")
    @click.option(
        "--repo-path",
        default=".",
        show_default=True,
        type=click.Path(file_okay=False, dir_okay=True),
        help="Project repo to enable Ambara in.",
    )
    @click.option(
        "--remote",
        envvar="AMBARA_KNOWLEDGE_REMOTE",
        default=None,
        help="Knowledge repo remote to store when enabling a project with no saved remote.",
    )
    def enable_cmd(repo_path: str, remote: str | None) -> None:
        """Re-enable Ambara for a project."""
        repo = Path(repo_path)
        config = _read_project_team_config(repo)
        if config.read_error:
            raise click.ClickException(f"Cannot read project team config: {config.read_error}")

        saved_remote = remote or config.knowledge_remote
        if not saved_remote:
            raise click.ClickException(
                "Cannot enable Ambara without a knowledge repo remote. Pass --remote."
            )

        config_path = _set_project_enabled(repo, enabled=True, remote=saved_remote)
        updated_servers = _set_project_mcp_disabled(repo, disabled=False)
        click.echo(f"Enabled Ambara for {repo}.")
        click.echo(f"Updated {config_path}.")
        if updated_servers:
            click.echo(f"Marked {updated_servers} project MCP server(s) enabled.")
        else:
            click.echo("No project MCP server needed updating.")
        click.echo("Restart the MCP client if it was already running.")

    @main.command("feedback")
    @click.argument("entry_id")
    @click.argument(
        "signal",
        type=click.Choice(
            [
                "not-useful",
                "duplicate",
                "stale",
                "useful",
                "pin",
                "mute-for-repo",
                "mute-for-session",
            ]
        ),
    )
    @click.option(
        "--repo-path",
        default=".",
        show_default=True,
        type=click.Path(file_okay=False, dir_okay=True),
        help="Project repo to update.",
    )
    def feedback_cmd(entry_id: str, signal: str, repo_path: str) -> None:
        """Record local relevance feedback for an entry."""
        normalized = signal.replace("-", "_")
        config_path, count = _update_project_entry_feedback(
            Path(repo_path), entry_id=entry_id, signal=normalized
        )
        if normalized == "useful":
            click.echo(f"Cleared local Ambara feedback for {entry_id}.")
        else:
            click.echo(f"Recorded local Ambara feedback for {entry_id}: {normalized}.")
        click.echo(f"Updated {config_path}.")
        click.echo(f"  feedback entries: {count}")

    @main.command("value")
    @click.option("--json", "as_json", is_flag=True, help="Print machine-readable value summary.")
    @click.option(
        "--explain", is_flag=True, help="Explain baselines, confidence, and privacy limits."
    )
    @click.option(
        "--ledger",
        "ledger_path",
        default=None,
        type=click.Path(dir_okay=False),
        help="Read a specific local value ledger path.",
    )
    def value_cmd(as_json: bool, explain: bool, ledger_path: str | None) -> None:
        """Show local Ambara value and savings receipts."""
        path = Path(ledger_path) if ledger_path else _value_ledger_path_from_env()
        if explain:
            _print_value_explain(path)
            return

        try:
            price_per_million, currency = _resolve_value_price_from_env()
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        summary = summary_windows(path, price_per_million=price_per_million, currency=currency)
        if as_json:
            click.echo(json.dumps(summary, indent=2))
            return

        last_day = summary["current_repo_or_session"]
        seven = summary["last_7_days"]
        thirty = summary["last_30_days"]
        click.echo("Ambara value")
        click.echo(f"  ledger: {path}")
        _print_value_window("last session/day", last_day)
        _print_value_window("last 7 days", seven)
        _print_value_window("last 30 days", thirty)
        click.echo("")
        click.echo("Estimates are Ambara app-payload only, not total client/session billing.")
