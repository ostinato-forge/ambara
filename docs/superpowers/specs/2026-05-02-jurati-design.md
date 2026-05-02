# Jurati Design Spec

**Date:** 2026-05-02
**Status:** Approved
**Author:** Edgar Parenti

## Purpose

Jurati is a shared team intelligence layer for agentic workflows. It gives AI coding agents (and humans) a shared memory — architectural principles, workflow preferences, decision history, and cross-project state — without surveillance, telemetry, or participation tracking.

The problem: multiple people working across multiple projects via different coding agent terminals have no way to sync ideas, preferences, workflows, and architectural decisions. Every agent starts cold. Knowledge stays siloed in individual `.claude/` memory files, CLAUDE.md fragments, and people's heads.

Jurati solves this by providing a git-backed knowledge repository with a thin MCP server layer that agents can query and contribute to.

## Constitutional Principles

### Privacy as Architecture

Jurati is a broadcast system, not an observation system. It is **structurally incapable** of surveillance:

- **No telemetry.** The server collects zero usage data. No query logs, no access patterns, no participation metrics.
- **No absence signals.** The system never reports who hasn't contributed, who hasn't read something, or who's falling behind.
- **Local queries.** Searches run against a local git clone. No central server sees what anyone is looking for.
- **Explicit sharing only.** Nothing enters the knowledge base without a deliberate `propose` or `record` action. Agent activity, conversation history, and work-in-progress are never captured.
- **No participation tracking.** The system has no concept of "active users" or "engagement." Git blame exists for provenance, not performance measurement.

This is not a policy — it is architecture. The server has no mechanism to observe what it isn't told.

### Escalation-Based Write Model

Derived from the four-eyes principle (quatre-ulls):

| Level | Description | Write mechanism | Review |
|-------|-------------|-----------------|--------|
| L0 | Ephemeral state (active work) | Direct commit | None — auto-expires 72h |
| L1 | Project context | Direct commit | Visible in git log |
| L2 | Workflows, decisions | Branch + PR | Human reviews before merge |
| L3 | Architectural principles | Branch + PR | Human reviews before merge |

Higher-stakes content requires human approval. Lower-stakes content flows freely. The escalation spectrum is structural, not procedural.

## Architecture

### Storage: Git Repo + Thin MCP Layer

The source of truth is a plain git repository (`jurati-knowledge`). The MCP server is a thin query/write layer over that repo. This means:

- Every entry is a markdown file with YAML frontmatter — human-readable, human-editable
- Full version history via git
- PRs for review on L2/L3 content
- Works without the MCP server (just read the files)
- Standard git tooling for backup, branching, collaboration

### Knowledge Repository Structure

```
jurati-knowledge/
├── principles/             # L2/L3: branch + PR
│   └── deterministic-cores.md
├── decisions/              # L2/L3: branch + PR
│   └── monorepo-consolidation.md
├── workflows/              # L2/L3: branch + PR
│   └── builder-reviewer-loop.md
├── projects/               # L0/L1: direct commit
│   └── agentic-sdlc-status.md
├── active/                 # L0: direct commit, auto-expires 72h
│   └── edgar-auth-refactor.md
└── .jurati/
    └── config.yaml         # escalation rules, sync settings
```

### Entry Schema

Every entry is a markdown file with YAML frontmatter:

```yaml
---
title: Deterministic Cores
type: principle              # principle | decision | workflow | project | active
status: active               # active | superseded | draft | proposed
author: Edgar Parenti
date: 2026-05-02
projects: [agentic-sdlc, qa-gate, egon, netballast]
tags: [architecture, pure-logic, testing]
schema_version: 1
expires: null                # ISO date, required for type: active
---

Body content in markdown. Human-readable, agent-readable.
Supports any structure — the frontmatter is the machine-actionable part.
```

### Core/IO Boundary

Following the same architectural primitive as egon, quatre-ulls, and netballast:

```
src/jurati/
├── core/                   # Pure, deterministic — zero I/O
│   ├── __init__.py
│   ├── schema.py           # Pydantic models for entries + frontmatter
│   ├── index.py            # Parse frontmatter, build in-memory index
│   ├── search.py           # Query/filter/match logic against index
│   └── validate.py         # Entry validation, escalation rules
├── git/                    # I/O boundary — all side effects here
│   ├── __init__.py
│   ├── repo.py             # Clone, pull, push, branch operations
│   ├── commit.py           # Write file + commit (L0/L1)
│   └── pr.py               # Branch + gh pr create (L2/L3)
├── __init__.py
├── server.py               # MCP tool handlers — thin glue
└── cli.py                  # jurati serve, jurati init
```

