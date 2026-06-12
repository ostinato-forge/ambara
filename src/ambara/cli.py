# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""CLI entry point: ambara serve, ambara init, ambara validate."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from ambara import __version__
from ambara.cli_capture import register_capture_commands
from ambara.cli_client_smoke import register_client_smoke_command
from ambara.cli_file_adapter import (
    _compile_startup_cli_packet,
    register_file_adapter_commands,
)
from ambara.cli_hooks import register_hook_commands
from ambara.cli_html import register_html_command
from ambara.cli_import import register_import_commands
from ambara.cli_inspect import register_inspect_commands
from ambara.cli_install import (
    _install_claude_md,
    _mcp_config_payload,
    _write_project_mcp_config,
    register_install_claude_md_command,
)
from ambara.cli_local import register_local_commands
from ambara.cli_lookup import register_lookup_commands
from ambara.cli_mcp_config import register_mcp_config_command
from ambara.cli_posture import register_posture_command
from ambara.cli_project_config import (
    _ambara_disabled,
    _project_active_ref_env,
    _read_project_team_config,
    _write_project_team_config,
)
from ambara.cli_read_model import register_read_model_commands
from ambara.cli_scope import register_scope_commands
from ambara.cli_setup import _validate_knowledge_repo, register_setup_commands
from ambara.cli_setup_diagnostics import (
    _discover_remote,
    _display_path,
    _print_doctor,
    _status_value,
    register_doctor_command,
)
from ambara.cli_sources import register_source_commands
from ambara.cli_status import register_status_command
from ambara.cli_value import (
    _build_value_rollup,
    _value_ledger_path,
    _write_startup_value_event,
)
from ambara.git.repo import repo_cache_path


@click.group(name="ambara")
@click.version_option(__version__)
def main() -> None:
    """Ambara: shared agent context for people and AI coding agents."""


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


register_import_commands(main)


register_setup_commands(main)


register_scope_commands(main)


register_lookup_commands(main)


register_capture_commands(main)


register_file_adapter_commands(main)


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


register_client_smoke_command(
    main,
    write_project_team_config=_write_project_team_config,
    write_startup_value_event=_write_startup_value_event,
    build_value_rollup=_build_value_rollup,
    value_ledger_path=_value_ledger_path,
)
register_doctor_command(
    main,
    repair_project_config=_repair_project_config_then_print_doctor,
)
register_status_command(main, compile_startup=_compile_startup_cli_packet)
register_posture_command(main)
register_install_claude_md_command(main)
register_hook_commands(main)
register_mcp_config_command(main)
register_source_commands(main)
register_read_model_commands(main)
register_local_commands(main)
register_html_command(main)
register_inspect_commands(main)
