# Jurati Design Spec

**Date:** 2026-05-02
**Status:** Consensus approved
**Author:** Edgar Parenti

## Purpose

Jurati is a shared team intelligence layer for agentic workflows. It gives AI
coding agents and humans a shared, reviewable memory of architectural
principles, workflow preferences, decision history, and cross-project state.

The problem is not that teams lack places to write things down. The problem is
that coding agents start cold in each terminal, project context drifts into
private memory files, workflow decisions live in scattered chat transcripts, and
cross-project lessons are rediscovered instead of reused.

Jurati solves this with two deliberately simple parts:

- a plain git knowledge repository containing markdown entries with strict YAML
  frontmatter
- a thin MCP server that can query, read, validate, and propose changes to that
  repository

The code repository and the knowledge repository are separate:

- `jurati` is the software project that ships the CLI, MCP server, schemas, and
  tests.
- `jurati-knowledge` is the team-owned content repository. It is the source of
  truth for shared knowledge.

## Design Goals

- Keep useful team knowledge available to agents without creating a monitoring
  system.
- Preserve human-readable git history and normal review mechanics.
- Make every write explicit, typed, and attributable through git.
- Keep local reads and searches local.
- Make protected-branch repositories the default assumption.
- Keep core logic deterministic and independently testable.

## Privacy Boundary

Jurati is a broadcast system, not an observation system. The Jurati server is
not allowed to collect usage telemetry, read receipts, query histories, absence
signals, engagement metrics, or participation scores.

This is the precise boundary:

### Jurati Server May Process Transiently

To answer a tool call, the server necessarily receives the current request
arguments in process memory. That includes query text, entry IDs, filters, and
explicit write content. The privacy rule is about persistence and reporting:
transient request inputs must not become telemetry, durable logs, read receipts,
analytics, or remote events except for explicit write operations.

### Jurati Server Must Not Persist Or Report

- who queried a topic
- who read an entry
- who did not read or contribute
- which results an agent ignored
- raw query text, read selections, or result clicks
- conversation history, terminal history, editor activity, or agent activity
  outside an explicit Jurati tool call

### Jurati Server May Persist

- the configured knowledge repo URL
- the local clone path
- entry files present in the local clone
- explicit write requests sent through `record`, `propose`, or `expire`
- git command success/failure needed to complete those explicit writes

### Git Provider Still Observes Writes

Jurati cannot hide normal git provenance. Remote git hosting records commits,
branches, PRs, authorship, timestamps, CI runs, comments, reviews, and merges.
That provenance exists for accountability and review. It must not be repurposed
inside Jurati as participation tracking.

### Active Work Is Explicit Presence

`active` entries are deliberate presence signals. They are never inferred from
agent activity. They expire from normal query/list results after their TTL, but
their git history remains unless an administrator performs a separate redaction
procedure outside normal Jurati v1 behavior.

## Escalation-Based Write Model

Jurati uses escalation levels to select the write path. The default v1 model
assumes `main` is protected. No normal MCP tool pushes directly to `main`.

| Level | Content | Default write path | Review expectation |
|-------|---------|--------------------|--------------------|
| L0 | Active ephemeral state | Non-main active ref | No PR; explicit ephemeral broadcast |
| L1 | Project status/context | Short-lived branch + lightweight PR | Visible review optional |
| L2 | Workflows and decisions | Branch + PR | Human review before merge |
| L3 | Architectural principles | Branch + PR | Human review before merge |

`record()` handles L0/L1 writes, but those levels have different visibility
rules:

- L0 `active` entries are committed to a configured non-main active ref such as
  `refs/heads/jurati/active/<client>/<entry-id>`. They are fetched during sync
  as an overlay on top of the source-of-truth branch. They become visible after
  the active ref push succeeds, not after a PR merge. They are never durable
  source-of-truth records unless separately proposed as L1+ content.
