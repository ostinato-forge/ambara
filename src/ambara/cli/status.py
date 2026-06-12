# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Status payload and rendering helpers for the Ambara CLI."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import click

from ambara.cli.project_config import (
    ProjectTeamConfig,
    _ambara_disabled,
    _read_project_team_config,
)
from ambara.cli.setup_diagnostics import (
    MCPConfigDiagnostics,
    StartupDiagnostics,
    _blocking_mcp_collision_names,
    _discover_remote,
    _display_path,
    _mcp_config_diagnostics,
    _startup_diagnostics,
    _status_value,
    _yes_no,
)
from ambara.cli.value import _value_ledger_path_from_env
from ambara.git.repo import repo_cache_path
from ambara.server_signals import source_inputs_configured
from ambara.sources.config import source_inputs_config_from_env
from ambara.sources.health import SourceHealthStatus
from ambara.sources.inspect import SourceInspection, SourceInspectionReport


@dataclass(frozen=True)
class StartupCliResult:
    packet: dict[str, Any]
    value_ledger_path: Path | None = None
    source_report: SourceInspectionReport | None = None


class StartupPacketCompiler(Protocol):
    def __call__(
        self,
        *,
        repo: str | None,
        goal: str | None,
        max_entries: int,
        include_muted: bool,
        record_value: bool,
    ) -> StartupCliResult: ...


def register_status_command(main: click.Group, *, compile_startup: StartupPacketCompiler) -> None:
    @main.command("status")
    @click.option("--json", "as_json", is_flag=True, help="Print machine-readable status output.")
    @click.option(
        "--refresh",
        is_flag=True,
        help="Fetch knowledge/source inputs and compile a startup packet health check.",
    )
    @click.option("--repo", default=None, help="Project slug for filtering startup entries.")
    @click.option(
        "--goal",
        default="status check",
        show_default=True,
        help="Goal text used when compiling the startup health check.",
    )
    @click.option("--max-entries", default=5, show_default=True, help="Startup entries to sample.")
    def status_cmd(
        as_json: bool,
        refresh: bool,
        repo: str | None,
        goal: str,
        max_entries: int,
    ) -> None:
        """Show first-run health, wiring, source, startup, and value status."""
        payload = _status_payload(
            refresh=refresh,
            repo=repo,
            goal=goal,
            max_entries=max_entries,
            compile_startup=compile_startup,
        )
        if as_json:
            click.echo(json.dumps(payload, indent=2, sort_keys=True))
            return
        _print_status_payload(payload)


