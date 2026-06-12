# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Project-level config I/O for the Ambara CLI.

Reads and writes the project team config (``.ambara/config.yaml``) and the
project ``.mcp.json`` enable/disable state. Depends only on the leaf utilities
in :mod:`ambara.cli.util` and the core/git layers, never back on ``cli/__init__.py``, so
command-family modules can import these helpers freely.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import click

from ambara.cli.install import DEFAULT_MCP_SERVER_NAME
from ambara.cli.util import _dump_yaml_mapping, _load_yaml_mapping, _optional_str
from ambara.core.scope_policy import ScopeMutePolicy
from ambara.git.config import MAX_ACTIVE_REF_TTL_HOURS

PROJECT_TEAM_CONFIG = Path(".ambara") / "config.yaml"


@dataclass(frozen=True)
class ProjectTeamConfig:
    path: Path
    present: bool
    read_error: str | None
    knowledge_remote: str | None
    enabled: bool | None
    muted_scopes: ScopeMutePolicy
    active_refs_enabled: bool | None
    active_ref_ttl_hours: int | None


def _project_enabled_from_config(data: dict[str, object]) -> bool:
    value = data.get("enabled")
    if isinstance(value, bool):
        return value
    disabled = data.get("disabled")
    if isinstance(disabled, bool):
        return not disabled
    return True


def _active_refs_policy_from_config(data: dict[str, object]) -> bool | None:
    active_refs = data.get("active_refs")
    if isinstance(active_refs, dict):
        enabled = active_refs.get("enabled")
        if isinstance(enabled, bool):
            return enabled
    value = data.get("active_refs_enabled")
    if isinstance(value, bool):
        return value
    expiry = data.get("expiry")
    if isinstance(expiry, dict):
        expiry_value = expiry.get("active_refs_enabled")
        if isinstance(expiry_value, bool):
            return expiry_value
    return None


def _ttl_hours(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        ttl = None
    elif isinstance(value, int):
        ttl = value
    elif isinstance(value, str) and value.strip().isdigit():
        ttl = int(value.strip())
    else:
        ttl = None

    if ttl is None or not 1 <= ttl <= MAX_ACTIVE_REF_TTL_HOURS:
        raise ValueError(
            f"active ref TTL must be an integer between 1 and {MAX_ACTIVE_REF_TTL_HOURS} hours"
        )
    return ttl


def _active_ref_ttl_hours_from_config(data: dict[str, object]) -> int | None:
    active_refs = data.get("active_refs")
    if isinstance(active_refs, dict):
        ttl = _ttl_hours(active_refs.get("ttl_hours"))
        if ttl is not None:
            return ttl
    expiry = data.get("expiry")
    if isinstance(expiry, dict):
        return _ttl_hours(expiry.get("active_ttl_hours"))
    return None


def _ambara_disabled(config: ProjectTeamConfig) -> bool:
    return os.environ.get("AMBARA_DISABLED", "").lower() == "true" or config.enabled is False


def _project_active_ref_env(config: ProjectTeamConfig) -> dict[str, str]:
    env: dict[str, str] = {}
    if config.enabled is False:
        env["AMBARA_DISABLED"] = "true"
    if config.active_refs_enabled is not None:
        env["AMBARA_ACTIVE_REFS_ENABLED"] = "true" if config.active_refs_enabled else "false"
    if config.active_ref_ttl_hours is not None:
        env["AMBARA_ACTIVE_REF_TTL_HOURS"] = str(config.active_ref_ttl_hours)
    return env


def _read_project_team_config(repo: Path) -> ProjectTeamConfig:
    path = repo / PROJECT_TEAM_CONFIG
    if not path.exists():
        return ProjectTeamConfig(
            path=path,
            present=False,
            read_error=None,
            knowledge_remote=None,
            enabled=None,
            muted_scopes=ScopeMutePolicy(),
            active_refs_enabled=None,
            active_ref_ttl_hours=None,
        )

    try:
        data = _load_yaml_mapping(path)
    except ValueError as exc:
        return ProjectTeamConfig(
            path=path,
            present=True,
            read_error=str(exc),
            knowledge_remote=None,
            enabled=None,
            muted_scopes=ScopeMutePolicy(),
            active_refs_enabled=None,
            active_ref_ttl_hours=None,
        )

    enabled = _project_enabled_from_config(data)
    muted_scopes = ScopeMutePolicy.from_raw(data.get("muted_scopes"))
    active_refs_enabled = _active_refs_policy_from_config(data)
    try:
        active_ref_ttl_hours = _active_ref_ttl_hours_from_config(data)
    except ValueError as exc:
        return ProjectTeamConfig(
            path=path,
            present=True,
            read_error=str(exc),
            knowledge_remote=_optional_str(data.get("knowledge_remote")),
            enabled=enabled,
            muted_scopes=muted_scopes,
            active_refs_enabled=active_refs_enabled,
            active_ref_ttl_hours=None,
        )

    return ProjectTeamConfig(
        path=path,
        present=True,
        read_error=None,
        knowledge_remote=_optional_str(data.get("knowledge_remote")),
        enabled=enabled,
        muted_scopes=muted_scopes,
        active_refs_enabled=active_refs_enabled,
        active_ref_ttl_hours=active_ref_ttl_hours,
    )


def _write_project_team_config(
    repo: Path, *, remote: str, active_refs_enabled: bool = False
) -> Path:
    path = repo / PROJECT_TEAM_CONFIG
    if path.exists():
        try:
            data = _load_yaml_mapping(path)
        except ValueError as exc:
            raise click.ClickException(f"Cannot update {path}: {exc}") from exc
    else:
        data = {}

    data.setdefault("schema_version", 1)
    data.setdefault("enabled", True)
    data["knowledge_remote"] = remote
    if "active_refs_enabled" not in data and "active_refs" not in data:
        data["active_refs_enabled"] = active_refs_enabled
    expiry = data.setdefault("expiry", {})
    if isinstance(expiry, dict):
        expiry.setdefault("active_ttl_hours", 72)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_yaml_mapping(data))
    click.echo(f"Updated {path}.")
    return path


