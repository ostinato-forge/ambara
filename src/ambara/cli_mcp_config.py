# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""MCP config CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import click

from ambara.cli_install import _mcp_config_payload, _write_project_mcp_config
from ambara.cli_project_config import (
    _project_active_ref_env,
    _read_project_team_config,
    _write_project_team_config,
)


def register_mcp_config_command(main: click.Group) -> None:
    @main.command("mcp-config")
    @click.option(
        "--remote",
        envvar="AMBARA_KNOWLEDGE_REMOTE",
        help="Git remote URL for the team knowledge repo.",
    )
    @click.option(
        "--client-slug",
        default="claude-code",
        show_default=True,
        help="Stable client name used for short-lived active refs.",
    )
    @click.option(
        "--command",
        "command_name",
        default="ambara",
        show_default=True,
        help="Command MCP clients should run.",
    )
    @click.option(
        "--write-project",
        is_flag=True,
        help="Write or update .mcp.json in the current project with a hash-based server name.",
    )
    @click.option(
        "--write-global",
        is_flag=True,
        help="Write or update ~/.claude.json with the MCP server config (user-level).",
    )
    def mcp_config(
        remote: str | None,
        client_slug: str,
        command_name: str,
        write_project: bool,
        write_global: bool,
    ) -> None:
        """Print or write a collision-resistant MCP config block."""
        project_config = _read_project_team_config(Path.cwd()) if write_project else None
        if not remote and project_config is not None:
            if project_config.read_error:
                raise click.ClickException(
                    f"Cannot read project team config: {project_config.read_error}"
                )
            remote = project_config.knowledge_remote
        if not remote:
            raise click.ClickException(
                "AMBARA_KNOWLEDGE_REMOTE is required. Pass --remote or set "
                "knowledge_remote in .ambara/config.yaml for --write-project."
            )

        if write_global:
            payload = _mcp_config_payload(remote, client_slug, command_name)
            target = Path.home() / ".claude.json"
            server_name = _write_project_mcp_config(target, payload)
            click.echo(f"Updated {target} with MCP server {server_name!r}.")
            return
        if write_project:
            _write_project_team_config(Path.cwd(), remote=remote)
            project_config = _read_project_team_config(Path.cwd())
            if project_config.read_error:
                raise click.ClickException(
                    f"Cannot read project team config: {project_config.read_error}"
                )
            payload = _mcp_config_payload(
                remote,
                client_slug,
                command_name,
                policy_env=_project_active_ref_env(project_config),
            )
            server_name = _write_project_mcp_config(Path(".mcp.json"), payload)
            click.echo(f"Updated .mcp.json with MCP server {server_name!r}.")
            click.echo("Next: run `ambara doctor` to check for duplicate server definitions.")
            return

        payload = _mcp_config_payload(remote, client_slug, command_name)
        click.echo(json.dumps(payload, indent=2))
