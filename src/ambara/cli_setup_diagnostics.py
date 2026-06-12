# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Setup, doctor, and status diagnostics shared by the CLI."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import click

from ambara.cli_install import (
    DEFAULT_MCP_SERVER_NAME,
    _ambara_expected_settings_allowlist,
    _has_startup_contract,
    _mcp_server_name,
)
from ambara.cli_project_config import (
    ProjectTeamConfig,
    _ambara_disabled,
    _read_project_team_config,
)
from ambara.core.index import Index
from ambara.core.schema import EntryStatus, EntryType, Sensitivity
from ambara.core.scope_policy import ScopeMutePolicy, scope_policy_summary
from ambara.core.validate import is_expired
from ambara.git.repo import ensure_repo, fetch_all, load_index_from_repo, repo_cache_path


@dataclass(frozen=True)
class StartupDiagnostics:
    claude_md_present: bool
    startup_contract_present: bool
    settings_present: bool
    read_only_allowed: bool
    write_tools_allowed: bool
    missing_read_only_tools: tuple[str, ...]


@dataclass(frozen=True)
class AuditDiagnostics:
    reviewable_git_context: bool
    signed_commits: bool
    append_only_events: bool
    complete_lifecycle_events: bool
    active_refs_audit_safe: bool
    authenticated_identity: bool
    host_protection_verified: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class MCPServerDefinition:
    name: str
    scope: str
    path: Path
    command: str | None
    args: tuple[str, ...]
    remote: str | None


@dataclass(frozen=True)
class MCPConfigDiagnostics:
    definitions: tuple[MCPServerDefinition, ...]
    read_errors: tuple[str, ...]
    collision_names: tuple[str, ...]


class ProjectConfigRepairer(Protocol):
    def __call__(
        self, *, check_startup: bool = False, team: bool = False, audit: bool = False
    ) -> bool: ...


def register_doctor_command(
    main: click.Group, *, repair_project_config: ProjectConfigRepairer
) -> None:
    @main.command()
    @click.option(
        "--strict",
        is_flag=True,
        help="Exit with an error when required setup is missing.",
    )
    @click.option(
        "--check-startup",
        is_flag=True,
        help="Fetch and index the configured knowledge repo to verify sync/context startup.",
    )
    @click.option(
        "--fix-project-config",
        is_flag=True,
        help="Repair safe project-local Ambara config before running diagnostics.",
    )
    @click.option(
        "--team",
        is_flag=True,
        help="Report repo-level team readiness from .ambara/config.yaml.",
    )
    @click.option(
        "--audit",
        is_flag=True,
        help="Report tamper-evidence/SOC2 audit-ledger readiness.",
    )
    def doctor(
        strict: bool,
        check_startup: bool,
        fix_project_config: bool,
        team: bool,
        audit: bool,
    ) -> None:
        """Explain Ambara setup and check whether this machine is ready."""
        if fix_project_config:
            ready = repair_project_config(
                check_startup=check_startup,
                team=team,
                audit=audit,
            )
        else:
            ready = _print_doctor(check_startup=check_startup, team=team, audit=audit)
        if strict and not ready:
            raise click.ClickException("Ambara is not ready; fix the missing items above.")


def _discover_remote() -> str | None:
    """Search for knowledge repo URL in standard locations."""
    import re as _re

    remote = os.environ.get("AMBARA_KNOWLEDGE_REMOTE", "").strip()
    if remote:
        return remote

    project_config = _read_project_team_config(Path.cwd())
    if project_config.knowledge_remote:
        return project_config.knowledge_remote

    claude_md = Path("CLAUDE.md")
    if claude_md.exists():
        text = claude_md.read_text()
        match = _re.search(r"Knowledge repo:\s*(\S+)", text)
        if match:
            return match.group(1)

    remote_file = Path(".ambara-remote")
    if remote_file.exists():
        return remote_file.read_text().strip()

    settings = Path(".claude") / "settings.json"
    if settings.exists():
        try:
            data = json.loads(settings.read_text())
            for server_cfg in data.get("mcpServers", {}).values():
                val: str | None = server_cfg.get("env", {}).get("AMBARA_KNOWLEDGE_REMOTE")
                if val:
                    return val
        except (json.JSONDecodeError, OSError):
            pass

    diagnostics = _mcp_config_diagnostics(Path.cwd(), Path.home())
    for scope in ("project", "user"):
        for definition in diagnostics.definitions:
            if definition.scope == scope and definition.remote:
                return definition.remote

    return None


