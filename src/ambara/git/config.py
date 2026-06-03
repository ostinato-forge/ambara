# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Configuration for the ambara server and git operations."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from ambara.core.scope_policy import ScopeMutePolicy

_SAFE_PREFIX_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,100}$")
MAX_ACTIVE_REF_TTL_HOURS = 168
DEFAULT_CONTEXT_FRESHNESS_WARNING_SECONDS = 300
DEFAULT_CONTEXT_STALE_AFTER_SECONDS = 900
DEFAULT_CONTEXT_MODE = "manifest"
VALID_CONTEXT_MODES = frozenset({"compiler", "full", "manifest", "startup"})
DEFAULT_CONTEXT_BUDGET_MODE = "balanced"
VALID_CONTEXT_BUDGET_MODES = frozenset({"quiet", "balanced", "deep"})
DEFAULT_STARTUP_MAX_ENTRIES = 3
MAX_STARTUP_ENTRIES = 5
DEFAULT_VALUE_LEDGER_RETENTION_DAYS = 90


@dataclass(frozen=True)
class PRSignalsConfig:
    provider: str = "github"
    label: str = "ambara"
    recency_days: int = 30
    repos: tuple[str, ...] = ()
    fixture_path: str | None = None
    include_body_excerpt: bool = True
    include_changed_paths: bool = True
    gitlab_base_url: str | None = None
    jira_base_url: str | None = None
    jira_projects: tuple[str, ...] = ()


@dataclass(frozen=True)
class AmbaraConfig:
    remote_url: str
    cache_dir: str = os.path.expanduser("~/.cache/ambara")
    main_branch: str = "main"
    branch_prefix: str = "ambara"
    active_ref_prefix: str = "ambara/active"
    sync_interval: int = 300
    client_slug: str | None = "claude-code"
    repo_graph: dict[str, list[str]] = field(default_factory=dict)
    secret_patterns: list[str] = field(default_factory=list)
    pr_signals: PRSignalsConfig = field(default_factory=PRSignalsConfig)
    active_refs_enabled: bool = False
    active_ref_ttl_hours: int = 72
    context_freshness_warning_seconds: int = DEFAULT_CONTEXT_FRESHNESS_WARNING_SECONDS
    context_stale_after_seconds: int = DEFAULT_CONTEXT_STALE_AFTER_SECONDS
    context_default_mode: str = DEFAULT_CONTEXT_MODE
    context_budget_mode: str = DEFAULT_CONTEXT_BUDGET_MODE
    startup_max_entries: int = DEFAULT_STARTUP_MAX_ENTRIES
    value_ledger_enabled: bool = False
    value_ledger_path: str | None = None
    value_ledger_retention_days: int = DEFAULT_VALUE_LEDGER_RETENTION_DAYS
    revise_keywords: tuple[str, ...] | None = None
    handoff_keywords: tuple[str, ...] | None = None
    disabled: bool = False
    muted_scopes: ScopeMutePolicy = field(default_factory=ScopeMutePolicy)
    entry_feedback: dict[str, str] = field(default_factory=dict)