- L1 project entries create a branch, commit the entry as `status: proposed`,
  push the branch, and open a PR labeled for low-ceremony review. They become
  `status: active` only after merge to the source-of-truth branch.

`propose()` handles L2/L3 writes. It always creates a branch and PR and never
claims that content is active until the PR merges.

This is structural rather than social: higher-stakes content cannot reach the
source-of-truth branch through a lower-stakes tool.

## Knowledge Repository Contract

The source of truth is a plain git repository, conventionally named
`jurati-knowledge`. The code repo must never be confused with the knowledge
repo.

```
jurati-knowledge/
├── principles/             # L3 architectural principles
├── decisions/              # L2/L3 ADR-style decisions
├── workflows/              # L2 team workflow contracts
├── projects/               # L1 project state and durable context
├── active/                 # L0 entries when viewing active overlay refs
├── archive/                # expired or superseded content, when retained as files
└── .jurati/
    └── config.yaml         # escalation rules, branch policy, schema version
```

Every entry is a markdown file with YAML frontmatter. The body can be flexible
markdown; the frontmatter is the machine contract.

```yaml
---
schema_version: 1
id: principle-deterministic-cores
title: Deterministic Cores
type: principle              # principle | decision | workflow | project | active
level: L3                    # L0 | L1 | L2 | L3
status: active               # draft | proposed | active | superseded | expired
created_at: 2026-05-02T00:00:00Z
updated_at: 2026-05-02T00:00:00Z
expires_at: null             # required for type: active
projects: [agentic-sdlc, qa-gate, egon, netballast]
tags: [architecture, pure-logic, testing]
supersedes: []
superseded_by: null
sensitivity: normal          # normal | internal | restricted
review:
  required: true
  pr: null
---

Body content in markdown.
```

### Schema Rules

- `id` is stable and unique across the repository.
- `id` must match `^[a-z0-9][a-z0-9-]{2,120}$`.
- Active-ref `client` slugs must match the same grammar as entry IDs and must
  come from explicit local configuration or tool input, not inferred silently
  from OS user identity.
- File path is derived from `type` and `id`; callers may not provide arbitrary
  paths.
- `level` must be allowed for the selected `type` by `.jurati/config.yaml`.
- `active` entries must include `expires_at`.
- Timestamps are UTC ISO-8601 strings ending in `Z`.
- `created_at` is immutable.
- `updated_at` must be greater than or equal to `created_at`.
- `expires_at` for active entries must be greater than `created_at`.
- `status: active` on L1/L2/L3 content is only valid after merge to the
  source-of-truth branch.
- `status: active` on L0 content is valid on configured active overlay refs.
- `supersedes` and `superseded_by` use entry IDs, not file paths.
- `sensitivity` is classification metadata, not an access-control system.
- Git provenance is authoritative for commit author and merge history; display
  author fields are optional content, not security controls.

## Core/IO Boundary

Jurati keeps the same deterministic core boundary used in the surrounding
tooling stack.

```
src/jurati/
├── core/
│   ├── schema.py           # Pydantic models for frontmatter and entries
│   ├── paths.py            # safe path derivation from type/id
│   ├── index.py            # parse entries into an in-memory index
│   ├── search.py           # pure query/filter/relevance logic
│   ├── validate.py         # schema, escalation, status, expiry validation
│   └── changes.py          # pure write-intent planning
├── git/
│   ├── repo.py             # clone, fetch, pull, worktree safety
│   ├── branch.py           # branch naming and checkout lifecycle
│   ├── commit.py           # materialize planned changes and commit
│   └── pr.py               # GitHub PR adapter
├── server.py               # MCP tool handlers
└── cli.py                  # jurati serve, jurati init, validation helpers
```

`core/` is pure: no filesystem reads, git calls, network, time, randomness, or
environment lookups. Current time, repo snapshots, config, and request metadata
enter core as explicit inputs.

`git/` owns side effects. It validates repo roots, prevents path traversal,
performs clone/fetch/push operations, and returns typed results.

