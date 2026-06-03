# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Ed Parenti

"""Shared MCP server state models."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

from ambara.core.content_policy import WritePolicy
from ambara.core.content_policy_config import ContentPolicyConfig
from ambara.core.curation import CurationAdvisory
from ambara.core.graph import EntryGraph
from ambara.core.hygiene import HygieneReport
from ambara.core.index import Index
from ambara.core.pr_signals import CoordinationSignal, PRSignal
from ambara.core.schema import Entry
from ambara.core.scoring import InvertedIndex
from ambara.git.auth import AuthCandidate
from ambara.git.config import AmbaraConfig
from ambara.providers.cache import SignalCache


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
    muted_entries_hidden: int = 0
    retired_entries_hidden: int = 0
    muted_signals_hidden: int = 0


@dataclass
class IndexCache:
    snapshot: ContextSnapshot | None = None
    generation: int = 0
    _bm25_index: InvertedIndex | None = field(default=None, repr=False)
    _bm25_generation: int = field(default=-1, repr=False)
    _entry_graph: EntryGraph | None = field(default=None, repr=False)
    _entry_graph_generation: int = field(default=-1, repr=False)


@dataclass
class ServerState:
    config: AmbaraConfig
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
    seen_context_entries: dict[str, datetime] = field(default_factory=dict, repr=False)
    feedback_signals: dict[str, str] = field(default_factory=dict, repr=False)