def load_config_from_env() -> AmbaraConfig:
    env_disabled = os.environ.get("AMBARA_DISABLED", "").lower() == "true"
    project_config = {} if env_disabled else _project_config_data()
    disabled = env_disabled or _project_config_disabled(project_config)
    muted_scopes = ScopeMutePolicy.from_raw(project_config.get("muted_scopes"))
    entry_feedback = _entry_feedback_from_config(project_config)
    remote_url = os.environ.get("AMBARA_KNOWLEDGE_REMOTE")
    if not remote_url or not remote_url.strip():
        remote_url = _config_str(project_config.get("knowledge_remote"))
        if disabled and remote_url is None:
            remote_url = ""
        elif remote_url is None:
            raise ValueError("AMBARA_KNOWLEDGE_REMOTE environment variable is required")
    else:
        remote_url = remote_url.strip()

    if not remote_url and not disabled:
        raise ValueError("AMBARA_KNOWLEDGE_REMOTE environment variable is required")

    if disabled:
        return AmbaraConfig(
            remote_url=remote_url,
            cache_dir=os.environ.get("AMBARA_CACHE_DIR", os.path.expanduser("~/.cache/ambara")),
            disabled=True,
            value_ledger_enabled=False,
            muted_scopes=muted_scopes,
            entry_feedback=entry_feedback,
        )

    branch_prefix = os.environ.get("AMBARA_BRANCH_PREFIX") or _config_str(
        project_config.get("branch_prefix")
    ) or "ambara"
    active_ref_prefix = os.environ.get("AMBARA_ACTIVE_REF_PREFIX") or _config_str(
        project_config.get("active_ref_prefix")
    ) or "ambara/active"

    main_branch = os.environ.get("AMBARA_MAIN_BRANCH") or _config_str(
        project_config.get("main_branch")
    ) or "main"
    client_slug = os.environ.get("AMBARA_CLIENT_SLUG", "claude-code")

    for name, value in [
        ("branch_prefix", branch_prefix),
        ("active_ref_prefix", active_ref_prefix),
        ("main_branch", main_branch),
        ("client_slug", client_slug),
    ]:
        if ".." in value or not _SAFE_PREFIX_PATTERN.match(value):
            raise ValueError(f"Invalid {name}: {value!r}")

    sync_interval_str = os.environ.get("AMBARA_SYNC_INTERVAL", "300")
    try:
        sync_interval = int(sync_interval_str)
    except ValueError:
        raise ValueError(
            f"AMBARA_SYNC_INTERVAL must be an integer, got {sync_interval_str!r}"
        ) from None
    if sync_interval < 1:
        raise ValueError(f"sync_interval must be >= 1, got {sync_interval}")

    active_ref_ttl_hours_str = os.environ.get("AMBARA_ACTIVE_REF_TTL_HOURS")
    if active_ref_ttl_hours_str is not None:
        try:
            active_ref_ttl_hours = int(active_ref_ttl_hours_str)
        except ValueError:
            raise ValueError(
                f"AMBARA_ACTIVE_REF_TTL_HOURS must be an integer, got {active_ref_ttl_hours_str!r}"
            ) from None
    else:
        active_ref_ttl_hours = _config_active_ref_ttl_hours(project_config) or 72
    if not 1 <= active_ref_ttl_hours <= MAX_ACTIVE_REF_TTL_HOURS:
        raise ValueError(
            "active_ref_ttl_hours must be between 1 and "
            f"{MAX_ACTIVE_REF_TTL_HOURS}, got {active_ref_ttl_hours}"
        )

    freshness_warning_seconds = _parse_int_env(
        "AMBARA_CONTEXT_FRESHNESS_WARNING_SECONDS",
        DEFAULT_CONTEXT_FRESHNESS_WARNING_SECONDS,
    )
    if freshness_warning_seconds < 0:
        raise ValueError(
            f"context_freshness_warning_seconds must be >= 0, got {freshness_warning_seconds}"
        )

    context_stale_after_seconds = _parse_int_env(
        "AMBARA_CONTEXT_STALE_AFTER_SECONDS",
        DEFAULT_CONTEXT_STALE_AFTER_SECONDS,
    )
    if context_stale_after_seconds <= freshness_warning_seconds:
        raise ValueError(
            "context_stale_after_seconds must be greater than context_freshness_warning_seconds"
        )

    startup_v2_enabled = os.environ.get("AMBARA_STARTUP_V2_ENABLED", "").lower() == "true"
    raw_context_default_mode = os.environ.get("AMBARA_CONTEXT_DEFAULT_MODE")
    if raw_context_default_mode is not None:
        context_default_mode = raw_context_default_mode.strip()
    elif startup_v2_enabled:
        context_default_mode = "startup"
    else:
        context_default_mode = DEFAULT_CONTEXT_MODE
    if context_default_mode not in VALID_CONTEXT_MODES:
        valid_modes = ", ".join(sorted(VALID_CONTEXT_MODES))
        raise ValueError(
            f"AMBARA_CONTEXT_DEFAULT_MODE must be one of: {valid_modes}; "
            f"got {context_default_mode!r}"
        )
    context_budget_mode = os.environ.get(
        "AMBARA_CONTEXT_BUDGET_MODE", DEFAULT_CONTEXT_BUDGET_MODE
    ).strip()
    if context_budget_mode not in VALID_CONTEXT_BUDGET_MODES:
        valid_modes = ", ".join(sorted(VALID_CONTEXT_BUDGET_MODES))
        raise ValueError(
            f"AMBARA_CONTEXT_BUDGET_MODE must be one of: {valid_modes}; got {context_budget_mode!r}"
        )

    signal_provider = os.environ.get("AMBARA_SIGNAL_PROVIDER", "github")

    pr_signal_repos_raw = os.environ.get("AMBARA_PR_SIGNAL_REPOS", "")
    pr_signal_repos = tuple(r.strip() for r in pr_signal_repos_raw.split(",") if r.strip())
    pr_signal_fixture = os.environ.get("AMBARA_PR_SIGNAL_FIXTURE") or None

    gitlab_base_url = os.environ.get("AMBARA_GITLAB_BASE_URL") or None
    jira_base_url = os.environ.get("AMBARA_JIRA_BASE_URL") or None
    jira_projects_raw = os.environ.get("AMBARA_JIRA_PROJECTS", "")
    jira_projects = tuple(p.strip() for p in jira_projects_raw.split(",") if p.strip())

    active_refs_enabled_env = os.environ.get("AMBARA_ACTIVE_REFS_ENABLED")
    active_refs_enabled = (
        active_refs_enabled_env.lower() == "true"
        if active_refs_enabled_env is not None
        else _config_active_refs_enabled(project_config) is True
    )

    startup_max_entries = min(
        _parse_int_env("AMBARA_STARTUP_MAX_ENTRIES", DEFAULT_STARTUP_MAX_ENTRIES),
        MAX_STARTUP_ENTRIES,
    )
    value_ledger_path = os.environ.get("AMBARA_VALUE_LEDGER_PATH") or None
    raw_value_ledger_enabled = os.environ.get("AMBARA_VALUE_LEDGER_ENABLED")
    value_ledger_enabled = (
        raw_value_ledger_enabled.lower() == "true"
        if raw_value_ledger_enabled is not None
        else value_ledger_path is not None
    )
    value_ledger_retention_days = _parse_int_env(
        "AMBARA_VALUE_LEDGER_RETENTION_DAYS",
        DEFAULT_VALUE_LEDGER_RETENTION_DAYS,
    )
    if value_ledger_retention_days < 1:
        raise ValueError(
            f"value_ledger_retention_days must be >= 1, got {value_ledger_retention_days}"
        )

    revise_raw = os.environ.get("AMBARA_REVISE_KEYWORDS", "")
    revise_keywords = (
        tuple(k.strip() for k in revise_raw.split(",") if k.strip()) if revise_raw else None
    )
    handoff_raw = os.environ.get("AMBARA_HANDOFF_KEYWORDS", "")
    handoff_keywords = (
        tuple(k.strip() for k in handoff_raw.split(",") if k.strip()) if handoff_raw else None
    )

    return AmbaraConfig(
        remote_url=remote_url,
        cache_dir=os.environ.get("AMBARA_CACHE_DIR", os.path.expanduser("~/.cache/ambara")),
        main_branch=main_branch,
        branch_prefix=branch_prefix,
        active_ref_prefix=active_ref_prefix,
        sync_interval=sync_interval,
        client_slug=client_slug,
        pr_signals=PRSignalsConfig(
            provider=signal_provider,
            repos=pr_signal_repos,
            fixture_path=pr_signal_fixture,
            gitlab_base_url=gitlab_base_url,
            jira_base_url=jira_base_url,
            jira_projects=jira_projects,
        ),
        active_refs_enabled=active_refs_enabled,
        active_ref_ttl_hours=active_ref_ttl_hours,
        startup_max_entries=startup_max_entries,
        context_budget_mode=context_budget_mode,
        value_ledger_enabled=value_ledger_enabled,
        value_ledger_path=value_ledger_path,
        value_ledger_retention_days=value_ledger_retention_days,
        context_freshness_warning_seconds=freshness_warning_seconds,
        context_stale_after_seconds=context_stale_after_seconds,
        context_default_mode=context_default_mode,
        revise_keywords=revise_keywords,
        handoff_keywords=handoff_keywords,
        disabled=disabled,
        muted_scopes=muted_scopes,
        entry_feedback=entry_feedback,
    )


