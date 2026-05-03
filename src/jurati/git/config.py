"""Configuration for the jurati server and git operations."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

_SAFE_PREFIX_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9/_-]{0,100}$")


@dataclass(frozen=True)
class JuratiConfig:
    remote_url: str
    cache_dir: str = os.path.expanduser("~/.cache/jurati")
    main_branch: str = "main"
    branch_prefix: str = "jurati"
    active_ref_prefix: str = "jurati/active"
    sync_interval: int = 300
    client_slug: str | None = "claude-code"


def load_config_from_env() -> JuratiConfig:
    remote_url = os.environ.get("JURATI_KNOWLEDGE_REMOTE")
    if not remote_url:
        raise ValueError("JURATI_KNOWLEDGE_REMOTE environment variable is required")

    branch_prefix = os.environ.get("JURATI_BRANCH_PREFIX", "jurati")
    active_ref_prefix = os.environ.get("JURATI_ACTIVE_REF_PREFIX", "jurati/active")

    for name, value in [("branch_prefix", branch_prefix), ("active_ref_prefix", active_ref_prefix)]:
        if ".." in value or not _SAFE_PREFIX_PATTERN.match(value):
            raise ValueError(f"Invalid {name}: {value!r}")

    sync_interval = int(os.environ.get("JURATI_SYNC_INTERVAL", "300"))
    if sync_interval < 1:
        raise ValueError(f"sync_interval must be >= 1, got {sync_interval}")

    return JuratiConfig(
        remote_url=remote_url,
        cache_dir=os.environ.get(
            "JURATI_CACHE_DIR", os.path.expanduser("~/.cache/jurati")
        ),
        main_branch=os.environ.get("JURATI_MAIN_BRANCH", "main"),
        branch_prefix=branch_prefix,
        active_ref_prefix=active_ref_prefix,
        sync_interval=sync_interval,
        client_slug=os.environ.get("JURATI_CLIENT_SLUG", "claude-code"),
    )
