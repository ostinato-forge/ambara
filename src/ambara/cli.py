# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""CLI entry point: ambara serve, ambara init, ambara validate."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click

from ambara import __version__
from ambara.cli_capture import register_capture_commands
from ambara.cli_client_smoke import register_client_smoke_command
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
from ambara.cli_sources import _source_token_from_env, register_source_commands
from ambara.cli_startup_sources import StartupSourceRefreshError, startup_source_context
from ambara.cli_status import StartupCliResult, register_status_command
from ambara.cli_value import (
    _build_value_rollup,
    _value_ledger_path,
    _write_startup_value_event,
)
from ambara.core.schema import EntryType, Sensitivity
from ambara.core.scope_policy import filter_index
from ambara.git.repo import ensure_repo, fetch_all, load_index_from_repo, repo_cache_path


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


def _compile_startup_cli_packet(
    *,
    repo: str | None,
    goal: str | None,
    max_entries: int,
    include_muted: bool,
    record_value: bool,
) -> StartupCliResult:
    from ambara.core.scoring import build_inverted_index
    from ambara.git.config import load_config_from_env
    from ambara.server_read import _build_disabled_startup_v2_payload, build_startup_v2_payload
    from ambara.server_state import SyncHealth

    project_config = _read_project_team_config(Path.cwd())
    if project_config.read_error:
        raise click.ClickException(f"Cannot read project team config: {project_config.read_error}")
    if project_config.enabled is False:
        return StartupCliResult(packet=_build_disabled_startup_v2_payload())

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
        if not include_muted:
            index = filter_index(index, config.muted_scopes)
    except Exception as exc:
        raise click.ClickException(f"Failed to load knowledge repo: {exc}") from exc

    now = datetime.now(UTC)
    sync_health = SyncHealth(last_success=now)
    try:
        source_context = startup_source_context(
            config.source_inputs,
            repo=repo,
            goal=goal,
            now=now,
            sync_health=sync_health,
            token=_source_token_from_env(),
        )
    except StartupSourceRefreshError as exc:
        raise click.ClickException(str(exc)) from exc

    visible_entries = [
        e for e in index.entries.values() if e.frontmatter.sensitivity != Sensitivity.RESTRICTED
    ]
    bm25 = build_inverted_index(visible_entries)

    packet = build_startup_v2_payload(
        index,
        now=now,
        sync_health=source_context.sync_health,
        freshness_warning_seconds=config.context_freshness_warning_seconds,
        stale_after_seconds=config.context_stale_after_seconds,
        repo=repo,
        goal=goal,
        max_entries=max_entries,
        coordination=source_context.coordination,
        prebuilt_index=bm25,
        budget_mode=config.context_budget_mode,
        source_health=source_context.source_health,
        source_omissions=source_context.source_omissions,
    )

    ledger_path: Path | None = None
    if config.value_ledger_enabled:
        ledger_path = _value_ledger_path(config.cache_dir, config.value_ledger_path)
        if record_value:
            _write_startup_value_event(
                packet,
                ledger_path=ledger_path,
                budget_mode=config.context_budget_mode,
                now=now,
            )
            rollup = _build_value_rollup(ledger_path, config, now=now)
            if rollup:
                packet["value_rollup"] = rollup

    return StartupCliResult(
        packet=packet,
        value_ledger_path=ledger_path,
        source_report=source_context.source_report,
    )


@main.command("startup")
@click.option("--repo", default=None, help="Project slug for filtering entries.")
@click.option("--goal", default=None, help="User request for relevance ranking.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "md", "markdown"]),
    default="json",
    help="Output format (default: json).",
)
@click.option(
    "--output", "-o", "output_path", default=None, help="Write to file instead of stdout."
)
@click.option("--max-entries", default=5, help="Maximum entries to include.")
@click.option(
    "--include-muted",
    is_flag=True,
    help="Include locally muted scopes for historical/manual lookup.",
)
def startup_cmd(
    repo: str | None,
    goal: str | None,
    fmt: str,
    output_path: str | None,
    max_entries: int,
    include_muted: bool,
) -> None:
    """Compile project context to a file or stdout. No MCP server needed."""
    from ambara.cli_render import render_startup_markdown

    fmt = "md" if fmt == "markdown" else fmt
    result = _compile_startup_cli_packet(
        repo=repo,
        goal=goal,
        max_entries=max_entries,
        include_muted=include_muted,
        record_value=True,
    )
    output = (
        render_startup_markdown(result.packet)
        if fmt == "md"
        else json.dumps(
            result.packet,
            indent=2,
        )
    )

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(output)
        click.echo(f"Wrote {fmt} context to {output_path}", err=True)
    else:
        click.echo(output)


def _title_from_message(message: str, *, max_len: int = 80) -> str:
    stripped = message.strip()
    for separator in (".", "!", "?"):
        idx = stripped.find(separator)
        if 0 <= idx < max_len:
            return stripped[: idx + 1].strip()
    if len(stripped) <= max_len:
        return stripped
    return stripped[:max_len].rsplit(" ", 1)[0].strip() + "..."