def _parse_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None


def _project_config_data(path: Path | None = None) -> dict[str, object]:
    config_path = path or Path.cwd() / ".ambara" / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        loaded: object = frontmatter.default_handlers.YAMLHandler().load(config_path.read_text())
    except Exception as exc:
        raise ValueError(f"Could not parse project config {config_path}: {exc}") from exc
    if not isinstance(loaded, dict):
        return {}
    return {key: value for key, value in loaded.items() if isinstance(key, str)}


def _project_config_disabled(data: dict[str, object]) -> bool:
    if not data:
        return False

    enabled = data.get("enabled")
    if isinstance(enabled, bool):
        return not enabled
    disabled = data.get("disabled")
    if isinstance(disabled, bool):
        return disabled
    return False


def _config_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _config_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _config_active_refs_enabled(data: dict[str, object]) -> bool | None:
    active_refs = data.get("active_refs")
    if isinstance(active_refs, dict):
        enabled = _config_bool(active_refs.get("enabled"))
        if enabled is not None:
            return enabled
    enabled = _config_bool(data.get("active_refs_enabled"))
    if enabled is not None:
        return enabled
    expiry = data.get("expiry")
    if isinstance(expiry, dict):
        return _config_bool(expiry.get("active_refs_enabled"))
    return None


def _config_active_ref_ttl_hours(data: dict[str, object]) -> int | None:
    active_refs = data.get("active_refs")
    if isinstance(active_refs, dict):
        ttl = _config_ttl_hours(active_refs.get("ttl_hours"))
        if ttl is not None:
            return ttl
    expiry = data.get("expiry")
    if isinstance(expiry, dict):
        return _config_ttl_hours(expiry.get("active_ttl_hours"))
    return None


def _config_ttl_hours(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _entry_feedback_from_config(data: dict[str, object]) -> dict[str, str]:
    raw = data.get("entry_feedback")
    if not isinstance(raw, dict):
        return {}
    allowed = {
        "not_useful",
        "duplicate",
        "stale",
        "useful",
        "pin",
        "mute_for_repo",
        "mute_for_session",
    }
    feedback: dict[str, str] = {}
    for raw_entry_id, raw_signal in raw.items():
        if not isinstance(raw_entry_id, str) or not raw_entry_id.strip():
            continue
        if not isinstance(raw_signal, str):
            continue
        signal = raw_signal.strip().lower().replace("-", "_")
        if signal in allowed:
            feedback[raw_entry_id.strip()] = signal
    return feedback
