# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Client conformance smoke command for file-adapter agent surfaces."""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import click

from ambara.cli_install import (
    CLIENT_CONFIGS,
    _install_instructions,
    _mcp_config_payload,
    _write_project_mcp_config,
)
from ambara.cli_render import render_startup_markdown
from ambara.git.config import (
    DEFAULT_CONTEXT_BUDGET_MODE,
    DEFAULT_CONTEXT_FRESHNESS_WARNING_SECONDS,
    DEFAULT_CONTEXT_STALE_AFTER_SECONDS,
    AmbaraConfig,
)
from ambara.git.repo import ensure_repo, fetch_all, load_index_from_repo
from ambara.server_read import build_startup_v2_payload
from ambara.server_state import SyncHealth

ValueLedgerPath = Callable[[str, str | None], Path]


class WriteStartupValueEvent(Protocol):
    def __call__(
        self,
        packet: dict[str, object],
        *,
        ledger_path: Path,
        budget_mode: str,
        now: datetime,
    ) -> None: ...


class BuildValueRollup(Protocol):
    def __call__(
        self,
        ledger_path: Path,
        config: AmbaraConfig,
        *,
        now: datetime,
    ) -> dict[str, object] | None: ...


class WriteProjectTeamConfig(Protocol):
    def __call__(
        self,
        repo: Path,
        *,
        remote: str,
        active_refs_enabled: bool = False,
    ) -> Path: ...