**core/** is pure: given inputs, returns outputs. No file reads, no git calls, no network. Fully testable with zero fixtures.

**git/** is the I/O boundary: clones repos, reads files, creates commits and PRs. Thin, mechanical, tested against real git repos.

**server.py** is glue: receives MCP tool calls, coordinates core/ and git/, returns results.

## MCP Server

### Tools

Seven tools, each with a clear single responsibility:

#### `query(topic, type?, project?, since?)`
Search the knowledge index. Returns matching entries with title, path, type, relevance snippet. Runs against the local in-memory index built from the git clone.

#### `read(path)`
Return the full content of a single entry (frontmatter + body).

#### `propose(type, title, content, metadata)`
Create a new entry via branch + PR. Used for L2/L3 content (principles, decisions, workflows). Returns the PR URL for human review.

#### `record(type, title, content, metadata)`
Create a new entry via direct commit to main. Used for L0/L1 content (project state, active work). Returns the commit SHA.

#### `list(type?, project?, status?)`
Filtered listing of entries. Returns title, path, type, status, date for each match.

#### `sync()`
Pull latest from remote, rebuild index. Called automatically on a 5-minute interval, but agents can trigger manually.

#### `forget(path)`
Remove an entry. Primary use: cleaning up expired `active/` entries (>72h). Can also be used to remove superseded content.

### Sync Model

- **Auto-clone on first start:** Server clones the remote repo to a local cache directory on first run. No manual setup required.
- **5-minute sync interval:** Background pull + reindex on a timer. Keeps local state fresh without hammering the remote.
- **Manual sync:** Agents can call `sync()` to force a refresh when they know something changed.
- **Conflict handling:** Git merge conflicts on direct commits are flagged to the user — the server doesn't auto-resolve. PR-based flows (L2/L3) handle conflicts through normal GitHub PR mechanics.

### Configuration

Server config via environment:

```bash
JURATI_REMOTE=git@github.com:RedHatTraining/jurati.git  # knowledge repo
JURATI_CACHE_DIR=~/.jurati/repos                         # local clone location
JURATI_SYNC_INTERVAL=300                                 # seconds (default: 300)
```

MCP settings.json entry:

```json
{
  "mcpServers": {
    "jurati": {
      "command": "jurati",
      "args": ["serve"],
      "env": {
        "JURATI_REMOTE": "git@github.com:RedHatTraining/jurati.git"
      }
    }
  }
}
```

## Content Layers (v1 Scope)

All four layers ship in v1:

### 1. Principles
Architectural decisions that span projects. Examples: "deterministic cores," "coverage honesty," "authority model." L2/L3 — require PR review.

### 2. Decisions
Specific choices with rationale and context. Machine-actionable ADRs. Examples: "monorepo consolidation," "Temporal migration strategy." L2/L3 — require PR review.

### 3. Workflows
How the team works. Preferred patterns, tool configurations, review processes. Examples: "builder/reviewer agent loop," "commit message format." L2/L3 — require PR review.

### 4. Projects
Current state of ongoing work. What's in flight, what's blocked, what's shipping. Examples: "agentic-sdlc consolidation status," "qa-gate v2 progress." L0/L1 — direct commit, low ceremony.

### 5. Active
Ephemeral signals — what someone is working on right now. Auto-expires after 72 hours. Explicit opt-in only (privacy principle). L0 — direct commit, no review.

## Testing Strategy

- **core/ tests:** Pure unit tests. No mocking needed — functions take data in, return data out. Index building, search matching, validation rules, schema parsing.
- **git/ tests:** Integration tests against real git repos (tmpdir fixtures). Clone, commit, branch, PR creation.
- **server tests:** Tool handler tests with a mocked git layer. Verify correct routing between core/ and git/.
- **Contract tests:** Validate that entry files in the knowledge repo conform to the schema. Runs in CI on the knowledge repo.

## Technology

- Python 3.13+
- Pydantic for schema/validation
- `mcp` SDK for MCP server implementation
- `gitpython` or subprocess git for repo operations
- `pyyaml` + `python-frontmatter` for YAML frontmatter parsing
- Click for CLI

## Non-Goals (v1)

- **No web UI.** Git + MCP + editor is the interface.
- **No real-time sync.** 5-minute polling is sufficient for knowledge that changes hourly, not per-second.
- **No permissions system.** Git repo permissions (who can push/merge) handle access control.
- **No AI summarization/synthesis.** The MCP server is a dumb index. Agents do their own reasoning over the content.
- **No cross-org federation.** Single knowledge repo per team/org.