def _print_doctor(*, check_startup: bool = False, team: bool = False, audit: bool = False) -> bool:
    project_config = _read_project_team_config(Path.cwd())
    disabled = _ambara_disabled(project_config)
    remote = _discover_remote() or ""
    cache_dir = os.environ.get("AMBARA_CACHE_DIR", os.path.expanduser("~/.cache/ambara"))
    client_slug = os.environ.get("AMBARA_CLIENT_SLUG", "claude-code")
    git_path = shutil.which("git")
    gh_path = shutil.which("gh")

    serve_ready = True if disabled else bool(remote and git_path)
    audit_ready: bool | None = None

    click.echo("Ambara doctor")
    click.echo("")
    click.echo("What Ambara does:")
    click.echo("  - gives humans and AI agents shared, reviewable context")
    click.echo("  - keeps reads local after sync")
    click.echo("  - uses git branches, refs, and review requests for explicit writes")
    click.echo("  - avoids telemetry, read receipts, and participation tracking")
    click.echo("")
    click.echo("Configuration:")
    click.echo(f"  Ambara disabled:         {_yes_no(disabled)}")
    click.echo(f"  AMBARA_KNOWLEDGE_REMOTE: {_status_value(remote)}")
    click.echo(f"  AMBARA_CACHE_DIR:        {cache_dir}")
    if remote:
        click.echo(f"  derived cache path:      {repo_cache_path(remote, cache_dir)}")
    click.echo(f"  AMBARA_CLIENT_SLUG:      {client_slug}")
    if disabled:
        click.echo("  disabled behavior:      local-only; no knowledge repo fetch")
    _print_muted_scope_summary(project_config.muted_scopes, prefix="  ")
    click.echo("")
    click.echo("Local tools:")
    click.echo(f"  git: {_found_value(git_path)}")
    click.echo(f"  gh:  {_found_value(gh_path)} (needed only for GitHub CLI fallback)")
    click.echo("")
    startup = _startup_diagnostics(Path.cwd(), remote=remote or None)
    _print_startup_diagnostics(startup, disabled=disabled)
    if not disabled and (not startup.startup_contract_present or not startup.read_only_allowed):
        serve_ready = False
    click.echo("")
    mcp_config = _mcp_config_diagnostics(Path.cwd(), Path.home())
    _print_mcp_config_diagnostics(mcp_config, remote=remote)
    blocking_collision_names = _blocking_mcp_collision_names(mcp_config.collision_names)
    if blocking_collision_names and not disabled:
        serve_ready = False
    click.echo("")

    if audit:
        audit_ready = _print_audit_diagnostics(_audit_diagnostics())
        click.echo("")

    if team:
        if disabled:
            team_ready = _print_disabled_team_readiness(project_config)
        else:
            team_ready = _print_team_readiness(
                Path.cwd(),
                remote=remote,
                startup=startup,
                mcp_config=mcp_config,
                gh_path=gh_path,
            )
        serve_ready = serve_ready and team_ready
        click.echo("")

    if check_startup:
        if disabled:
            startup_probe_ok = _print_disabled_startup_probe()
        else:
            startup_probe_ok = _print_startup_probe(remote, cache_dir)
        serve_ready = serve_ready and startup_probe_ok
        click.echo("")

    click.echo(f"Ready for `ambara serve`: {'yes' if serve_ready else 'no'}")
    if audit_ready is not None:
        click.echo(f"Ready for audit ledger claims: {_yes_no(audit_ready)}")

    if not serve_ready and not disabled:
        click.echo("")
        click.echo("Fast path:")
        click.echo("  1. Run: ambara onboard --remote <url>")
        click.echo("  2. Push the generated knowledge repo if it is new.")
        click.echo("  3. Run: ambara doctor --check-startup")
        click.echo("  4. Restart the MCP client and start a normal task.")

    return serve_ready and (audit_ready if audit_ready is not None else True)


