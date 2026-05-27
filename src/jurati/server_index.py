"""Index-cache helpers for the MCP server facade."""

from __future__ import annotations

from datetime import UTC, datetime

from jurati.core.schema import Entry
from jurati.core.scoring import InvertedIndex, build_inverted_index
from jurati.server_snapshot import build_context_snapshot
from jurati.server_state import ContextSnapshot, ServerState


def _set_context_snapshot(state: ServerState, snapshot: ContextSnapshot) -> None:
    state.context_snapshot = snapshot
    state._cached_bm25_index = snapshot.bm25_index
    state._cached_bm25_index_generation = snapshot.index_generation


def _get_context_snapshot(state: ServerState, *, now: datetime) -> ContextSnapshot:
    snapshot = state.context_snapshot
    if snapshot is None or snapshot.index_generation != state._index_generation:
        snapshot = build_context_snapshot(state, now=now)
        _set_context_snapshot(state, snapshot)
    return snapshot


def _rebuild_context_snapshot(state: ServerState, *, now: datetime | None = None) -> None:
    _set_context_snapshot(state, build_context_snapshot(state, now=now or datetime.now(UTC)))


def _get_bm25_index(state: ServerState) -> InvertedIndex:
    snapshot = state.context_snapshot
    if snapshot is not None and snapshot.index_generation == state._index_generation:
        state._cached_bm25_index = snapshot.bm25_index
        state._cached_bm25_index_generation = snapshot.index_generation
        return snapshot.bm25_index

    if (
        state._cached_bm25_index is None
        or state._cached_bm25_index_generation != state._index_generation
    ):
        all_entries = list(state.index.entries.values())
        state._cached_bm25_index = build_inverted_index(all_entries)
        state._cached_bm25_index_generation = state._index_generation
    return state._cached_bm25_index


def _invalidate_index_cache(state: ServerState) -> None:
    state._cached_bm25_index = None
    state._cached_bm25_index_generation = -1
    state.context_snapshot = None
    state._index_generation += 1


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