@main.command("save")
@click.argument("message")
@click.option("--projects", default=None, help="Comma-separated project slugs.")
@click.option("--tags", default=None, help="Comma-separated tags.")
def save_cmd(message: str, projects: str | None, tags: str | None) -> None:
    """Save a handoff in one command. Shorthand for record --type active."""
    from ambara.cli_write import check_content_policy, do_active_write, gen_entry_id
    from ambara.core.changes import plan_record
    from ambara.git.config import load_config_from_env

    try:
        config = load_config_from_env()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if not config.active_refs_enabled:
        raise click.ClickException("Handoffs are not enabled. Run `ambara onboard` to set up.")

    try:
        repo_path = ensure_repo(config.remote_url, config.cache_dir)
        fetch_all(
            repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
    except Exception as exc:
        raise click.ClickException(f"Failed to load knowledge repo: {exc}") from exc

    title = _title_from_message(message)
    project_list = [p.strip() for p in projects.split(",") if p.strip()] if projects else []
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    now = datetime.now(UTC)

    check_content_policy(
        source="record",
        title=title,
        content=message,
        entry_type=EntryType.ACTIVE,
        projects=project_list,
        tags=tag_list,
    )

    try:
        intent = plan_record(
            EntryType.ACTIVE,
            title,
            message,
            entry_id=gen_entry_id(),
            projects=project_list,
            tags=tag_list,
            now=now,
            expires_at=now + timedelta(hours=config.active_ref_ttl_hours),
            branch_prefix=config.branch_prefix,
            active_ref_prefix=config.active_ref_prefix,
            client=config.client_slug,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        do_active_write(repo_path, intent, config.main_branch)
        click.echo(f"Saved: {title}")
    except Exception as exc:
        raise click.ClickException(f"Write failed: {exc}") from exc


@main.command("record")
@click.option(
    "--type",
    "entry_type",
    required=True,
    type=click.Choice(["active", "project"]),
    help="Entry type (active=L0 short-lived, project=L1 lightweight review branch).",
)
@click.option("--title", required=True, help="Entry title.")
@click.option("--content", required=True, help="Entry body text.")
@click.option("--projects", default=None, help="Comma-separated project slugs.")
@click.option("--tags", default=None, help="Comma-separated tags.")
def record_cmd(
    entry_type: str,
    title: str,
    content: str,
    projects: str | None,
    tags: str | None,
) -> None:
    """Record a handoff, status update, or active context. No MCP server needed."""
    from ambara.cli_write import (
        check_content_policy,
        do_active_write,
        do_branch_write,
        gen_entry_id,
    )
    from ambara.core.changes import plan_record
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
    except Exception as exc:
        raise click.ClickException(f"Failed to load knowledge repo: {exc}") from exc

    parsed_type = EntryType(entry_type)
    project_list = [p.strip() for p in projects.split(",")] if projects else []
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    now = datetime.now(UTC)
    eid = gen_entry_id()

    if parsed_type == EntryType.ACTIVE and not config.active_refs_enabled:
        raise click.ClickException(
            "Active context is disabled by repo policy. "
            "Set AMBARA_ACTIVE_REFS_ENABLED=true to opt in."
        )

    check_content_policy(
        source="record",
        title=title,
        content=content,
        entry_type=parsed_type,
        projects=project_list,
        tags=tag_list,
    )

    exp = None
    if parsed_type == EntryType.ACTIVE:
        exp = now + timedelta(hours=config.active_ref_ttl_hours)

    try:
        intent = plan_record(
            parsed_type,
            title,
            content,
            entry_id=eid,
            projects=project_list,
            tags=tag_list,
            now=now,
            expires_at=exp,
            branch_prefix=config.branch_prefix,
            active_ref_prefix=config.active_ref_prefix,
            client=config.client_slug,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        if intent.write_mode == "active_ref":
            sha = do_active_write(repo_path, intent, config.main_branch)
            click.echo(f"Recorded active context: {title}")
        else:
            sha = do_branch_write(repo_path, intent, config.main_branch)
            click.echo(f"Recorded on branch {intent.branch} ({sha[:8]})")
            click.echo("No review request was created. Open one if you want to merge this entry.")
    except Exception as exc:
        raise click.ClickException(f"Write failed: {exc}") from exc


@main.command("propose")
@click.option(
    "--type",
    "entry_type",
    required=True,
    type=click.Choice(["decision", "workflow", "principle"]),
    help="Entry type for team review.",
)
@click.option("--title", required=True, help="Entry title.")
@click.option("--content", required=True, help="Entry body text.")
@click.option("--projects", default=None, help="Comma-separated project slugs.")
@click.option("--tags", default=None, help="Comma-separated tags.")
def propose_cmd(
    entry_type: str,
    title: str,
    content: str,
    projects: str | None,
    tags: str | None,
) -> None:
    """Propose a project decision or workflow for review. No MCP server needed."""
    from ambara.cli_write import check_content_policy, do_branch_write, gen_entry_id
    from ambara.core.changes import plan_propose
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
    except Exception as exc:
        raise click.ClickException(f"Failed to load knowledge repo: {exc}") from exc

    parsed_type = EntryType(entry_type)
    project_list = [p.strip() for p in projects.split(",")] if projects else []
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    now = datetime.now(UTC)
    eid = gen_entry_id()

    check_content_policy(
        source="propose",
        title=title,
        content=content,
        entry_type=parsed_type,
        projects=project_list,
        tags=tag_list,
    )

    try:
        intent = plan_propose(
            parsed_type,
            title,
            content,
            entry_id=eid,
            projects=project_list,
            tags=tag_list,
            now=now,
            branch_prefix=config.branch_prefix,
            client=config.client_slug,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        sha = do_branch_write(repo_path, intent, config.main_branch)
        click.echo(f"Proposed on branch {intent.branch} ({sha[:8]})")
        click.echo("No review request was created. Open one if you want to merge this entry.")
    except Exception as exc:
        raise click.ClickException(f"Write failed: {exc}") from exc


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
