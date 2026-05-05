# Jurati Evolution Spec: From Tool to Platform Component

**Date:** 2026-05-05
**Status:** Draft — revision 1
**Author:** Edgar Parenti
**Supersedes:** None (additive to `2026-05-02-jurati-design.md`)

## Context

Three rounds of expert design review (MIT Professor, Staff Engineer, Privacy/Ethics Researcher, DX Practitioner) — each reading the full codebase and 42 stress test issues — converge on one conclusion: **jurati's core architecture is sound, but it needs to evolve from a standalone tool into a generic platform component for human+agent teams.**

Jurati is open source. It must work for any company adopting agentic workflows — engineering, legal, compliance, training, product. It cannot assume any specific orchestration system (Temporal, egon), gate framework (four-eyes), or provider (GitHub). Every integration point must be a generic interface that specific systems implement.

---

## 1. What Stays (Sound Foundations)

These are architecturally validated and remain unchanged:

- **Pure/IO split**: `core/` has zero I/O imports; `git/` is the sole I/O boundary.
- **Entry types**: PRINCIPLE, DECISION, WORKFLOW, PROJECT, ACTIVE — domain-neutral knowledge durability categories.
- **Escalation levels L0–L3**: Control persistence ceremony (which git ref, whether PR created). Orthogonal to any gate system's advancement authority.
- **`record()` / `propose()` separation**: Lower-stakes tools cannot create higher-stakes content and vice versa.
- **Privacy boundary**: No query logging, read receipts, participation metrics, or inferred presence. The implementation matches the promise (verified by code review).
- **WriteIntent / ExpireIntent pattern**: Pure planning in `core/changes.py` produces intent objects; `git/commit.py` materializes them.
- **BM25 search with multi-signal scoring**: Recency decay, type weights, repo affinity, exact-match boost.
- **PR signal classification**: 6 effects (continue, reuse, revise, pause, handoff, clarify) with urgency/confidence — pure, deterministic.
- **Git-backed provenance**: All writes produce git commits. PRs are the review surface.

---

## 2. Schema Evolution

### 2a. Schema versioning: backward compatibility, not migration

Bump `schema_version` default from `1` to `2` for new entries. Existing v1 entries in the knowledge repo are **not rewritten**. Pydantic applies defaults for fields absent from v1 frontmatter (`visibility = INTERNAL`, `recorded_by = None`). The parsed `schema_version` stays `1` on those entries — it is a provenance marker, not a format gate.

This is **backward compatibility**, not migration. There is no schema normalization pass. Code must handle v1 and v2 entries identically after Pydantic defaults are applied. The version number exists so tooling can distinguish "written before visibility existed" from "author intentionally chose INTERNAL."

### 2b. `visibility` field

Author-side declaration of cross-system distribution consent.

```python
class Visibility(StrEnum):
    INTERNAL = "internal"   # visible within jurati's own MCP tools only (default)
    EXTERNAL = "external"   # explicitly opts in to cross-system distribution
```

Added to `Frontmatter`: `visibility: Visibility = Visibility.INTERNAL`

**Visibility is an explicit author/tool input, not a hard-coded default by level.** The rules:

- L0 (active) entries: always `INTERNAL`. Enforced in `plan_record()` — cannot be overridden. L0 is ephemeral presence-adjacent data; it must never automatically propagate externally.
- L1 (project) entries: default `INTERNAL`. The author or calling tool may explicitly set `EXTERNAL` when the entry is intended for cross-system consumption. `plan_record()` and the MCP `record()` tool accept an optional `visibility` parameter.
- L2/L3 (reviewed) entries: default `EXTERNAL`. The author or calling tool may explicitly set `INTERNAL` to keep a decision private to jurati's own tools. `plan_propose()` and the MCP `propose()` tool accept an optional `visibility` parameter.

**Validation**: `core/validate.py` rejects `restricted` entries with `visibility = EXTERNAL`. L0 entries with `visibility = EXTERNAL` are rejected.