def _set_project_enabled(repo: Path, *, enabled: bool, remote: str | None = None) -> Path:
    path = repo / PROJECT_TEAM_CONFIG
    if path.exists():
        try:
            data = _load_yaml_mapping(path)
        except ValueError as exc:
            raise click.ClickException(f"Cannot update {path}: {exc}") from exc
    else:
        data = {}

    data.setdefault("schema_version", 1)
    data["enabled"] = enabled
    if remote is not None:
        data["knowledge_remote"] = remote
    if enabled and not _optional_str(data.get("knowledge_remote")):
        raise click.ClickException(
            "Cannot enable Ambara without a knowledge repo remote. Pass --remote."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_yaml_mapping(data))
    return path


def _set_project_mcp_disabled(repo: Path, *, disabled: bool) -> int:
    path = repo / ".mcp.json"
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Cannot update {path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise click.ClickException(f"Cannot update {path}: top-level JSON must be an object.")

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return 0

    updated = 0
    for name, raw_config in servers.items():
        if not isinstance(name, str) or not isinstance(raw_config, dict):
            continue
        env = raw_config.setdefault("env", {})
        if not isinstance(env, dict):
            continue
        is_ambara = (
            name == DEFAULT_MCP_SERVER_NAME
            or name.startswith(f"{DEFAULT_MCP_SERVER_NAME}-")
            or "AMBARA_KNOWLEDGE_REMOTE" in env
            or raw_config.get("command") == "ambara"
        )
        if not is_ambara:
            continue
        if disabled:
            env["AMBARA_DISABLED"] = "true"
        else:
            env.pop("AMBARA_DISABLED", None)
        updated += 1

    if updated:
        path.write_text(json.dumps(data, indent=2) + "\n")
    return updated


def _update_project_entry_feedback(repo: Path, *, entry_id: str, signal: str) -> tuple[Path, int]:
    if not entry_id.strip():
        raise click.ClickException("entry_id must not be empty.")
    path = repo / PROJECT_TEAM_CONFIG
    if path.exists():
        try:
            data = _load_yaml_mapping(path)
        except ValueError as exc:
            raise click.ClickException(f"Cannot update {path}: {exc}") from exc
    else:
        data = {}
    data.setdefault("schema_version", 1)
    raw_feedback = data.get("entry_feedback")
    feedback = raw_feedback if isinstance(raw_feedback, dict) else {}
    if signal == "useful":
        feedback.pop(entry_id, None)
    else:
        feedback[entry_id] = signal
    if feedback:
        data["entry_feedback"] = dict(sorted(feedback.items()))
    else:
        data.pop("entry_feedback", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_yaml_mapping(data))
    return path, len(feedback)