`server.py` is orchestration glue. It receives MCP tool calls, loads explicit
inputs, calls core, invokes git adapters, and returns small typed responses.

## MCP Tool Contract

### `query(topic, type?, project?, status?, include_expired?)`

Search the local in-memory index. Returns matching entry summaries with IDs,
titles, paths, types, statuses, projects, tags, and short snippets. It must not
write query text or result selections to disk or remote services.

### `read(id, include_expired?)`

Return one entry by ID. Path lookup is derived from the index; callers do not
pass raw paths. Expired entries require an explicit `include_expired` option in
the server-side request contract.

### `record(type, title, content, metadata)`

Create an L0/L1 entry. L0 writes push a non-main active ref and return entry ID,
ref, commit SHA, and expiry time. L1 writes create a low-ceremony PR and return
entry ID, branch, commit SHA, and PR URL. The tool refuses L2/L3 content.

### `propose(type, title, content, metadata)`

Create an L2/L3 entry through a normal branch/PR path. The tool returns entry
ID, branch, commit SHA, and PR URL. It refuses L0/L1 content unless explicitly
configured as a proposal rather than a record.

### `list(type?, project?, status?, include_expired?)`

List entries from the local index. Defaults exclude expired `active` entries.

### `validate(id?)`

Validate one entry or the full local index without writing. Returns typed schema,
path, escalation, expiry, and supersession errors. It must not open PRs, modify
files, or update remote state.

### `sync()`

Fetch or pull the configured source-of-truth branch, then rebuild the local
index. Sync must not auto-merge conflicts. Conflicts return a typed error with
the repo path and suggested recovery.

### `expire(id, reason?)`

Mark an entry as expired or superseded through the write path appropriate to its
level. L0 expiry updates or removes the configured active ref from normal index
results; it does not promise deletion from remote git hosting history. L1 expiry
uses the low-ceremony PR path. L2/L3 expiry uses review PRs.

### Redaction Is Not A Normal Tool

True removal from git history is an administrative incident response, not a v1
MCP tool. The normal tool surface must use expiry, supersession, or tombstone
entries.

## Sync And Cache Model

- On first start, the server clones `JURATI_KNOWLEDGE_REMOTE` into
  `JURATI_CACHE_DIR`.
- The cache path is derived from the remote URL hash so multiple knowledge repos
  do not collide.
- The default sync interval is 300 seconds.
- Reads and queries use the local clone and fetched active overlay refs only.
- Sync fetches the source-of-truth branch plus configured active refs.
- Manual `sync()` is available when a caller knows remote state changed.
- Background sync failures are surfaced as health state; they do not disable
  local reads of the last synced index.
- The index is rebuilt from repository contents after sync, not incrementally
  trusted from prior process memory.

## Configuration

```bash
JURATI_KNOWLEDGE_REMOTE=git@github.com:RedHatTraining/jurati-knowledge.git
JURATI_CACHE_DIR=~/.jurati/repos
JURATI_MAIN_BRANCH=main
JURATI_BRANCH_PREFIX=jurati
JURATI_ACTIVE_REF_PREFIX=jurati/active
JURATI_SYNC_INTERVAL=300
JURATI_WRITE_MODE=pull_request
```

MCP client example:

```json
{
  "mcpServers": {
    "jurati": {
      "command": "jurati",
      "args": ["serve"],
      "env": {
        "JURATI_KNOWLEDGE_REMOTE": "git@github.com:RedHatTraining/jurati-knowledge.git"
      }
    }
  }
}
```

`.jurati/config.yaml` in the knowledge repo defines repository policy:

```yaml
schema_version: 1
main_branch: main
active_ref_prefix: jurati/active
levels:
  active: [L0]
  project: [L1]
  workflow: [L2]
  decision: [L2, L3]
  principle: [L3]
review:
  low_ceremony_labels: [jurati-record]
  required_review_levels: [L2, L3]
expiry:
  active_ttl_hours: 72
active_refs_enabled: true
```