The integration contract (section 7) filters entries by visibility through **named access modes** — see section 7a.

### 2c. Provenance metadata

Split the single `authored_by` concept into two distinct, honest fields:

```python
class RecordedBy(BaseModel, frozen=True):
    """Which MCP client submitted the write. Populated automatically."""
    client: str       # client_slug (e.g., "claude-code", "cursor")
```

- `recorded_by: RecordedBy | None = None` — which MCP client submitted. Always populated on new writes. Mechanical fact, not an authorship claim.
- `source: SourceMeta | None = None` — already exists. Git provenance from ambient capture (repo, commit, author). This is the asserted human author for captured content.

`ActorKind` is derived at read time, not stored:
- If `source` is present → `HUMAN`
- If `recorded_by` is present and `source` is absent → `AGENT`
- If both are present → `PAIR`

**Privacy caveat**: `opaque_identity()` (section 5c) salts `recorded_by.client` and `source.author` at the integration boundary. But raw git history and raw markdown in the knowledge repo still expose identities to anyone with repo access. The privacy boundary is at the API layer, not the storage layer.

### 2d. Sensitivity enforcement

The `Sensitivity` enum (NORMAL, INTERNAL, RESTRICTED) already exists but has **zero enforcement**. Changes:

- `core/validate.py`: `restricted` entries must have `visibility = INTERNAL` (never `EXTERNAL`)
- `core/validate.py`: `restricted` entries cannot be L0 (active refs have no access control)
- `server.py context()`: Exclude `restricted` entries from ambient context. They require explicit `read(id=...)`
- `core/scoring.py build_inverted_index()`: Skip entries with `sensitivity = RESTRICTED` entirely. They must not appear in the BM25 inverted index — even body-stripped results can leak that restricted content exists for a given search term.
- `server.py search/query`: Restricted entries excluded from multi-result search. Only accessible via `read(id=...)`.

### 2e. `on_source_branch` derived field

```python
class Entry(BaseModel):
    path: str
    frontmatter: Frontmatter
    body: str
    on_source_branch: bool = False  # set at parse time by index loader
```

Set by `load_index_from_repo()`: entries loaded from the main branch tree get `on_source_branch = True`. Entries overlaid from active refs get `False`.

Rules:
- If `on_source_branch is True` and `status == PROPOSED` → the entry was merged but frontmatter wasn't updated. Treat as `ACTIVE` for query purposes.
- `GATE_EVIDENCE` and `DURABLE_SOURCE` access modes check `on_source_branch`, not `status`.
- No bot, no GitHub Action, no frontmatter rewriting needed.

---

## 3. L0 Redesign: Opt-in Active Context

### 3a. Opt-in for both read and write

`JuratiConfig`: `active_refs_enabled: bool = False`. Environment: `JURATI_ACTIVE_REFS_ENABLED=true`.

**Write-side**: `server.py record()`: When `entry_type == ACTIVE` and `active_refs_enabled is False`, return error.

**Read-side**: `git/repo.py fetch_all()`: Skip fetching active refs when disabled. `load_index_from_repo()`: Skip overlay. A user who opts out neither writes nor receives anyone else's active context.

### 3b. Visibility locked to INTERNAL

L0 entries always get `visibility = INTERNAL`. Enforced in `plan_record()`.

### 3c. Maximum TTL

L0 entries with `expires_at` more than 168 hours (7 days) from `created_at` are rejected.

---

## 4. Coordination Signal Abstraction

### 4a. Generalized signal shape

```python
@dataclass(frozen=True)
class CoordinationSignal:
    signal_id: str
    provider: str
    source: str              # repo, project, channel
    artifact_ref: str        # PR URL, ticket URL, thread URL
    title: str
    excerpt: str | None
    actor: str
    state: str               # open/merged/closed/resolved
    labels: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    subject_refs: tuple[str, ...]    # files, modules, topics
    subject_areas: tuple[str, ...]   # directory prefixes, domains
```