def _status_payload(
    *,
    refresh: bool,
    repo: str | None,
    goal: str,
    max_entries: int,
    compile_startup: StartupPacketCompiler,
) -> dict[str, Any]:
    project_config = _read_project_team_config(Path.cwd())
    disabled = _ambara_disabled(project_config)
    remote = _discover_remote() or ""
    cache_dir = os.environ.get("AMBARA_CACHE_DIR", os.path.expanduser("~/.cache/ambara"))
    git_path = shutil.which("git")
    startup = _startup_diagnostics(Path.cwd(), remote=remote or None)
    mcp_config = _mcp_config_diagnostics(Path.cwd(), Path.home())
    blocking_collisions = _blocking_mcp_collision_names(mcp_config.collision_names)
    ready = _status_ready(
        disabled=disabled,
        remote=remote,
        git_path=git_path,
        startup=startup,
        mcp_config=mcp_config,
        project_config=project_config,
    )
    now = datetime.now(UTC)
    source_inputs_configured_flag: bool | None = None
    source_inputs_error: str | None = None
    try:
        source_inputs_configured_flag = source_inputs_configured(source_inputs_config_from_env())
    except Exception as exc:
        source_inputs_error = str(exc)

    status = "disabled" if disabled else ("wiring_ready" if ready else "needs_setup")
    if source_inputs_error and not disabled:
        status = "needs_attention"

    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": status,
        "knowledge_repo": {
            "remote": remote or None,
            "cache_dir": cache_dir,
            "derived_cache_path": repo_cache_path(remote, cache_dir) if remote else None,
            "project_config": _display_path(project_config.path),
            "project_config_present": project_config.present,
            "project_config_error": project_config.read_error,
        },
        "client_wiring": _status_client_wiring_payload(
            startup,
            mcp_config,
            blocking_collisions=blocking_collisions,
        ),
        "source_inputs": _status_source_inputs_payload(
            None,
            configured=source_inputs_configured_flag,
            config_error=source_inputs_error,
            now=now,
        ),
        "startup_packet": {"status": "not_checked"},
        "value_ledger": _status_value_ledger_payload(),
        "next_repair": None,
    }

    if refresh:
        try:
            result = compile_startup(
                repo=repo,
                goal=goal,
                max_entries=max_entries,
                include_muted=False,
                record_value=False,
            )
        except click.ClickException as exc:
            payload["status"] = "needs_attention"
            payload["startup_packet"] = {"status": "error", "error": exc.message}
            payload["source_inputs"] = _status_source_inputs_payload(
                None,
                configured=source_inputs_configured_flag,
                config_error=source_inputs_error,
                now=now,
            )
            if (
                source_inputs_configured_flag is True
                and "Source input refresh failed" in exc.message
            ):
                payload["source_inputs"]["status"] = "configured_unavailable"
                payload["source_inputs"]["reason"] = "source refresh failed"
            else:
                payload["source_inputs"]["reason"] = "startup refresh failed"
        else:
            packet = result.packet
            source_inputs = _status_source_inputs_payload(
                result.source_report,
                configured=source_inputs_configured_flag,
                config_error=None,
                now=now,
            )
            payload["startup_packet"] = _status_startup_packet_payload(packet)
            payload["source_inputs"] = source_inputs
            payload["value_ledger"] = _status_value_ledger_payload(result.value_ledger_path)
            source_status = source_inputs.get("status")
            if packet.get("availability") == "unavailable" or source_status in {
                "configured_stale",
                "configured_unavailable",
                "configured_error",
            }:
                payload["status"] = "needs_attention"
            elif payload["status"] in {"wiring_ready", "needs_attention"}:
                payload["status"] = "ready"

    payload["next_repair"] = _status_next_repair(
        payload,
        disabled=disabled,
        remote=remote,
        startup=startup,
        blocking_collisions=blocking_collisions,
    )
    payload["generated_at"] = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return payload


def _status_ready(
    *,
    disabled: bool,
    remote: str,
    git_path: str | None,
    startup: StartupDiagnostics,
    mcp_config: MCPConfigDiagnostics,
    project_config: ProjectTeamConfig,
) -> bool:
    if disabled:
        return True
    if project_config.read_error:
        return False
    if not remote or not git_path:
        return False
    if not startup.startup_contract_present or not startup.read_only_allowed:
        return False
    return not _blocking_mcp_collision_names(mcp_config.collision_names)


def _status_client_wiring_payload(
    startup: StartupDiagnostics,
    mcp_config: MCPConfigDiagnostics,
    *,
    blocking_collisions: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "startup_contract_present": startup.startup_contract_present,
        "settings_present": startup.settings_present,
        "read_only_tools_allowed": startup.read_only_allowed,
        "write_tools_allowed": startup.write_tools_allowed,
        "missing_read_only_tools": list(startup.missing_read_only_tools),
        "mcp_server_count": len(mcp_config.definitions),
        "mcp_servers": [
            {
                "name": definition.name,
                "scope": definition.scope,
                "path": _display_path(definition.path),
                "remote": definition.remote,
            }
            for definition in mcp_config.definitions
        ],
        "read_errors": list(mcp_config.read_errors),
        "blocking_collisions": list(blocking_collisions),
    }


def _status_startup_packet_payload(packet: dict[str, Any]) -> dict[str, Any]:
    value = packet.get("value")
    entries = packet.get("entries")
    more = packet.get("more")
    return {
        "status": "ok",
        "schema": packet.get("v"),
        "availability": packet.get("availability"),
        "coordination": packet.get("coordination"),
        "action": packet.get("action"),
        "packet_tokens_est": (value.get("packet_tokens_est") if isinstance(value, dict) else None),
        "entry_count": len(entries) if isinstance(entries, list) else 0,
        "entries_omitted": (more.get("entries_omitted") if isinstance(more, dict) else None),
        "restricted_hidden": (more.get("restricted_hidden") if isinstance(more, dict) else None),
    }