## Content Layers

### Principles

Long-lived architectural principles that span projects. Example:
`principle-deterministic-cores`. Default level: L3.

### Decisions

ADR-style decisions with rationale, alternatives, consequences, and supersession
links. Default level: L2, with L3 available for architecture-wide decisions.

### Workflows

How the team works: builder/reviewer loops, commit conventions, review gates,
lab validation practices, and tool usage norms. Default level: L2.

### Projects

Durable but lightweight project state: what is in flight, what is blocked, what
was shipped, and what cross-project context agents should know. Default level:
L1.

### Active

Explicit, short-lived active-work entries stored on non-main active overlay
refs. They are opt-in presence signals, excluded from normal results after
expiry, and never inferred from behavior. Default level: L0.

## Testing And Proof Strategy

### Core Tests

- schema round trips and validation errors
- path derivation and path traversal rejection
- ID slug grammar and timestamp invariants
- escalation/type/status compatibility
- expiry filtering
- search determinism and ranking stability
- write-intent planning with no filesystem access

### Git Adapter Tests

- clone/fetch/pull against temporary repositories
- fetching source-of-truth plus active overlay refs
- branch naming, collision handling, and dirty-worktree protection
- committing planned changes without escaping the repo root
- conflict detection without auto-resolution
- PR adapter contract tests with the GitHub boundary mocked or recorded behind
  explicit live-test flags

### Server Tests

- each MCP tool routes through core then git adapters correctly
- query/read do not invoke write paths
- validate does not invoke write paths
- expired active entries are excluded by default
- L0 records are visible from active refs before merge and disappear from
  default results after TTL
- write tools reject invalid type/level combinations
- sync failures preserve last known readable index

### Knowledge Repo Contract Tests

- all markdown entries parse
- IDs are unique
- file paths match type/id
- no active entry lacks `expires_at`
- active refs are ignored when disabled by config
- no L2/L3 active entry appears without review metadata
- supersession links resolve

### Privacy Regression Tests

- query/read/list produce no telemetry files
- server logs contain no query text by default
- no active entry is created without explicit `record`
- expired active entries disappear from default query/list results

## V1 Build Sequence

1. **Skeleton:** package, CLI shell, MCP server shell, config loading, and test
   harness.
2. **Core contracts:** schema, path derivation, validation, index building,
   search, expiry filtering, and write-intent planning.
3. **Read path:** clone/cache/sync, local index load, `query`, `read`, `list`,
   and `validate`, including active overlay refs.
4. **Write path:** active-ref writes, branch creation, commit materialization,
   PR creation, `record`, `propose`, and `expire`.
5. **Knowledge repo validation:** `.jurati/config.yaml`, contract test command,
   and CI example for `jurati-knowledge`.
6. **Operational hardening:** sync health, conflict errors, cache isolation,
   privacy regression tests, and install documentation.

## V1 Acceptance

- A fresh install can clone a configured `jurati-knowledge` repo and answer
  `query`, `read`, `list`, and `validate` from the local index.
- Invalid entries fail deterministically with useful errors.
- L0 records push only to configured active refs and are visible before merge.
- L1 records create low-ceremony PRs, not direct pushes to protected `main`.
- L2/L3 proposals create review PRs and cannot be recorded as low-stakes
  content.
- Expiry hides stale active entries from default reads without claiming git
  history deletion.
- Query/read/list leave no Jurati telemetry behind.
- The code repo and knowledge repo names are never interchangeable in docs,
  config, or examples.

## Non-Goals For V1

- No web UI.
- No real-time sync.
- No Jurati-native permissions system beyond git hosting controls and schema
  validation.
- No AI summarization or synthesis inside the server.
- No cross-org federation.
- No git-history redaction tool.
- No participation dashboards, read receipts, contribution rankings, or absence
  reports.
