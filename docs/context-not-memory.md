# Context, Not Memory

Jurati is a shared agent context layer for projects and teams. It is not a
personal second brain, a CRM, a graph store, a database replacement, or a
telemetry system.

The distinction matters. Markdown files are good for human-readable, reviewable
knowledge. They are not themselves query infrastructure. Jurati uses Markdown
with YAML frontmatter as the source format because people can review it in pull
requests, preserve history in git, and keep durable decisions visible to both
people and agents.

## Architecture Claim

Jurati provides curated, git-reviewed coordination context for people and AI
agents:

- decisions that should shape future work
- workflows that describe how the team operates
- project context that explains what is in flight
- short-lived active handoffs that expire
- labeled PR signals that affect coordination

Jurati does not claim that a folder of Markdown files is agent memory. The
knowledge repo is the source ledger. Retrieval is handled by structured code:
frontmatter parsing, validation, in-memory indexes, BM25 ranking, privacy
filters, MCP tools, and explicit read/query/search contracts.

## What Jurati Is Not

Jurati is not trying to become a general-purpose personal notes app. It can
replace a shared Markdown context workflow when the goal is reviewed,
agent-readable coordination context.

Solo developers can use Jurati for project continuity across repos, agents, and
future sessions. The boundary is the same: save explicit project context that an
agent should reuse, not private scratch notes or a general personal archive.

Jurati is not:

- a personal notes app
- a personal assistant memory store
- a CRM or contact database
- a graph database
- a vector database
- a telemetry or participation tracking system
- a place for raw chat transcripts, secrets, or private customer data

Restricted entries remain outside broad search, context responses, and ranking
indexes. Query text is not logged. Reads do not create read receipts. Agent
activity is not used to infer presence.

## Storage Model

Jurati separates source, index, and interface:

| Layer | Role |
|-------|------|
| Markdown + YAML | Human-reviewable source of truth in git |
| Validation | Schema, escalation, path, privacy, and expiry checks |
| Runtime indexes | Derived retrieval structures built from source entries |
| MCP tools | Agent-facing context, search, read, and write contract |
| Pull requests | Durable review path for lasting context |

This is different from treating Markdown as the intelligence layer. Markdown is
the review surface. The runtime decides what to retrieve, filter, and return.

## Query Roadmap

The current runtime builds in-memory indexes from the knowledge repo cache, and
the CLI supports a derived SQLite/FTS read model for rebuildable local queries.
If Jurati needs richer retrieval beyond that, the next storage steps should
still be derived read models, not different source-of-truth models.

Good candidates:

- SQLite for structured metadata, filtering, and concurrent local reads
- SQLite FTS5 for full-text retrieval
- a vector index for semantic retrieval
- a graph projection for relationship traversal

In all cases, git remains the reviewed source ledger. Query stores are derived
indexes that can be rebuilt from the knowledge repo.

## Product Guardrail

Jurati should replace ad hoc shared notes for agent context, not recreate a
general notes product surface. Its product shape is narrower and stronger:
explicit project decisions, workflows, active handoffs, PR signals, and
coordination guidance. It should help agents start with the right context and
write back only when explicitly asked.

Security, privacy, and content safety are governed by
[Security, Privacy, And Content Safety Gate](security-privacy-content-safety.md).