`PRSignal` maps mechanically: `repo→source`, `url→artifact_ref`, `author→actor`, `merged_at→resolved_at`, `changed_paths→subject_refs`, `target_areas→subject_areas`.

### 4b. Provider protocol

```python
# providers/protocol.py — I/O interface, not in core/
@runtime_checkable
class SignalProvider(Protocol):
    provider_id: str
    def fetch_signals(self, config: dict[str, Any]) -> list[CoordinationSignal]: ...
    def needs_refresh(self, last_fetch: datetime, now: datetime) -> bool: ...
```

### 4c. Configurable keyword sets

`JURATI_REVISE_KEYWORDS` and `JURATI_HANDOFF_KEYWORDS` as comma-separated overrides. Default to current engineering-flavored sets.

---

## 5. Privacy Enforcement

### 5a. Sensitivity enforcement (section 2d)

### 5b. Access mode filtering at integration boundary

When external systems consume jurati through the integration contract (section 7), the contract layer filters entries by **named access mode**. This is the architectural solution to the cross-system consent problem.

### 5c. Identity opacity for external consumers

`core/privacy.py opaque_identity()`: salted hash keyed to requesting system. Prevents cross-system identity correlation. API-layer boundary only — raw git repo still exposes identities.

### 5d. PR author in context()

Acceptable. PR authorship is public git provenance from the git provider, not jurati observation.

---

## 6. Event Emission

### 6a. Purpose and privacy contract

Events allow external systems to react to jurati state changes without polling. Events are **lifecycle evidence** — they record that a knowledge entry was proposed or expired. They are explicitly **not**:

- Participation analytics (who used jurati, how often, from where)
- Activity trails (who queried, read, or searched for what)
- Presence signals (who is working, who is idle)

**Privacy rules for events:**

1. **Content**: Events include `entry_id`, `entry_type`, `level`, `visibility`. They never include author identity, query text, body content, or `recorded_by` data. Systems that need author info request it through the integration contract (section 7), which applies identity salting.
2. **Retention**: Events are git objects. They persist as long as the knowledge repo's git history persists. There is no built-in retention policy or automatic pruning. Organizations that need time-bounded retention should configure git history limits or periodic event directory cleanup on the knowledge repo itself.
3. **Consumers**: Events are consumed via standard git tooling (`git log events/`, GitHub webhooks filtering by path). There is no runtime API, callback registration, or subscriber list. Jurati has no knowledge of who consumes events.
4. **Redaction**: Since events are git commits, redaction follows standard git history rewriting (force push, BFG). Jurati does not provide a redaction API because redaction of git history is a git operation, not a jurati operation.
5. **L0 exclusion**: L0 entries produce no events. L0 is fire-and-forget. An L0 event on an active ref would be invisible from main; an L0 event on main would violate L0's ephemeral contract.

### 6b. Event types

```python
class EventType(StrEnum):
    ENTRY_PROPOSED = "entry_proposed"    # L1+ branch/PR created
    ENTRY_EXPIRED = "entry_expired"      # expiry branch/PR created
```

No `ENTRY_MERGED`. Jurati does not control merges. Systems needing merge events use GitHub webhooks on the knowledge repo.

### 6c. Event file layout

`events/<YYYY-MM-DD>/<timestamp>-<entry-id>.json`. Per-event files avoid merge conflicts across concurrent PR branches. One atomic commit includes both the entry and its event record.

### 6d. Merge normalization

Parse-time inference from branch location via `on_source_branch` (section 2e). No bot or GitHub Action needed.

---

## 7. Integration Contract

A stable, generic interface for external systems to consume jurati knowledge. The contract is both a pure module (`core/contract.py`) and the API surface through which integrations actually interact.

### 7a. Access modes and filtering rules

```python
class AccessMode(StrEnum):
    CONTEXT = "context"
    EXTERNAL_CONTEXT = "external_context"
    GATE_EVIDENCE = "gate_evidence"
    DURABLE_SOURCE = "durable_source"
```