def _status_source_inputs_payload(
    report: SourceInspectionReport | None,
    *,
    configured: bool | None,
    config_error: str | None,
    now: datetime,
) -> dict[str, Any]:
    if config_error:
        return {
            "status": "config_error",
            "configured": configured,
            "error": config_error,
        }
    if report is None:
        if configured is False:
            return {
                "status": "not_configured",
                "configured": False,
                "source_count": 0,
                "artifact_count": 0,
                "counts": _status_source_counts(),
            }
        return {"status": "not_checked", "configured": configured}
    if not report.sources:
        return {
            "status": "not_configured",
            "configured": False,
            "source_count": 0,
            "artifact_count": 0,
            "counts": _status_source_counts(),
            "omissions": _status_source_omissions_payload(report),
            "sources": [],
        }

    counts = _status_source_counts()
    sources: list[dict[str, Any]] = []
    for inspection in report.sources:
        status = _status_source_health_status(inspection, now=now)
        counts[status.value] += 1
        sources.append(
            {
                "id": inspection.config.id,
                "provider": inspection.config.provider,
                "category": inspection.config.category.value,
                "status": status.value,
                "artifact_count": len(inspection.artifacts),
                "baseline_available": inspection.health.has_successful_baseline,
                "rate_limited": inspection.rate_limited,
                "omissions": _status_source_omissions_payload(inspection),
            }
        )

    if counts[SourceHealthStatus.ERROR.value]:
        status_value = "configured_error"
    elif counts[SourceHealthStatus.UNAVAILABLE.value]:
        status_value = "configured_unavailable"
    elif counts[SourceHealthStatus.STALE.value]:
        status_value = "configured_stale"
    else:
        status_value = "configured_fresh"

    return {
        "status": status_value,
        "configured": True,
        "source_count": len(report.sources),
        "artifact_count": report.artifact_count,
        "counts": counts,
        "omissions": _status_source_omissions_payload(report),
        "errors": list(report.source_errors),
        "sources": sources,
    }


def _status_source_counts() -> dict[str, int]:
    return {status.value: 0 for status in SourceHealthStatus}


def _status_source_omissions_payload(
    value: SourceInspection | SourceInspectionReport,
) -> dict[str, int]:
    omissions = value.omissions
    return {
        "privacy": omissions.privacy,
        "safety": omissions.safety,
        "budget": omissions.budget,
        "freshness": omissions.freshness,
        "source_error": omissions.source_error,
        "total": omissions.total,
    }


def _status_source_health_status(
    inspection: SourceInspection, *, now: datetime
) -> SourceHealthStatus:
    health = inspection.health
    if (
        health.status is SourceHealthStatus.FRESH
        and health.stale_after is not None
        and health.stale_after <= now
    ):
        return SourceHealthStatus.STALE
    return health.status


def _status_value_ledger_payload(path: Path | None = None) -> dict[str, Any]:
    ledger_path = path or _value_ledger_path_from_env()
    event_count = 0
    if ledger_path.exists():
        event_count = sum(1 for line in ledger_path.read_text().splitlines() if line.strip())
    return {
        "path": str(ledger_path.expanduser()),
        "exists": ledger_path.exists(),
        "event_count": event_count,
    }


def _status_next_repair(
    payload: dict[str, Any],
    *,
    disabled: bool,
    remote: str,
    startup: StartupDiagnostics,
    blocking_collisions: tuple[str, ...],
) -> str:
    if disabled:
        return "Ambara is disabled here; run `ambara enable --remote <url>` to re-enable it."
    knowledge = payload.get("knowledge_repo", {})
    if isinstance(knowledge, dict) and knowledge.get("project_config_error"):
        return "Fix .ambara/config.yaml, then run `ambara status` again."
    source_inputs = payload.get("source_inputs", {})
    if isinstance(source_inputs, dict) and source_inputs.get("status") == "config_error":
        return "Fix source input configuration, then run `ambara status --refresh`."
    if not remote:
        return (
            "Run `ambara demo` to try the loop, or `ambara onboard --local` to wire this project."
        )
    if blocking_collisions:
        return "Remove duplicate Ambara MCP server definitions, then run `ambara status` again."
    startup_packet = payload.get("startup_packet", {})
    if isinstance(source_inputs, dict) and source_inputs.get("status") in {
        "configured_stale",
        "configured_unavailable",
        "configured_error",
    }:
        return "Run `ambara sources doctor` for source input details."
    if isinstance(startup_packet, dict) and startup_packet.get("status") == "error":
        return "Run `ambara doctor --check-startup` for the failing sync/startup details."
    if not startup.startup_contract_present or not startup.read_only_allowed:
        return "Run `ambara doctor --fix-project-config --team` to repair client wiring."
    if isinstance(startup_packet, dict) and startup_packet.get("status") == "not_checked":
        return "Run `ambara status --refresh` to check startup packet, source, and value state."
    return 'Run `ambara startup --goal "your task" --format md` before work.'