def _print_muted_scope_summary(policy: ScopeMutePolicy, *, prefix: str = "") -> None:
    if policy.is_empty():
        click.echo(f"{prefix}muted scopes: none")
        return
    summary = scope_policy_summary(policy)
    click.echo(f"{prefix}muted scopes: {summary['total']}")
    for key in ("projects", "repos", "source_inputs", "tags"):
        values = summary[key]
        if values:
            click.echo(f"{prefix}{key}: {', '.join(values)}")


def _active_refs_policy_label(value: bool | None) -> str:
    if value is True:
        return "enabled"
    if value is False:
        return "disabled"
    return "missing"


def _has_project_mcp_config(
    diagnostics: MCPConfigDiagnostics,
    *,
    remote: str,
) -> bool:
    for definition in diagnostics.definitions:
        if definition.scope != "project":
            continue
        if not (
            definition.name == DEFAULT_MCP_SERVER_NAME or definition.name.startswith("ambara-")
        ):
            continue
        if remote and definition.remote != remote:
            continue
        return True
    return False


def _print_team_readiness(
    repo: Path,
    *,
    remote: str,
    startup: StartupDiagnostics,
    mcp_config: MCPConfigDiagnostics,
    gh_path: str | None,
) -> bool:
    config = _read_project_team_config(repo)
    project_mcp_present = _has_project_mcp_config(mcp_config, remote=remote)
    active_policy_known = config.active_refs_enabled is not None
    write_path_available = bool(gh_path) and startup.write_tools_allowed

    team_ready = (
        config.present
        and config.enabled is not False
        and config.read_error is None
        and bool(remote)
        and bool(config.knowledge_remote)
        and project_mcp_present
        and startup.startup_contract_present
        and startup.read_only_allowed
        and active_policy_known
    )

    click.echo("Team readiness:")
    click.echo(f"  repo participation marker: {_yes_no(config.present)}")
    click.echo(f"  config path:               {_display_path(config.path)}")
    if config.read_error:
        click.echo(f"  config error:              {config.read_error}")
    click.echo(f"  Ambara enabled:            {_yes_no(config.enabled is not False)}")
    click.echo(f"  config knowledge remote:   {_status_value(config.knowledge_remote)}")
    click.echo(f"  discovered remote:         {_status_value(remote)}")
    click.echo(f"  project MCP config:        {_yes_no(project_mcp_present)}")
    click.echo(f"  startup contract:          {_yes_no(startup.startup_contract_present)}")
    click.echo(f"  read-only tools:           {_yes_no(startup.read_only_allowed)}")
    click.echo(f"  write path available:      {_yes_no(write_path_available)}")
    active_policy = _active_refs_policy_label(config.active_refs_enabled)
    click.echo(f"  active refs policy:        {active_policy}")
    if config.active_ref_ttl_hours is not None:
        click.echo(f"  active refs TTL:           {config.active_ref_ttl_hours}h")
    _print_muted_scope_summary(config.muted_scopes, prefix="  ")
    click.echo(
        "  privacy boundary:          repo readiness only; no teammate install/presence tracking"
    )
    click.echo(f"  Team ready:                {_yes_no(team_ready)}")
    if not team_ready:
        click.echo(
            "  fix: run `ambara doctor --fix-project-config --team` "
            "after setting the knowledge remote."
        )
    return team_ready


def _print_disabled_team_readiness(config: ProjectTeamConfig) -> bool:
    click.echo("Team readiness:")
    click.echo(f"  repo participation marker: {_yes_no(config.present)}")
    click.echo(f"  config path:               {_display_path(config.path)}")
    if config.read_error:
        click.echo(f"  config error:              {config.read_error}")
        return False
    click.echo("  Ambara enabled:            no")
    _print_muted_scope_summary(config.muted_scopes, prefix="  ")
    click.echo("  Team ready:                skipped; Ambara disabled for this project")
    return True


def _status_value(value: str | None) -> str:
    return value if value else "missing"


def _found_value(path: str | None) -> str:
    return path if path else "missing"


