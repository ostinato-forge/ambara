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
from ambara.core.schema import Entry
from ambara.core.scoring import InvertedIndex
from ambara.git.auth import AuthCandidate
from ambara.git.config import AmbaraConfig
from ambara.sources.cache import SourceCache
from ambara.sources.inspect import SourceInspectionReport
from ambara.sources.types import SourceArtifact


@dataclass
class SyncHealth:
    last_success: datetime | None = None
    last_failure: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0


@dataclass
class SourceRefreshHealth:
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
    source_artifacts: tuple[SourceArtifact, ...] = ()
    source_advisories: tuple[CurationAdvisory, ...] = ()
    muted_entries_hidden: int = 0
    retired_entries_hidden: int = 0
    muted_source_inputs_hidden: int = 0


@dataclass
class IndexCache:
    snapshot: ContextSnapshot | None = None
    generation: int = 0
    _bm25_index: InvertedIndex | None = field(default=None, repr=False)
    _bm25_generation: int = field(default=-1, repr=False)
    _entry_graph: EntryGraph | None = field(default=None, repr=False)
    _entry_graph_generation: int = field(default=-1, repr=False)


@dataclass(init=False)
class ServerState:
    config: AmbaraConfig
    repo_path: str
    index: Index
    last_sync: datetime
    sync_health: SyncHealth
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    cached_pr_candidate: AuthCandidate | None = None
    source_health: SourceRefreshHealth = field(default_factory=SourceRefreshHealth)
    source_cache: SourceCache = field(default_factory=SourceCache)
    source_report: SourceInspectionReport | None = None
    source_report_last_refresh: datetime | None = None
    cache: IndexCache = field(default_factory=IndexCache)
    content_policy: WritePolicy | None = field(default=None, repr=False)
    content_policy_config: ContentPolicyConfig | None = field(default=None, repr=False)
    _index_tree_hash: str | None = field(default=None, repr=False)
    _last_fetch_at: datetime | None = field(default=None, repr=False)
    seen_context_entries: dict[str, datetime] = field(default_factory=dict, repr=False)
    feedback_signals: dict[str, str] = field(default_factory=dict, repr=False)

    def __init__(
        self,
        config: AmbaraConfig,
        repo_path: str,
        index: Index,
        last_sync: datetime,
        sync_health: SyncHealth,
        *,
        write_lock: threading.Lock | None = None,
        cached_pr_candidate: AuthCandidate | None = None,
        source_health: SourceRefreshHealth | None = None,
        source_cache: SourceCache | None = None,
        source_report: SourceInspectionReport | None = None,
        source_report_last_refresh: datetime | None = None,
        cache: IndexCache | None = None,
        content_policy: WritePolicy | None = None,
        content_policy_config: ContentPolicyConfig | None = None,
        _index_tree_hash: str | None = None,
        _last_fetch_at: datetime | None = None,
        seen_context_entries: dict[str, datetime] | None = None,
        feedback_signals: dict[str, str] | None = None,
    ) -> None:
        self.config = config
        self.repo_path = repo_path
        self.index = index
        self.last_sync = last_sync
        self.sync_health = sync_health
        self.write_lock = write_lock or threading.Lock()
        self.cached_pr_candidate = cached_pr_candidate
        self.source_health = source_health or SourceRefreshHealth()
        self.source_cache = source_cache or SourceCache()
        self.source_report = source_report
        self.source_report_last_refresh = source_report_last_refresh
        self.cache = cache or IndexCache()
        self.content_policy = content_policy
        self.content_policy_config = content_policy_config
        self._index_tree_hash = _index_tree_hash
        self._last_fetch_at = _last_fetch_at
        self.seen_context_entries = seen_context_entries or {}
        self.feedback_signals = feedback_signals or {}