def _print_status_payload(payload: dict[str, Any]) -> None:
    click.echo("Ambara status")
    click.echo(f"  overall:        {payload['status']}")
    knowledge = payload["knowledge_repo"]
    click.echo(f"  knowledge repo: {_status_value(knowledge.get('remote'))}")
    click.echo(f"  cache dir:      {knowledge['cache_dir']}")
    if knowledge.get("derived_cache_path"):
        click.echo(f"  cache path:     {knowledge['derived_cache_path']}")
    click.echo(f"  project config: {knowledge['project_config']}")
    if knowledge.get("project_config_error"):
        click.echo(f"  config error:   {knowledge['project_config_error']}")

    client = payload["client_wiring"]
    click.echo("")
    click.echo("Client wiring:")
    click.echo(f"  startup contract: {_yes_no(client['startup_contract_present'])}")
    click.echo(f"  read tools:       {_yes_no(client['read_only_tools_allowed'])}")
    click.echo(f"  write tools:      {_yes_no(client['write_tools_allowed'])}")
    click.echo(f"  MCP servers:      {client['mcp_server_count']}")
    if client["blocking_collisions"]:
        click.echo(f"  collisions:       {', '.join(client['blocking_collisions'])}")

    startup_packet = payload["startup_packet"]
    click.echo("")
    click.echo("Startup packet:")
    if startup_packet["status"] == "not_checked":
        click.echo("  status:          not checked")
    elif startup_packet["status"] == "error":
        click.echo("  status:          error")
        click.echo(f"  error:           {startup_packet['error']}")
    else:
        click.echo(f"  availability:    {startup_packet.get('availability')}")
        click.echo(f"  action:          {startup_packet.get('action')}")
        click.echo(f"  packet tokens:   {_status_value(startup_packet.get('packet_tokens_est'))}")
        click.echo(f"  entries:         {startup_packet.get('entry_count')}")

    source_inputs = payload["source_inputs"]
    click.echo("")
    click.echo("Source inputs:")
    click.echo(f"  status:          {source_inputs['status']}")
    if "configured" in source_inputs:
        click.echo(f"  configured:      {_status_value(source_inputs.get('configured'))}")
    if "source_count" in source_inputs:
        click.echo(f"  sources:         {source_inputs['source_count']}")
        click.echo(f"  artifacts:       {source_inputs['artifact_count']}")
    counts = source_inputs.get("counts")
    if isinstance(counts, dict):
        click.echo(f"  fresh:           {counts.get('fresh', 0)}")
        click.echo(f"  stale:           {counts.get('stale', 0)}")
        click.echo(f"  unavailable:     {counts.get('unavailable', 0)}")
        click.echo(f"  error:           {counts.get('error', 0)}")
    omissions = source_inputs.get("omissions")
    if isinstance(omissions, dict):
        click.echo(f"  omissions:       {omissions.get('total')}")
    errors = source_inputs.get("errors")
    if isinstance(errors, list) and errors:
        click.echo(f"  attention:       {len(errors)} source issue(s)")

    value = payload["value_ledger"]
    click.echo("")
    click.echo("Value ledger:")
    click.echo(f"  path:            {value['path']}")
    click.echo(f"  exists:          {_yes_no(value['exists'])}")
    click.echo(f"  events:          {value['event_count']}")

    click.echo("")
    click.echo(f"Next repair: {payload['next_repair']}")