def _startup_diagnostics(repo: Path, *, remote: str | None = None) -> StartupDiagnostics:
    claude_md = repo / "CLAUDE.md"
    settings_file = repo / ".claude" / "settings.json"
    permissions = _settings_permissions(settings_file)
    expected_read_only = _ambara_expected_settings_allowlist(
        remote=remote,
        include_write=False,
    )
    expected_write = _ambara_expected_settings_allowlist(
        remote=remote,
        include_read_only=False,
    )
    missing_read_only = tuple(tool for tool in expected_read_only if tool not in permissions)
    return StartupDiagnostics(
        claude_md_present=claude_md.exists(),
        startup_contract_present=_has_startup_contract(claude_md.read_text())
        if claude_md.exists()
        else False,
        settings_present=settings_file.exists(),
        read_only_allowed=not missing_read_only,
        write_tools_allowed=all(tool in permissions for tool in expected_write),
        missing_read_only_tools=missing_read_only,
    )


def _settings_permissions(settings_file: Path) -> set[str]:
    if not settings_file.exists():
        return set()
    try:
        data = json.loads(settings_file.read_text())
    except (json.JSONDecodeError, OSError):
        return set()
    permissions = data.get("permissions", {}).get("allow", [])
    if not isinstance(permissions, list):
        return set()
    return {item for item in permissions if isinstance(item, str)}


def _print_startup_diagnostics(diagnostics: StartupDiagnostics, *, disabled: bool = False) -> None:
    click.echo("Agent startup:")
    click.echo(f"  CLAUDE.md startup contract: {_yes_no(diagnostics.startup_contract_present)}")
    click.echo(f"  .claude/settings.json:       {_yes_no(diagnostics.settings_present)}")
    click.echo(f"  read-only tools auto-approved: {_yes_no(diagnostics.read_only_allowed)}")
    click.echo(f"  write tools auto-approved:     {_yes_no(diagnostics.write_tools_allowed)}")
    if diagnostics.missing_read_only_tools:
        missing = ", ".join(diagnostics.missing_read_only_tools)
        click.echo(f"  missing read-only tools:       {missing}")
    if disabled:
        click.echo("  disabled state:             agents proceed local-only")
    elif not diagnostics.startup_contract_present or not diagnostics.read_only_allowed:
        click.echo("  fix: run `ambara install-claude-md --repo-path . --remote <url>`")


def _mcp_config_locations(repo: Path, home: Path) -> tuple[tuple[str, Path], ...]:
    candidates = [
        ("project", repo / ".mcp.json"),
        ("project", repo / ".claude" / "mcp.json"),
        ("project", repo / ".claude" / "settings.json"),
        ("user", home / ".claude" / "mcp.json"),
        ("user", home / ".claude.json"),
    ]
    locations: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for scope, path in candidates:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        locations.append((scope, path))
    return tuple(locations)


def _mcp_config_diagnostics(repo: Path, home: Path) -> MCPConfigDiagnostics:
    definitions: list[MCPServerDefinition] = []
    read_errors: list[str] = []
    for scope, path in _mcp_config_locations(repo, home):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            read_errors.append(f"{path}: {exc}")
            continue
        for name, raw_config in _iter_mcp_servers(data):
            definitions.append(_mcp_definition(name, raw_config, scope=scope, path=path))

    collision_names = tuple(
        sorted(
            name
            for name in {definition.name for definition in definitions}
            if sum(1 for definition in definitions if definition.name == name) > 1
        )
    )
    return MCPConfigDiagnostics(
        definitions=tuple(definitions),
        read_errors=tuple(read_errors),
        collision_names=collision_names,
    )


def _blocking_mcp_collision_names(collision_names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        name
        for name in collision_names
        if name == DEFAULT_MCP_SERVER_NAME or name.startswith(f"{DEFAULT_MCP_SERVER_NAME}-")
    )


