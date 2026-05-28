"""Shared MCP server state models."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

from jurati.core.content_policy import WritePolicy
from jurati.core.content_policy_config import ContentPolicyConfig
from jurati.core.curation import CurationAdvisory
from jurati.core.hygiene import HygieneReport
from jurati.core.index import Index
from jurati.core.pr_signals import CoordinationSignal, PRSignal
from jurati.core.schema import Entry
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
class SignalHealth:
    last_success: datetime | None = None
    last_failure: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0


@dataclass(frozen=True)
class ContextSnapshot:
    built_at: datetime
    index_generation: int
    index: Index
    total_entries: int
    hidden_restricted_entries: int
    bm25_index: InvertedIndex
    visible_entries: tuple[Entry, ...]
    hygiene_report: HygieneReport
    signals: tuple[PRSignal | CoordinationSignal, ...] = ()
    signal_advisories: tuple[CurationAdvisory, ...] = ()


@dataclass
class IndexCache:
    snapshot: ContextSnapshot | None = None
    generation: int = 0
    _bm25_index: InvertedIndex | None = field(default=None, repr=False)
    _bm25_generation: int = field(default=-1, repr=False)


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
    signal_health: SignalHealth = field(default_factory=SignalHealth)
    cache: IndexCache = field(default_factory=IndexCache)
    content_policy: WritePolicy | None = field(default=None, repr=False)
    content_policy_config: ContentPolicyConfig | None = field(default=None, repr=False)
    _index_tree_hash: str | None = field(default=None, repr=False)
    _last_fetch_at: datetime | None = field(default=None, repr=False)
