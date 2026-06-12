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
from ambara.cli_client_smoke import register_client_smoke_command
from ambara.cli_hooks import register_hook_commands
from ambara.cli_html import register_html_command
from ambara.cli_inspect import register_inspect_commands
from ambara.cli_install import (
    _install_claude_md,
    _mcp_config_payload,
    _write_project_mcp_config,
    register_install_claude_md_command,
)
from ambara.cli_local import register_local_commands
from ambara.cli_mcp_config import register_mcp_config_command
from ambara.cli_posture import register_posture_command
from ambara.cli_project_config import (
    PROJECT_TEAM_CONFIG,
    _ambara_disabled,
    _project_active_ref_env,
    _read_project_team_config,
    _write_project_team_config,
)
from ambara.cli_read_model import register_read_model_commands
from ambara.cli_setup import _validate_knowledge_repo, register_setup_commands
from ambara.cli_setup_diagnostics import (
    _discover_remote,
    _display_path,
    _print_doctor,
    _print_muted_scope_summary,
    _status_value,
    register_doctor_command,
)
from ambara.cli_sources import _source_token_from_env, register_source_commands
from ambara.cli_startup_sources import StartupSourceRefreshError, startup_source_context
from ambara.cli_status import StartupCliResult, register_status_command
from ambara.cli_util import _dump_yaml_mapping, _load_yaml_mapping
from ambara.cli_value import (
    _build_value_rollup,
    _value_ledger_path,
    _write_startup_value_event,
)
from ambara.core.schema import EntryType, EscalationLevel, Sensitivity
from ambara.core.scope_policy import ScopeMutePolicy, filter_index
from ambara.git.import_context import materialize_context_import
from ambara.git.repo import ensure_repo, fetch_all, load_index_from_repo, repo_cache_path
from ambara.import_context import (
    ContextPackError,
    ImportPlan,
    default_import_branch,
    plan_context_import,
    plan_markdown_import,
)


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


