"""Configuration for the jurati server and git operations."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class JuratiConfig:
    remote_url: str
    cache_dir: str = os.path.expanduser("~/.cache/jurati")
    main_branch: str = "main"
    branch_prefix: str = "jurati"
    active_ref_prefix: str = "jurati/active"
    sync_interval: int = 300
    client_slug: str | None = None


def load_config_from_env() -> JuratiConfig:
    remote_url = os.environ.get("JURATI_KNOWLEDGE_REMOTE")
    if not remote_url:
        raise ValueError("JURATI_KNOWLEDGE_REMOTE environment variable is required")

    return JuratiConfig(
        remote_url=remote_url,
        cache_dir=os.environ.get(
            "JURATI_CACHE_DIR", os.path.expanduser("~/.cache/jurati")
        ),
        main_branch=os.environ.get("JURATI_MAIN_BRANCH", "main"),
        branch_prefix=os.environ.get("JURATI_BRANCH_PREFIX", "jurati"),
        active_ref_prefix=os.environ.get("JURATI_ACTIVE_REF_PREFIX", "jurati/active"),
        sync_interval=int(os.environ.get("JURATI_SYNC_INTERVAL", "300")),
        client_slug=os.environ.get("JURATI_CLIENT_SLUG", "claude-code"),
    )
