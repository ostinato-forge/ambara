"""Shared MCP server state models."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

from jurati.core.content_policy import WritePolicy
from jurati.core.content_policy_config import ContentPolicyConfig
from jurati.core.index import Index
from jurati.core.scoring import InvertedIndex
from jurati.git.auth import AuthCandidate
from jurati.git.config import JuratiConfig
from jurati.providers.cache import SignalCache


@dataclass
class SyncHealth:
    last_success: datetime | None = None
    last_failure: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0


@dataclass
class ServerState:
    config: JuratiConfig
    repo_path: str
    index: Index
    last_sync: datetime
    sync_health: SyncHealth
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    cached_pr_candidate: AuthCandidate | None = None
    signal_cache: SignalCache = field(default_factory=lambda: SignalCache(recency_days=30))
    content_policy: WritePolicy | None = field(default=None, repr=False)
    content_policy_config: ContentPolicyConfig | None = field(default=None, repr=False)
    _cached_bm25_index: InvertedIndex | None = field(default=None, repr=False)
    _cached_bm25_index_generation: int = field(default=-1, repr=False)
    _index_generation: int = field(default=0, repr=False)