def _iter_mcp_servers(value: object) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    if isinstance(value, dict):
        servers = value.get("mcpServers")
        if isinstance(servers, dict):
            for name, config in servers.items():
                if isinstance(name, str):
                    found.append((name, config))
        for nested in value.values():
            found.extend(_iter_mcp_servers(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_iter_mcp_servers(nested))
    return found


def _mcp_definition(
    name: str, raw_config: object, *, scope: str, path: Path
) -> MCPServerDefinition:
    command: str | None = None
    args: tuple[str, ...] = ()
    remote: str | None = None
    if isinstance(raw_config, dict):
        raw_command = raw_config.get("command")
        if isinstance(raw_command, str):
            command = raw_command
        raw_args = raw_config.get("args")
        if isinstance(raw_args, list):
            args = tuple(item for item in raw_args if isinstance(item, str))
        raw_env = raw_config.get("env")
        if isinstance(raw_env, dict):
            raw_remote = raw_env.get("AMBARA_KNOWLEDGE_REMOTE")
            if isinstance(raw_remote, str) and raw_remote:
                remote = raw_remote
    return MCPServerDefinition(
        name=name,
        scope=scope,
        path=path,
        command=command,
        args=args,
        remote=remote,
    )


def _print_mcp_config_diagnostics(diagnostics: MCPConfigDiagnostics, *, remote: str) -> None:
    click.echo("MCP config:")
    if remote:
        click.echo(f"  expected server name: {_mcp_server_name(remote)}")
    if not diagnostics.definitions:
        click.echo("  server definitions found: none")
    else:
        click.echo(f"  server definitions found: {len(diagnostics.definitions)}")
        for definition in diagnostics.definitions:
            click.echo(
                f"  - {definition.name} ({definition.scope}) at {_display_path(definition.path)}"
            )

    if diagnostics.read_errors:
        click.echo("  unreadable config files:")
        for error in diagnostics.read_errors:
            click.echo(f"    - {error}")

    if diagnostics.collision_names:
        click.echo("  collision risk: duplicate MCP server names detected")
        for name in diagnostics.collision_names:
            click.echo(f"    - {name}")
        blocking = _blocking_mcp_collision_names(diagnostics.collision_names)
        if blocking:
            click.echo("  fix: keep one Ambara definition for each server name.")
            click.echo(
                "       For Claude Code, remove a legacy user entry with "
                "`claude mcp remove <name> -s user`,"
            )
            click.echo(
                "       or regenerate project config with "
                "`ambara mcp-config --remote <url> --write-project`."
            )
        else:
            click.echo("  note: duplicate non-Ambara servers do not block Ambara startup.")

    legacy = [definition for definition in diagnostics.definitions if definition.name == "ambara"]
    if legacy and not diagnostics.collision_names:
        click.echo("  note: legacy server name 'ambara' found; hash-based names avoid collisions.")


def _audit_diagnostics() -> AuditDiagnostics:
    blockers = (
        "Ambara-created commits are not signed or verified by Ambara.",
        "Lifecycle event files are not append-only, hash-chained, signed, or complete for L0.",
        "L0 active refs can be deleted and are explicitly non-audit context today.",
        "recorded_by/source metadata are informational, not authenticated actor identity.",
        "Branch protection and signed-commit host policy are not configured or verified by Ambara.",
    )
    return AuditDiagnostics(
        reviewable_git_context=True,
        signed_commits=False,
        append_only_events=False,
        complete_lifecycle_events=False,
        active_refs_audit_safe=False,
        authenticated_identity=False,
        host_protection_verified=False,
        blockers=blockers,
    )


def _print_audit_diagnostics(diagnostics: AuditDiagnostics) -> bool:
    audit_ready = (
        diagnostics.signed_commits
        and diagnostics.append_only_events
        and diagnostics.complete_lifecycle_events
        and diagnostics.active_refs_audit_safe
        and diagnostics.authenticated_identity
        and diagnostics.host_protection_verified
    )

    click.echo("Audit/compliance claim gate:")
    click.echo(f"  reviewable git-backed context: {_yes_no(diagnostics.reviewable_git_context)}")
    click.echo(f"  immutable ledger claim:       {_yes_no(audit_ready)}")
    click.echo(f"  tamper-evident ledger claim:  {_yes_no(audit_ready)}")
    click.echo(f"  SOC2-ready audit evidence:    {_yes_no(audit_ready)}")
    click.echo(f"  signed Ambara commits:        {_yes_no(diagnostics.signed_commits)}")
    click.echo(f"  append-only event evidence:   {_yes_no(diagnostics.append_only_events)}")
    click.echo(f"  complete lifecycle events:    {_yes_no(diagnostics.complete_lifecycle_events)}")
    click.echo(f"  L0 active refs audit-safe:    {_yes_no(diagnostics.active_refs_audit_safe)}")
    click.echo(f"  authenticated actor identity: {_yes_no(diagnostics.authenticated_identity)}")
    click.echo(f"  host protection verified:     {_yes_no(diagnostics.host_protection_verified)}")
    click.echo("  allowed claim:                reviewable project context backed by git")
    click.echo(
        "  blocked claims:               immutable ledger, tamper-evident ledger, "
        "SOC2-ready audit trail, authenticated authorship"
    )
    if diagnostics.blockers:
        click.echo("  blockers:")
        for blocker in diagnostics.blockers:
            click.echo(f"    - {blocker}")
    return audit_ready


def _display_path(path: Path) -> str:
    home = Path.home()
    try:
        relative = path.expanduser().resolve().relative_to(home.expanduser().resolve())
    except ValueError:
        return str(path)
    return f"~/{relative.as_posix()}"


def _print_startup_probe(remote: str, cache_dir: str) -> bool:
    click.echo("Startup probe:")
    if not remote:
        click.echo("  sync():    skipped (missing AMBARA_KNOWLEDGE_REMOTE)")
        click.echo("  context(): skipped (missing AMBARA_KNOWLEDGE_REMOTE)")
        return False

    main_branch = os.environ.get("AMBARA_MAIN_BRANCH", "main")
    active_ref_prefix = os.environ.get("AMBARA_ACTIVE_REF_PREFIX", "ambara/active")
    active_refs_enabled = os.environ.get("AMBARA_ACTIVE_REFS_ENABLED", "").lower() == "true"

    try:
        repo_path = ensure_repo(remote, cache_dir)
        fetch_all(
            repo_path,
            main_branch,
            active_ref_prefix,
            active_refs_enabled=active_refs_enabled,
        )
        index = load_index_from_repo(
            repo_path,
            main_branch,
            active_ref_prefix,
            active_refs_enabled=active_refs_enabled,
        )
    except Exception as exc:
        click.echo(f"  sync():    failed ({exc})")
        cache_hint = _cache_failure_hint(exc)
        if cache_hint:
            click.echo(cache_hint)
        click.echo("  context(): skipped because sync failed")
        return False

    summary = _startup_context_summary(index, datetime.now(UTC))
    click.echo(f"  sync():    ok ({len(index.entries)} entries indexed)")
    click.echo(
        "  context(): ok "
        f"({summary['active']} active, {summary['recent']} recent entries available)"
    )
    return True


def _print_disabled_startup_probe() -> bool:
    click.echo("Startup probe:")
    click.echo("  sync():    skipped (Ambara disabled)")
    click.echo("  startup(): disabled (agents proceed local-only)")
    return True


def _startup_context_summary(index: Index, now: datetime) -> dict[str, int]:
    recent_cutoff = now - timedelta(days=7)
    active = 0
    recent = 0
    for entry in index.entries.values():
        fm = entry.frontmatter
        if fm.sensitivity == Sensitivity.RESTRICTED:
            continue
        if fm.type == EntryType.ACTIVE and not is_expired(entry, now):
            active += 1
        if (
            fm.type != EntryType.ACTIVE
            and fm.updated_at >= recent_cutoff
            and fm.status in (EntryStatus.ACTIVE, EntryStatus.PROPOSED)
        ):
            recent += 1
    return {"active": active, "recent": min(recent, 15)}


def _cache_failure_hint(exc: Exception) -> str | None:
    message = str(exc).lower()
    cache_problem_markers = (
        "read-only file system",
        "permission denied",
        "could not create work tree dir",
        "file exists",
        "not a directory",
    )
    if not any(marker in message for marker in cache_problem_markers):
        return None
    return (
        "  fix: set AMBARA_CACHE_DIR to a writable directory, for example "
        "`AMBARA_CACHE_DIR=/tmp/ambara-cache ambara doctor --check-startup`."
    )


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