@main.command("import-context")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Validate and summarize the import without writing files.",
)
@click.option(
    "--repo",
    "repo_path",
    default=".",
    show_default=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Path to the Ambara knowledge repo to import into.",
)
@click.option(
    "--branch",
    default=None,
    help="Review branch to create when writing the import.",
)
@click.option(
    "--base",
    default="HEAD",
    show_default=True,
    help="Base ref for the review branch when writing the import.",
)
@click.argument("bundle", type=click.Path(exists=True, dir_okay=False))
def import_context_cmd(
    bundle: str,
    dry_run: bool,
    repo_path: str,
    branch: str | None,
    base: str,
) -> None:
    """Plan an import from a context-pack tarball."""
    try:
        plan = plan_context_import(
            Path(bundle),
            knowledge_repo=Path(repo_path),
            now=datetime.now(UTC),
        )
    except ContextPackError as exc:
        raise click.ClickException(str(exc)) from exc

    _print_import_plan(plan, Path(repo_path), dry_run=dry_run)
    if plan.errors or plan.reject_count:
        sys.exit(1)

    if dry_run:
        return

    try:
        result = materialize_context_import(
            repo_path,
            plan,
            branch=branch or default_import_branch(plan),
            base=base,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("")
    click.echo("Wrote import review branch:")
    click.echo(f"  branch: {result.branch}")
    click.echo(f"  commit: {result.commit}")
    click.echo(f"  created: {len(result.created_paths)} entries")
    click.echo("")
    click.echo("Next: push this branch and open a review request to merge it.")


@main.command("import-docs")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Validate and summarize the import without writing files.",
)
@click.option(
    "--repo",
    "repo_path",
    default=".",
    show_default=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Path to the Ambara knowledge repo to import into.",
)
@click.option(
    "--branch",
    default=None,
    help="Review branch to create when writing the import.",
)
@click.option(
    "--base",
    default="HEAD",
    show_default=True,
    help="Base ref for the review branch when writing the import.",
)
@click.option(
    "--mode",
    type=click.Choice(["adr", "rfc", "docs", "obsidian"]),
    default="adr",
    show_default=True,
    help="How to map source Markdown into Ambara entries.",
)
@click.option("--project", "projects", multiple=True, help="Project tag to add.")
@click.option("--tag", "tags", multiple=True, help="Additional tag to add.")
@click.argument("source", nargs=-1, required=True, type=click.Path(exists=True))
def import_docs_cmd(
    source: tuple[str, ...],
    dry_run: bool,
    repo_path: str,
    branch: str | None,
    base: str,
    mode: str,
    projects: tuple[str, ...],
    tags: tuple[str, ...],
) -> None:
    """Plan an import from allowlisted Markdown files or directories."""
    try:
        plan = plan_markdown_import(
            tuple(Path(item) for item in source),
            knowledge_repo=Path(repo_path),
            now=datetime.now(UTC),
            mode=mode,
            projects=projects,
            tags=tags,
            source_root=Path.cwd(),
        )
    except ContextPackError as exc:
        raise click.ClickException(str(exc)) from exc

    _print_import_plan(plan, Path(repo_path), dry_run=dry_run)
    if plan.errors or plan.reject_count:
        sys.exit(1)

    if dry_run:
        return

    try:
        result = materialize_context_import(
            repo_path,
            plan,
            branch=branch or default_import_branch(plan),
            base=base,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("")
    click.echo("Wrote import review branch:")
    click.echo(f"  branch: {result.branch}")
    click.echo(f"  commit: {result.commit}")
    click.echo(f"  created: {len(result.created_paths)} entries")
    click.echo("")
    click.echo("Next: push this branch and open a review request to merge it.")


register_setup_commands(main)


@main.command("mute-scope")
@click.option(
    "--repo-path",
    default=".",
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Project repo to update.",
)
@click.option("--project", "projects", multiple=True, help="Project or project key to mute.")
@click.option("--repo", "repos", multiple=True, help="Source repo slug to mute.")
@click.option(
    "--source-input",
    "--signal-source",
    "source_inputs",
    multiple=True,
    help="Source input/provider to mute. --signal-source is a legacy alias.",
)
@click.option("--tag", "tags", multiple=True, help="Entry tag or source label to mute.")
def mute_scope_cmd(
    repo_path: str,
    projects: tuple[str, ...],
    repos: tuple[str, ...],
    source_inputs: tuple[str, ...],
    tags: tuple[str, ...],
) -> None:
    """Mute local project/repo/source-input/tag scopes without deleting knowledge."""
    policy = _scope_policy_from_cli(
        projects=projects,
        repos=repos,
        source_inputs=source_inputs,
        tags=tags,
    )
    if policy.is_empty():
        raise click.ClickException(
            "Pass at least one scope: --project, --repo, --source-input, or --tag."
        )

    repo = Path(repo_path)
    config_path, updated = _update_project_muted_scopes(repo, policy, remove=False)
    click.echo(f"Muted Ambara scope(s) for {repo}.")
    click.echo(f"Updated {config_path}.")
    _print_muted_scope_summary(updated, prefix="  ")


@main.command("unmute-scope")
@click.option(
    "--repo-path",
    default=".",
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Project repo to update.",
)
@click.option("--project", "projects", multiple=True, help="Project or project key to unmute.")
@click.option("--repo", "repos", multiple=True, help="Source repo slug to unmute.")
@click.option(
    "--source-input",
    "--signal-source",
    "source_inputs",
    multiple=True,
    help="Source input/provider to unmute. --signal-source is a legacy alias.",
)
@click.option("--tag", "tags", multiple=True, help="Entry tag or source label to unmute.")
def unmute_scope_cmd(
    repo_path: str,
    projects: tuple[str, ...],
    repos: tuple[str, ...],
    source_inputs: tuple[str, ...],
    tags: tuple[str, ...],
) -> None:
    """Unmute local project/repo/source-input/tag scopes."""
    policy = _scope_policy_from_cli(
        projects=projects,
        repos=repos,
        source_inputs=source_inputs,
        tags=tags,
    )
    if policy.is_empty():
        raise click.ClickException(
            "Pass at least one scope: --project, --repo, --source-input, or --tag."
        )

    repo = Path(repo_path)
    config_path, updated = _update_project_muted_scopes(repo, policy, remove=True)
    click.echo(f"Unmuted Ambara scope(s) for {repo}.")
    click.echo(f"Updated {config_path}.")
    _print_muted_scope_summary(updated, prefix="  ")


@main.command("retire-scope")
@click.option(
    "--repo-path",
    default=".",
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Knowledge repo checkout to update.",
)
@click.option("--project", "projects", multiple=True, help="Project or project key to retire.")
@click.option("--repo", "repos", multiple=True, help="Source repo slug to retire.")
@click.option("--tag", "tags", multiple=True, help="Entry tag to retire.")
@click.option("--branch", default=None, help="Review branch name to create.")
@click.option("--dry-run", is_flag=True, help="Print matching entries without writing.")
def retire_scope_cmd(
    repo_path: str,
    projects: tuple[str, ...],
    repos: tuple[str, ...],
    tags: tuple[str, ...],
    branch: str | None,
    dry_run: bool,
) -> None:
    """Retire matching knowledge on a review branch without rewriting history."""
    from ambara.git.lifecycle import (
        collect_retire_scope_matches,
        default_retire_scope_branch,
        materialize_retire_scope,
    )

    policy = _scope_policy_from_cli(projects=projects, repos=repos, tags=tags)
    if policy.is_empty():
        raise click.ClickException("Pass at least one scope: --project, --repo, or --tag.")

    now = datetime.now(UTC)
    repo = Path(repo_path)
    try:
        matches = collect_retire_scope_matches(str(repo), policy)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if not matches:
        click.echo("No active entries matched the requested scope.")
        return

    click.echo(f"Matched {len(matches)} entr{'y' if len(matches) == 1 else 'ies'} to retire:")
    for match in matches:
        click.echo(f"  - {match.entry_id} ({match.entry_type}) {match.path} -> {match.action}")

    if dry_run:
        click.echo("No files written.")
        return

    branch_name = branch or default_retire_scope_branch(now)
    try:
        result = materialize_retire_scope(
            str(repo),
            policy,
            branch=branch_name,
            now=now,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Retired scope on branch {result.branch} ({result.commit[:8]}).")
    click.echo(f"Lifecycle report: {result.report_path}")
    click.echo(
        "No review request was created. Open one if you want to merge this lifecycle cleanup."
    )


@main.command("clear")
@click.option(
    "--repo-path",
    default=".",
    show_default=True,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Knowledge repo checkout to update.",
)
@click.option(
    "--all",
    "all_entries",
    is_flag=True,
    help="Clear all current entries; restricted entries require --include-restricted.",
)
@click.option(
    "--type",
    "entry_types",
    multiple=True,
    type=click.Choice([str(value) for value in EntryType]),
    help="Entry type to clear.",
)
@click.option(
    "--level",
    "levels",
    multiple=True,
    type=click.Choice([str(value) for value in EscalationLevel]),
    help="Escalation level to clear.",
)
@click.option("--project", "projects", multiple=True, help="Project or project key to clear.")
@click.option("--repo", "repos", multiple=True, help="Source repo slug to clear.")
@click.option("--tag", "tags", multiple=True, help="Entry tag to clear.")
@click.option(
    "--include-restricted",
    is_flag=True,
    help="Include restricted entries in the reviewed cleanup branch.",
)
@click.option("--branch", default=None, help="Review branch name to create.")
@click.option("--dry-run", is_flag=True, help="Print matching entries without writing.")
def clear_cmd(
    repo_path: str,
    all_entries: bool,
    entry_types: tuple[str, ...],
    levels: tuple[str, ...],
    projects: tuple[str, ...],
    repos: tuple[str, ...],
    tags: tuple[str, ...],
    include_restricted: bool,
    branch: str | None,
    dry_run: bool,
) -> None:
    """Bulk-clear current context on a review branch without deleting history."""
    from ambara.git.lifecycle import (
        ClearEntriesFilter,
        collect_clear_entries_matches,
        default_clear_entries_branch,
        materialize_clear_entries,
    )

    filters = ClearEntriesFilter(
        entry_types=tuple(EntryType(value) for value in entry_types),
        levels=tuple(EscalationLevel(value) for value in levels),
        projects=projects,
        repos=repos,
        tags=tags,
        include_restricted=include_restricted,
    )
    if all_entries and filters.has_selectors():
        raise click.ClickException("Use --all by itself, or omit --all and pass filters.")
    if not all_entries and not filters.has_selectors():
        raise click.ClickException(
            "Pass --all or at least one filter: --type, --level, --project, --repo, or --tag."
        )

    now = datetime.now(UTC)
    repo = Path(repo_path)
    try:
        matches = collect_clear_entries_matches(str(repo), filters)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if not matches:
        click.echo("No current entries matched the clear filters.")
        return

    click.echo(f"Matched {len(matches)} entr{'y' if len(matches) == 1 else 'ies'} to clear:")
    for match in matches:
        click.echo(
            f"  - {match.entry_id} ({match.entry_type}/{match.level}, "
            f"{match.sensitivity}) {match.path} -> {match.action}"
        )

    if dry_run:
        click.echo("No files written.")
        return

    branch_name = branch or default_clear_entries_branch(now)
    try:
        result = materialize_clear_entries(
            str(repo),
            filters,
            branch=branch_name,
            now=now,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Cleared context on branch {result.branch} ({result.commit[:8]}).")
    click.echo(f"Lifecycle report: {result.report_path}")
    click.echo(
        "No review request was created. Open one if you want to merge this lifecycle cleanup."
    )


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
        raise click.ClickException(f"Cannot read project team config: {project_config.read_error}")
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


@main.command()
@click.option("--message", "-m", required=True, help="Commit message to process")
@click.option("--commit", default="unknown", help="Source commit SHA")
@click.option("--author", default="unknown", help="Source commit author email")
@click.option("--repo-slug", default=None, help="Source repo slug (defaults to current dir name)")
def capture(message: str, commit: str, author: str, repo_slug: str | None) -> None:
    """Process a commit message through the ambara capture pipeline."""
    from ambara.capture.extract import parse_commit_message
    from ambara.capture.pending import save_pending

    parsed = parse_commit_message(message)
    if parsed is None:
        click.echo("No ambara: prefix found — nothing to capture.")
        return

    if repo_slug is None:
        repo_slug = Path.cwd().name

    git_dir = _local_git_dir(Path.cwd())
    try:
        save_pending(str(git_dir), commit, message, author=author, repo_slug=repo_slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        f'[ambara] queued: "{parsed.title}" (type={parsed.entry_type}, level={parsed.level})'
    )


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


@main.command()
@click.argument("message")
@click.option("--expires", default="2h", help="Expiry duration (e.g. 2h, 30m)")
def active(message: str, expires: str) -> None:
    """Broadcast active status without a commit."""
    click.echo(f'[ambara] active: "{message}" (expires in {expires})')
    click.echo("Note: requires AMBARA_KNOWLEDGE_REMOTE to be configured.")


@main.command()
@click.option("--dry-run", is_flag=True, help="List pending captures without writing.")
def flush(dry_run: bool) -> None:
    """Flush pending captures from the offline queue."""
    from ambara.capture.pending import list_pending, remove_pending
    from ambara.capture.pipeline import run_capture
    from ambara.git.config import load_config_from_env

    git_dir = _local_git_dir(Path.cwd())

    pending = list_pending(str(git_dir))
    if not pending:
        click.echo("No pending captures.")
        return

    click.echo(f"Found {len(pending)} pending capture(s).")
    if dry_run:
        for item in pending:
            click.echo(f"  - {item['commit_sha'][:8]}: {item['message'][:60]}")
        return

    try:
        config = load_config_from_env()
        knowledge_repo_path = ensure_repo(config.remote_url, config.cache_dir)
        fetch_all(
            knowledge_repo_path,
            config.main_branch,
            config.active_ref_prefix,
            active_refs_enabled=config.active_refs_enabled,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    processed = 0
    skipped = 0
    failed = 0
    for item in pending:
        commit_sha = item["commit_sha"]
        message = item["message"]
        repo_slug = item.get("repo_slug") or Path.cwd().name
        author = item.get("author") or "unknown"
        try:
            outcome = run_capture(
                message=message,
                repo_slug=repo_slug,
                knowledge_repo_path=knowledge_repo_path,
                main_branch=config.main_branch,
                now=datetime.now(UTC),
                source_commit=commit_sha,
                source_author=author,
            )
        except Exception as exc:
            failed += 1
            click.echo(f"Failed {commit_sha[:8]}: {exc}", err=True)
            continue

        remove_pending(str(git_dir), commit_sha)
        if outcome is None:
            skipped += 1
            click.echo(f"Skipped {commit_sha[:8]}: already captured or not applicable.")
        else:
            processed += 1
            click.echo(f"Flushed {commit_sha[:8]}: {outcome.entry_id}")

    click.echo(f"Processed {processed}, skipped {skipped}, failed {failed}.")
    if failed:
        raise click.ClickException("one or more pending captures failed; markers were kept")


@main.command("search")
@click.argument("query")
def search_cmd(query: str) -> None:
    """Search the knowledge repo from the command line."""
    click.echo(f"Searching for: {query}")
    click.echo("Note: requires AMBARA_KNOWLEDGE_REMOTE to be configured.")


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


def _scope_policy_from_cli(
    *,
    projects: tuple[str, ...] = (),
    repos: tuple[str, ...] = (),
    source_inputs: tuple[str, ...] = (),
    signal_sources: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
) -> ScopeMutePolicy:
    return ScopeMutePolicy.from_raw(
        {
            "projects": list(projects),
            "repos": list(repos),
            "source_inputs": list(source_inputs),
            "signal_sources": list(signal_sources),
            "tags": list(tags),
        }
    )


def _update_project_muted_scopes(
    repo: Path, policy: ScopeMutePolicy, *, remove: bool
) -> tuple[Path, ScopeMutePolicy]:
    path = repo / PROJECT_TEAM_CONFIG
    if path.exists():
        try:
            data = _load_yaml_mapping(path)
        except ValueError as exc:
            raise click.ClickException(f"Cannot update {path}: {exc}") from exc
    else:
        data = {}

    current = ScopeMutePolicy.from_raw(data.get("muted_scopes"))
    updated = current.without(policy) if remove else current.merge(policy)
    data.setdefault("schema_version", 1)
    if updated.is_empty():
        data.pop("muted_scopes", None)
    else:
        data["muted_scopes"] = updated.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_yaml_mapping(data))
    return path, updated


def _local_git_dir(root: Path) -> Path:
    marker = root / ".git"
    if marker.is_dir():
        return marker
    if marker.is_file():
        content = marker.read_text().strip()
        prefix = "gitdir:"
        if content.startswith(prefix):
            git_dir = Path(content[len(prefix) :].strip())
            return git_dir if git_dir.is_absolute() else (root / git_dir).resolve()
    raise click.ClickException("not in a git repository")


def _print_import_plan(plan: ImportPlan, repo_path: Path, *, dry_run: bool) -> None:
    click.echo("Context import dry run" if dry_run else "Context import plan")
    click.echo(f"{plan.source_label}: {plan.bundle_name}")
    click.echo(f"Knowledge repo: {repo_path}")
    click.echo(
        f"Summary: {plan.create_count} create, {plan.skip_count} skip, {plan.reject_count} reject"
    )

    _print_import_section(plan, "create", "Create")
    _print_import_section(plan, "skip", "Skip")
    _print_import_section(plan, "reject", "Reject")

    if plan.errors:
        click.echo("")
        click.echo("Repository errors:")
        for error in plan.errors:
            click.echo(f"  - {error}")

    if dry_run:
        click.echo("")
        click.echo("No files written.")


def _print_import_section(plan: ImportPlan, action: str, title: str) -> None:
    items = [item for item in plan.actions if item.action == action]
    if not items:
        return

    click.echo("")
    click.echo(f"{title}:")
    for item in items:
        if item.destination_path:
            click.echo(
                f"  - {item.source_path} -> {item.destination_path} "
                f"({item.entry_type}, {item.level}): {item.reason}"
            )
        else:
            click.echo(f"  - {item.source_path}: {item.reason}")
        for error in item.errors:
            click.echo(f"      {error}")


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
