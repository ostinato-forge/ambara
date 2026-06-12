# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Runtime and validation commands for the Ambara CLI facade."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from ambara.cli_install import (
    _install_claude_md,
    _mcp_config_payload,
    _write_project_mcp_config,
)
from ambara.cli_project_config import (
    _ambara_disabled,
    _project_active_ref_env,
    _read_project_team_config,
    _write_project_team_config,
)
from ambara.cli_setup import _validate_knowledge_repo
from ambara.cli_setup_diagnostics import (
    _discover_remote,
    _display_path,
    _print_doctor,
    _status_value,
)
from ambara.git.repo import repo_cache_path


def register_runtime_commands(main: click.Group) -> None:
    @main.command()
    @click.option(
        "--check",
        is_flag=True,
        help="Explain what serve would do and verify configuration without starting MCP.",
    )
    def serve(check: bool) -> None:
        """Start the Ambara MCP server over stdio."""
        if check:
            _serve_check()
            return

        from ambara.server import run_stdio

        run_stdio()

    @main.command()
    @click.argument("path", default=".", type=click.Path(exists=True))
    def validate(path: str) -> None:
        """Validate all knowledge entries in a directory."""
        root = Path(path)
        entry_count, errors = _validate_knowledge_repo(root)

        if errors:
            click.echo(f"Found {len(errors)} error(s) in {entry_count} entries:")
            for err in errors:
                click.echo(f"  - {err}")
            sys.exit(1)
        else:
            click.echo(f"All {entry_count} entries valid.")


def _serve_check() -> None:
    remote = _discover_remote() or ""
    cache_dir = os.environ.get("AMBARA_CACHE_DIR", os.path.expanduser("~/.cache/ambara"))
    client_slug = os.environ.get("AMBARA_CLIENT_SLUG", "claude-code")
    main_branch = os.environ.get("AMBARA_MAIN_BRANCH", "main")
    project_config = _read_project_team_config(Path.cwd())
    disabled = _ambara_disabled(project_config)

    if disabled:
        click.echo("Ambara serve preflight")
        click.echo("  state:           disabled")
        click.echo(f"  config path:     {_display_path(project_config.path)}")
        click.echo(f"  knowledge remote: {_status_value(remote)}")
        click.echo("")
        click.echo("When started, Ambara will:")
        click.echo("  1. skip knowledge repo clone, fetch, and indexing")
        click.echo("  2. report disabled status to MCP status/sync/startup/context calls")
        click.echo("  3. tell agents to proceed from local project context")
        click.echo("")
        click.echo(
            "Privacy boundary: no query logging, read receipts, absence signals, or telemetry."
        )
        return

    if not remote:
        raise click.ClickException(
            "AMBARA_KNOWLEDGE_REMOTE is required. Run `ambara mcp-config --remote <url>` "
            "to generate a client config."
        )

    click.echo("Ambara serve preflight")
    click.echo(f"  knowledge remote: {remote}")
    click.echo(f"  cache directory:  {repo_cache_path(remote, cache_dir)}")
    click.echo(f"  main branch:      {main_branch}")
    click.echo(f"  client slug:      {client_slug}")
    click.echo("")
    click.echo("When started, Ambara will:")
    click.echo("  1. clone or reuse the local cache for the knowledge repo")
    click.echo("  2. fetch the source-of-truth branch and active refs")
    click.echo("  3. build an in-memory index from markdown entries")
    click.echo("  4. answer MCP query/read/list/validate/sync calls from that index")
    click.echo("  5. write only when record/propose/expire is explicitly called")
    click.echo("")
    click.echo("Privacy boundary: no query logging, read receipts, absence signals, or telemetry.")


def _repair_project_config_then_print_doctor(
    *, check_startup: bool = False, team: bool = False, audit: bool = False
) -> bool:
    remote = _discover_remote()
    if not remote:
        raise click.ClickException(
            "Cannot repair project config without a knowledge repo remote. "
            "Run `ambara onboard --remote <url>` or set AMBARA_KNOWLEDGE_REMOTE."
        )

    project = Path.cwd()
    client_slug = os.environ.get("AMBARA_CLIENT_SLUG", "claude-code")

    click.echo("Project config repair")
    click.echo(f"  knowledge remote: {remote}")
    click.echo("")

    _install_claude_md(project, remote)
    _write_project_team_config(project, remote=remote)
    project_config = _read_project_team_config(project)
    if project_config.read_error:
        raise click.ClickException(f"Cannot read project team config: {project_config.read_error}")
    payload = _mcp_config_payload(
        remote,
        client_slug,
        "ambara",
        policy_env=_project_active_ref_env(project_config),
    )
    server_name = _write_project_mcp_config(project / ".mcp.json", payload)
    click.echo(f"Updated {project / '.mcp.json'} with MCP server {server_name!r}.")
    click.echo("")

    return _print_doctor(check_startup=check_startup, team=team, audit=audit)
