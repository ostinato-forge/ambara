# Jurati

Shared team intelligence layer for agentic workflows. Git-backed knowledge repo + MCP server.

## Architecture

- `core/` — pure, deterministic, zero I/O. Schema, index, search, validation, path derivation, write-intent planning, events, integration contract, privacy.
- `git/` — I/O boundary. Clone, fetch, branch, commit, PR operations, config.
- `providers/` — I/O boundary. Signal provider protocol and implementations (GitHub PRs).
- `server.py` — MCP tool handlers. Orchestration glue between core/ and git/.
- `cli.py` — `jurati serve`, `jurati init`, `jurati validate`, `jurati install-claude-md`, `jurati doctor`.

**Never cross the streams.** `core/` must never import from `git/` or `providers/` or perform I/O. Current time, repo snapshots, and config enter core as explicit inputs.

### Core modules

| Module | Purpose |
|--------|---------|
| `core/schema.py` | Entry, Frontmatter, Visibility, RecordedBy, Sensitivity, EscalationLevel |
| `core/index.py` | Entry parsing, Index building, schema v1→v2 backward-compat defaults, `on_source_branch` |
| `core/changes.py` | WriteIntent, ExpireIntent, plan_record, plan_propose, plan_expire — pure write planning |
| `core/validate.py` | Entry validation rules: restricted+external, restricted+L0, L0 max TTL, review requirements |
| `core/scoring.py` | BM25 search with recency decay, type weights, repo affinity, restricted exclusion |
| `core/search.py` | Exact substring matching query |
| `core/pr_signals.py` | CoordinationSignal, PRSignal, classify_signals, configurable keywords |
| `core/events.py` | EventType, EventRecord — L1+ lifecycle events (L0 excluded, privacy-safe) |
| `core/contract.py` | AccessMode, KnowledgeQuery, KnowledgeResult, query_knowledge, check_constraints |
| `core/privacy.py` | opaque_identity — salted identity hashing at integration boundaries |
| `core/hygiene.py` | Expired/stale/superseded entry lifecycle reporting |
| `core/paths.py` | Path derivation, safety checks |

### I/O boundary

| Module | Purpose |
|--------|---------|
| `git/repo.py` | ensure_repo, fetch_all (respects active_refs_enabled), load_index_from_repo |
| `git/commit.py` | materialize_write, materialize_expire — atomically commits entries + event files |
| `git/branch.py` | Branch creation, push, cleanup, active ref management |
| `git/config.py` | JuratiConfig from env vars — active_refs_enabled, keyword overrides, PR signal config |
| `git/auth.py` | Zero-config GitHub auth resolver (candidate chain) |
| `git/pr.py` | PR creation via gh CLI |
| `providers/protocol.py` | SignalProvider runtime-checkable Protocol |
| `providers/github_prs.py` | GitHub PR signal provider implementation |
| `providers/cache.py` | In-memory signal cache with TTL |

## Code vs Knowledge Repo

`jurati` (this repo) is the software. `jurati-knowledge` is the team-owned content repository. Never confuse the two in docs, config, or code.

## Schema

Schema v2 (`schema_version: 2`) is the current version. v1 entries are backward-compatible — they receive v2 defaults (`visibility=internal`, `recorded_by=None`) at parse time with no data migration.

Key v2 additions:

- `visibility`: INTERNAL (default) or EXTERNAL — author-side distribution declaration
- `recorded_by`: which MCP client submitted the write (mechanical fact, not authorship claim)
- `sensitivity`: NORMAL, INTERNAL, or RESTRICTED — RESTRICTED entries excluded from search, context, BM25 index
- `on_source_branch`: derived at parse time — True for entries on the source-of-truth branch

## Escalation Model

Protected `main` is the default. No MCP tool pushes directly to main.

- L0 (active): non-main active overlay refs (`jurati/active/<client>/<entry-id>`). **Opt-in** — disabled by default via `active_refs_enabled=false`.
- L1 (project): short-lived branch + lightweight PR
- L2 (workflow, decision): branch + PR, human review
- L3 (principle): branch + PR, human review

`record()` handles L0/L1. `propose()` handles L2/L3. Higher-stakes tools cannot create lower-stakes content and vice versa.

L0 entries are always `visibility=INTERNAL` and have a max TTL of 168 hours (7 days).

## Events

L1+ write operations produce per-event JSON files in `events/YYYY-MM-DD/` within the knowledge repo. Events contain entry_id, entry_type, level, and visibility — never author identity, query text, or body content. L0 entries produce no events.

## Privacy

The server must not persist or report: query text, read patterns, participation metrics, absence signals, or agent activity outside explicit tool calls. Git provenance (commits, PRs, authorship) exists for accountability — it must not be repurposed as participation tracking inside jurati.

Restricted entries are excluded from context(), search(), query(), and the BM25 inverted index. They are only accessible via read(id=...).

When entries cross integration contract boundaries (non-CONTEXT access modes), identities are salted per requesting system via opaque_identity().

## Dev

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Conventions

- Python 3.13+
- Conventional Commits: `feat:`, `fix:`, `refactor:`, etc.
- Ruff for linting, mypy strict mode
- Tests mirror src/ structure under tests/
- Entry IDs: `^[a-z0-9][a-z0-9-]{2,120}$`
- Timestamps: UTC ISO-8601 ending in `Z`
- core/ modules must have zero I/O imports (enforced by test_architecture.py AST guard)