def register_client_smoke_command(
    main: click.Group,
    *,
    write_project_team_config: WriteProjectTeamConfig,
    write_startup_value_event: WriteStartupValueEvent,
    build_value_rollup: BuildValueRollup,
    value_ledger_path: ValueLedgerPath,
) -> None:
    """Register client-smoke without expanding the already-large CLI facade."""

    @main.command("client-smoke")
    @click.option(
        "--client",
        "client_name",
        type=click.Choice(["claude-code", "codex", "cursor", "gemini"]),
        default="codex",
        show_default=True,
        help="Agent client surface to smoke through the plain file adapter.",
    )
    @click.option(
        "--remote",
        envvar="AMBARA_KNOWLEDGE_REMOTE",
        required=True,
        help="Git remote or local path for the team knowledge repo.",
    )
    @click.option(
        "--project-path",
        default=".",
        show_default=True,
        type=click.Path(file_okay=False),
        help="Project directory where the file-adapter context should be written.",
    )
    @click.option(
        "--cache-dir",
        default=None,
        type=click.Path(file_okay=False),
        help="Local cache directory. Defaults to <project>/.ambara/cache.",
    )
    @click.option("--goal", default="client smoke", show_default=True, help="Startup goal text.")
    @click.option("--json", "as_json", is_flag=True, help="Print machine-readable smoke result.")
    def client_smoke_cmd(
        client_name: str,
        remote: str,
        project_path: str,
        cache_dir: str | None,
        goal: str,
        as_json: bool,
    ) -> None:
        """Smoke a named agent through the no-network file-adapter path."""
        project = Path(project_path)
        project.mkdir(parents=True, exist_ok=True)
        context_path = project / ".ambara" / "context.md"
        resolved_cache_dir = Path(cache_dir) if cache_dir else project / ".ambara" / "cache"
        resolved_cache_dir.mkdir(parents=True, exist_ok=True)

        client_slug = "claude-code" if client_name == "claude-code" else client_name
        with contextlib.redirect_stdout(io.StringIO()) if as_json else contextlib.nullcontext():
            write_project_team_config(project, remote=remote, active_refs_enabled=True)
            setup_paths = _install_client_smoke_setup(
                project,
                remote=remote,
                client_name=client_name,
            )

        try:
            repo_path = ensure_repo(remote, str(resolved_cache_dir))
            fetch_all(repo_path, "main", active_refs_enabled=True)
            index = load_index_from_repo(repo_path, "main", active_refs_enabled=True)
        except Exception as exc:
            raise click.ClickException(
                f"Client smoke could not load knowledge repo: {exc}"
            ) from exc

        now = datetime.now(UTC)
        packet = build_startup_v2_payload(
            index,
            now=now,
            sync_health=SyncHealth(last_success=now),
            freshness_warning_seconds=DEFAULT_CONTEXT_FRESHNESS_WARNING_SECONDS,
            stale_after_seconds=DEFAULT_CONTEXT_STALE_AFTER_SECONDS,
            goal=goal,
            budget_mode=DEFAULT_CONTEXT_BUDGET_MODE,
        )
        config = AmbaraConfig(
            remote_url=remote,
            cache_dir=str(resolved_cache_dir),
            client_slug=client_slug,
            active_refs_enabled=True,
        )
        ledger_path = value_ledger_path(config.cache_dir, config.value_ledger_path)
        write_startup_value_event(
            packet,
            ledger_path=ledger_path,
            budget_mode=config.context_budget_mode,
            now=now,
        )
        rollup = build_value_rollup(ledger_path, config, now=now)
        if rollup:
            packet["value_rollup"] = rollup

        context_path.parent.mkdir(parents=True, exist_ok=True)
        context_markdown = render_startup_markdown(packet)
        context_path.write_text(context_markdown)
        readback = context_path.read_text()
        ok = (
            packet.get("v") == "s2"
            and "# Team Context" in readback
            and "## Dig deeper" in readback
            and "body" not in json.dumps(packet).lower()
        )
        result: dict[str, object] = {
            "ok": ok,
            "client": client_name,
            "client_slug": client_slug,
            "adapter": "file",
            "context_path": str(context_path),
            "knowledge_entry_count": len(index.entries),
            "entry_count": len(packet.get("entries", []))
            if isinstance(packet.get("entries"), list)
            else 0,
            "value_rollup_events": _int_from_mapping(
                packet.get("value_rollup"),
                "events",
                default=0,
            )
            or 0,
            "instructions_path": setup_paths.get("instructions_path"),
            "mcp_config_path": setup_paths.get("mcp_config_path"),
        }
        if as_json:
            click.echo(json.dumps(result, indent=2))
            return

        click.echo("Ambara client smoke")
        click.echo(f"  client:        {client_name}")
        click.echo("  adapter:       file")
        click.echo(f"  context file:  {context_path}")
        click.echo(f"  knowledge:     {result['knowledge_entry_count']}")
        click.echo(f"  entries:       {result['entry_count']}")
        click.echo(f"  value events:  {result['value_rollup_events']}")
        if setup_paths.get("instructions_path"):
            click.echo(f"  instructions:  {setup_paths['instructions_path']}")
        if setup_paths.get("mcp_config_path"):
            click.echo(f"  mcp config:    {setup_paths['mcp_config_path']}")
        click.echo(f"  result:        {'pass' if ok else 'fail'}")
        if not ok:
            raise click.ClickException("Client smoke failed file-adapter validation.")


def _install_client_smoke_setup(
    project: Path, *, remote: str, client_name: str
) -> dict[str, str | None]:
    installer_name = "claude" if client_name == "claude-code" else client_name
    client_config = CLIENT_CONFIGS.get(installer_name)
    if client_config is None:
        return {"instructions_path": None, "mcp_config_path": None}

    _install_instructions(
        project,
        remote,
        client_config=client_config,
        solo=False,
    )
    payload = _mcp_config_payload(remote, client_name, "ambara")
    mcp_path = project / client_config.mcp_config_path
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    _write_project_mcp_config(mcp_path, payload)
    return {
        "instructions_path": str(project / client_config.instructions_path),
        "mcp_config_path": str(mcp_path),
    }


def _int_from_mapping(value: object, key: str, *, default: int | None = None) -> int | None:
    if not isinstance(value, dict):
        return default
    raw = value.get(key)
    if isinstance(raw, bool):
        return default
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    return default
