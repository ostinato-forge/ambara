# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Read-side knowledge lookup commands for the CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import click

from ambara.cli.project_config import _read_project_team_config
from ambara.core.schema import EntryType
from ambara.core.scope_policy import filter_index
from ambara.git.repo import ensure_repo, fetch_all, load_index_from_repo


def _format_relative_time(dt: datetime, now: datetime) -> str:
    seconds = max(0, int((now - dt).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def register_lookup_commands(main: click.Group) -> None:
    @main.command("show")
    @click.option(
        "--type",
        "entry_type",
        type=click.Choice(["active", "project", "decision", "workflow", "principle"]),
        default=None,
        help="Filter by entry type.",
    )
    @click.option("--limit", default=20, show_default=True, help="Maximum entries to show.")
    @click.option("--include-muted", is_flag=True, help="Include locally muted scopes.")
    def show_cmd(entry_type: str | None, limit: int, include_muted: bool) -> None:
        """List recent entries in the knowledge repo."""
        from ambara.git.config import load_config_from_env

        project_config = _read_project_team_config(Path.cwd())
        if project_config.read_error:
            raise click.ClickException(
                f"Cannot read project team config: {project_config.read_error}"
            )
        if project_config.enabled is False:
            click.echo("Ambara is disabled for this project.")
            return

        try:
            config = load_config_from_env()
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc

        try:
            repo_path = ensure_repo(config.remote_url, config.cache_dir)
            fetch_all(
                repo_path,
                config.main_branch,
                config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
            index = load_index_from_repo(
                repo_path,
                config.main_branch,
                config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
        except Exception as exc:
            raise click.ClickException(f"Failed to load knowledge repo: {exc}") from exc

        if not include_muted:
            index = filter_index(index, config.muted_scopes)

        now = datetime.now(UTC)
        parsed_type = EntryType(entry_type) if entry_type else None
        entries = index.list_entries(now=now, entry_type=parsed_type)[:limit]

        if not entries:
            click.echo("No entries found.")
            return

        grouped: dict[str, list[tuple[str, str]]] = {}
        for entry in entries:
            type_name = entry.frontmatter.type.value.capitalize()
            when = _format_relative_time(
                entry.frontmatter.updated_at or entry.frontmatter.created_at,
                now,
            )
            grouped.setdefault(type_name, []).append((entry.frontmatter.title, when))

        for type_name, items in grouped.items():
            click.echo(f"{type_name}:")
            for title, when in items:
                click.echo(f"  {title:<60s} {when}")
            click.echo("")

    @main.command("query")
    @click.argument("topic")
    @click.option("--max-results", default=5, help="Maximum results to return.")
    @click.option("--include-muted", is_flag=True, help="Include locally muted scopes.")
    def query_cmd(topic: str, max_results: int, include_muted: bool) -> None:
        """Search project context by topic. No MCP server needed."""
        from ambara.core.scoring import rank_entries
        from ambara.git.config import load_config_from_env

        try:
            config = load_config_from_env()
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc

        try:
            repo_path = ensure_repo(config.remote_url, config.cache_dir)
            fetch_all(
                repo_path,
                config.main_branch,
                config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
            index = load_index_from_repo(
                repo_path,
                config.main_branch,
                config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
        except Exception as exc:
            raise click.ClickException(f"Failed to load knowledge repo: {exc}") from exc

        if not include_muted:
            index = filter_index(index, config.muted_scopes)
        now = datetime.now(UTC)
        visible = index.list_entries(now=now)
        results = rank_entries(visible, topic, now=now, max_results=max_results)

        if not results:
            click.echo(f"No results for: {topic}")
            return

        for result in results:
            fm = result.entry.frontmatter
            click.echo(f"\n## {fm.title}")
            click.echo(f"**{fm.id}** ({fm.type}) — {fm.status}")
            if result.entry.body.strip():
                body_preview = result.entry.body.strip()[:300]
                if len(result.entry.body.strip()) > 300:
                    body_preview += "..."
                click.echo(body_preview)

    @main.command("read")
    @click.argument("entry_id")
    def read_cmd(entry_id: str) -> None:
        """Read a single knowledge entry by ID. No MCP server needed."""
        from ambara.git.config import load_config_from_env

        try:
            config = load_config_from_env()
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc

        try:
            repo_path = ensure_repo(config.remote_url, config.cache_dir)
            fetch_all(
                repo_path,
                config.main_branch,
                config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
            index = load_index_from_repo(
                repo_path,
                config.main_branch,
                config.active_ref_prefix,
                active_refs_enabled=config.active_refs_enabled,
            )
        except Exception as exc:
            raise click.ClickException(f"Failed to load knowledge repo: {exc}") from exc

        entry = index.entries.get(entry_id)
        if entry is None:
            raise click.ClickException(f"Entry not found: {entry_id}")

        fm = entry.frontmatter
        click.echo(f"# {fm.title}")
        click.echo(
            f"**ID:** {fm.id}  **Type:** {fm.type}  **Level:** {fm.level}  **Status:** {fm.status}"
        )
        click.echo(f"**Created:** {fm.created_at}  **Updated:** {fm.updated_at}")
        if fm.projects:
            click.echo(f"**Projects:** {', '.join(fm.projects)}")
        if fm.tags:
            click.echo(f"**Tags:** {', '.join(fm.tags)}")
        click.echo("")
        click.echo(entry.body.strip())

    @main.command("search")
    @click.argument("query")
    def search_cmd(query: str) -> None:
        """Search the knowledge repo from the command line."""
        click.echo(f"Searching for: {query}")
        click.echo("Note: requires AMBARA_KNOWLEDGE_REMOTE to be configured.")
