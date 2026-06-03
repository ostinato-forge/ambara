"""Index-cache helpers for the MCP server facade."""

from __future__ import annotations

from datetime import UTC, datetime

from ambara.core.schema import Entry
from ambara.core.scoring import InvertedIndex, build_inverted_index
from ambara.server_snapshot import build_context_snapshot
from ambara.server_state import ContextSnapshot, ServerState


def _set_context_snapshot(state: ServerState, snapshot: ContextSnapshot) -> None:
    cache = state.cache
    cache.snapshot = snapshot
    cache._bm25_index = snapshot.bm25_index
    cache._bm25_generation = snapshot.index_generation


def _get_context_snapshot(state: ServerState, *, now: datetime) -> ContextSnapshot | None:
    cache = state.cache
    snapshot = cache.snapshot
    if snapshot is None or snapshot.index_generation != cache.generation:
        return None
    return snapshot


def _rebuild_context_snapshot(state: ServerState, *, now: datetime | None = None) -> None:
    _set_context_snapshot(state, build_context_snapshot(state, now=now or datetime.now(UTC)))


def _get_bm25_index(state: ServerState) -> InvertedIndex:
    cache = state.cache
    snapshot = cache.snapshot
    if snapshot is not None and snapshot.index_generation == cache.generation:
        cache._bm25_index = snapshot.bm25_index
        cache._bm25_generation = snapshot.index_generation
        return snapshot.bm25_index

    if cache._bm25_index is None or cache._bm25_generation != cache.generation:
        all_entries = list(state.index.entries.values())
        cache._bm25_index = build_inverted_index(all_entries)
        cache._bm25_generation = cache.generation
    return cache._bm25_index


def _invalidate_index_cache(state: ServerState) -> None:
    cache = state.cache
    cache._bm25_index = None
    cache._bm25_generation = -1
    cache.snapshot = None
    cache.generation += 1


def _add_entry_to_index(state: ServerState, entry: Entry) -> None:
    state.index.add(entry)
    _invalidate_index_cache(state)
    _rebuild_context_snapshot(state)


def _remove_entry_from_index(state: ServerState, entry_id: str) -> Entry | None:
    removed = state.index.remove(entry_id)
    if removed is not None:
        _invalidate_index_cache(state)
        _rebuild_context_snapshot(state)
    return removed
