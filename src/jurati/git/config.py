"""Configuration for the jurati server and git operations."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

_SAFE_PREFIX_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,100}$")
MAX_ACTIVE_REF_TTL_HOURS = 168
DEFAULT_CONTEXT_FRESHNESS_WARNING_SECONDS = 300
DEFAULT_CONTEXT_STALE_AFTER_SECONDS = 900
DEFAULT_CONTEXT_MODE = "manifest"
VALID_CONTEXT_MODES = frozenset({"compiler", "full", "manifest", "startup"})
DEFAULT_STARTUP_MAX_ENTRIES = 3
MAX_STARTUP_ENTRIES = 5


@dataclass(frozen=True)
class PRSignalsConfig:
    provider: str = "github"
    label: str = "jurati"
    recency_days: int = 30
    repos: tuple[str, ...] = ()
    fixture_path: str | None = None
    include_body_excerpt: bool = True
    include_changed_paths: bool = True
    jira_base_url: str | None = None
    jira_projects: tuple[str, ...] = ()


@dataclass(frozen=True)
class JuratiConfig:
    remote_url: str
    cache_dir: str = os.path.expanduser("~/.cache/jurati")
    main_branch: str = "main"
    branch_prefix: str = "jurati"
    active_ref_prefix: str = "jurati/active"
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
    startup_v2_enabled: bool = False
    startup_max_entries: int = DEFAULT_STARTUP_MAX_ENTRIES
    revise_keywords: tuple[str, ...] | None = None
    handoff_keywords: tuple[str, ...] | None = None


def load_config_from_env() -> JuratiConfig:
    remote_url = os.environ.get("JURATI_KNOWLEDGE_REMOTE")
    if not remote_url or not remote_url.strip():
        raise ValueError("JURATI_KNOWLEDGE_REMOTE environment variable is required")

    branch_prefix = os.environ.get("JURATI_BRANCH_PREFIX", "jurati")
    active_ref_prefix = os.environ.get("JURATI_ACTIVE_REF_PREFIX", "jurati/active")

    main_branch = os.environ.get("JURATI_MAIN_BRANCH", "main")
    client_slug = os.environ.get("JURATI_CLIENT_SLUG", "claude-code")

    for name, value in [
        ("branch_prefix", branch_prefix),
        ("active_ref_prefix", active_ref_prefix),
        ("main_branch", main_branch),
        ("client_slug", client_slug),
    ]:
        if ".." in value or not _SAFE_PREFIX_PATTERN.match(value):
            raise ValueError(f"Invalid {name}: {value!r}")

    sync_interval_str = os.environ.get("JURATI_SYNC_INTERVAL", "300")
    try:
        sync_interval = int(sync_interval_str)
    except ValueError:
        raise ValueError(
            f"JURATI_SYNC_INTERVAL must be an integer, got {sync_interval_str!r}"
        ) from None
    if sync_interval < 1:
        raise ValueError(f"sync_interval must be >= 1, got {sync_interval}")

    active_ref_ttl_hours_str = os.environ.get("JURATI_ACTIVE_REF_TTL_HOURS", "72")
    try:
        active_ref_ttl_hours = int(active_ref_ttl_hours_str)
    except ValueError:
        raise ValueError(
            f"JURATI_ACTIVE_REF_TTL_HOURS must be an integer, got {active_ref_ttl_hours_str!r}"
        ) from None
    if not 1 <= active_ref_ttl_hours <= MAX_ACTIVE_REF_TTL_HOURS:
        raise ValueError(
            "active_ref_ttl_hours must be between 1 and "
            f"{MAX_ACTIVE_REF_TTL_HOURS}, got {active_ref_ttl_hours}"
        )

    freshness_warning_seconds = _parse_int_env(
        "JURATI_CONTEXT_FRESHNESS_WARNING_SECONDS",
        DEFAULT_CONTEXT_FRESHNESS_WARNING_SECONDS,
    )
    if freshness_warning_seconds < 0:
        raise ValueError(
            f"context_freshness_warning_seconds must be >= 0, got {freshness_warning_seconds}"
        )

    context_stale_after_seconds = _parse_int_env(
        "JURATI_CONTEXT_STALE_AFTER_SECONDS",
        DEFAULT_CONTEXT_STALE_AFTER_SECONDS,
    )
    if context_stale_after_seconds <= freshness_warning_seconds:
        raise ValueError(
            "context_stale_after_seconds must be greater than context_freshness_warning_seconds"
        )

    context_default_mode = os.environ.get(
        "JURATI_CONTEXT_DEFAULT_MODE", DEFAULT_CONTEXT_MODE
    ).strip()
    if context_default_mode not in VALID_CONTEXT_MODES:
        valid_modes = ", ".join(sorted(VALID_CONTEXT_MODES))
        raise ValueError(
            f"JURATI_CONTEXT_DEFAULT_MODE must be one of: {valid_modes}; "
            f"got {context_default_mode!r}"
        )

    signal_provider = os.environ.get("JURATI_SIGNAL_PROVIDER", "github")

    pr_signal_repos_raw = os.environ.get("JURATI_PR_SIGNAL_REPOS", "")
    pr_signal_repos = tuple(r.strip() for r in pr_signal_repos_raw.split(",") if r.strip())
    pr_signal_fixture = os.environ.get("JURATI_PR_SIGNAL_FIXTURE") or None

    jira_base_url = os.environ.get("JURATI_JIRA_BASE_URL") or None
    jira_projects_raw = os.environ.get("JURATI_JIRA_PROJECTS", "")
    jira_projects = tuple(p.strip() for p in jira_projects_raw.split(",") if p.strip())

    active_refs_enabled = os.environ.get("JURATI_ACTIVE_REFS_ENABLED", "").lower() == "true"

    startup_v2_enabled = os.environ.get("JURATI_STARTUP_V2_ENABLED", "").lower() == "true"
    startup_max_entries = min(
        _parse_int_env("JURATI_STARTUP_MAX_ENTRIES", DEFAULT_STARTUP_MAX_ENTRIES),
        MAX_STARTUP_ENTRIES,
    )

    revise_raw = os.environ.get("JURATI_REVISE_KEYWORDS", "")
    revise_keywords = (
        tuple(k.strip() for k in revise_raw.split(",") if k.strip()) if revise_raw else None
    )
    handoff_raw = os.environ.get("JURATI_HANDOFF_KEYWORDS", "")
    handoff_keywords = (
        tuple(k.strip() for k in handoff_raw.split(",") if k.strip()) if handoff_raw else None
    )

    return JuratiConfig(
        remote_url=remote_url,
        cache_dir=os.environ.get("JURATI_CACHE_DIR", os.path.expanduser("~/.cache/jurati")),
        main_branch=main_branch,
        branch_prefix=branch_prefix,
        active_ref_prefix=active_ref_prefix,
        sync_interval=sync_interval,
        client_slug=client_slug,
        pr_signals=PRSignalsConfig(
            provider=signal_provider,
            repos=pr_signal_repos,
            fixture_path=pr_signal_fixture,
            jira_base_url=jira_base_url,
            jira_projects=jira_projects,
        ),
        active_refs_enabled=active_refs_enabled,
        active_ref_ttl_hours=active_ref_ttl_hours,
        startup_v2_enabled=startup_v2_enabled,
        startup_max_entries=startup_max_entries,
        context_freshness_warning_seconds=freshness_warning_seconds,
        context_stale_after_seconds=context_stale_after_seconds,
        context_default_mode=context_default_mode,
        revise_keywords=revise_keywords,
        handoff_keywords=handoff_keywords,
    )


def _parse_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None