| Access mode | Visibility filter | Branch filter | Sensitivity filter |
|---|---|---|---|
| `CONTEXT` | all | all | exclude `restricted` |
| `EXTERNAL_CONTEXT` | `external` only | all | exclude `restricted` |
| `GATE_EVIDENCE` | `external` only | source-of-truth only | exclude `restricted` |
| `DURABLE_SOURCE` | all | source-of-truth only | exclude `restricted` |

When `access_mode != CONTEXT`, `system_id` is required and `opaque_identity()` is applied.

### 7b. Knowledge query contract

```python
@dataclass(frozen=True)
class KnowledgeQuery:
    topic: str | None = None
    entry_type: str | None = None
    project: str | None = None
    access_mode: AccessMode = AccessMode.CONTEXT
    system_id: str | None = None
    max_results: int = 10

@dataclass(frozen=True)
class KnowledgeResult:
    entries: list[dict[str, Any]]
    coordination: list[dict[str, Any]]
    provenance: str
```

Pure function in `core/contract.py`. MCP tools use `CONTEXT` mode. External integrations declare their mode explicitly.

### 7c. Contract as the integration surface

The contract module is not just a pure helper with tests. The MCP server's existing tools (`context()`, `search()`, `query()`, `list_entries()`) must route through the contract layer for all filtering decisions. Additionally, a new `knowledge_query` MCP tool exposes the full contract interface to external systems that need non-CONTEXT access modes.

This means:
- `server.py context()` delegates to `contract.query_knowledge()` with `AccessMode.CONTEXT`
- External systems call `knowledge_query()` MCP tool with their access mode and system_id
- Filtering logic lives in one place (`core/contract.py`), not duplicated between server helpers and contract functions

### 7d. Constraint check interface

```python
def check_constraints(
    index: Index,
    project: str,
    *,
    now: datetime,
    constraint_types: tuple[EntryType, ...] = (EntryType.DECISION, EntryType.PRINCIPLE),
) -> list[Entry]:
```

### 7e. Signal classification (already pure)

`classify_signals()` is the coordination contract — external systems call it directly.

---

## 8. Index Caching

Cache BM25 inverted index on `ServerState`. Invalidate on `sync()`. `rank_entries()` gains `prebuilt_index` parameter — caller manages cache lifecycle, function stays pure.

---

## 9. DX Improvements

- `jurati install-claude-md`: Appends CLAUDE.md section + generates `.claude/settings.json`
- `jurati quickstart`: Also writes settings.json
- `jurati mcp-config`: Hash-based server name (`jurati-<hash>`) prevents collisions

---

## 10. Reporting (Deferred)

`jurati report` — deferred until a non-engineering team adopts jurati.

---

## Verification

1. `pytest tests/ -x -q` — all pass after each phase
2. Schema compatibility: v1 entries parse correctly, keep `schema_version: 1`, gain v2 field defaults
3. L0 write opt-in: `record(type="active")` fails when `JURATI_ACTIVE_REFS_ENABLED` not set
4. L0 read opt-in: `fetch_all()` skips active refs when `active_refs_enabled=False`
5. Sensitivity: `restricted` entries excluded from `context()`, excluded from BM25 index, only accessible via `read(id=...)`
6. Access mode: `EXTERNAL_CONTEXT` returns only `visibility=external` entries; `GATE_EVIDENCE` further requires `on_source_branch`
7. Signal provider: GitHub provider returns identical results via generalized `CoordinationSignal` shape
8. Events: L1+ write operations produce per-event JSON files; L0 writes produce no events
9. Events privacy: event files never contain author identity, query text, body content, or recorded_by data
10. Merge normalization: entry with `status=proposed` on source-of-truth branch treated as `active` in queries
11. Index cache: second search skips `build_inverted_index()`
12. install-claude-md: generates correct CLAUDE.md section and settings.json
13. Privacy: `opaque_identity()` produces different hashes for different `system_id` values
14. Visibility: `record(visibility="external")` accepted for L1; rejected for L0
15. Contract surface: `knowledge_query` MCP tool exposes non-CONTEXT access modes to external systems
