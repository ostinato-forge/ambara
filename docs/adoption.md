# Jurati Adoption Guide

This guide is for any team — engineering, training, legal, product — that
needs shared context for people and AI agents without adding another
heavyweight system.

## The Adoption Promise

A new user should be able to answer these questions in minutes:

- What is Jurati?
- What repo does it read?
- What does it write?
- What will my agent see?
- What will my teammates see?
- What privacy boundary does it enforce?

If those answers are not obvious, the product is not done.

## The Simple Mental Model

Jurati is a reviewable team context layer backed by git.

Agents read it before acting. People and agents write to it only when they
explicitly choose to share something. Durable changes use normal git review.
Short-lived active context uses active refs and expires automatically.

The Markdown files are the human-reviewable source format, not the query
engine. Jurati parses and indexes those entries so agents retrieve focused
context instead of loading a pile of notes into their prompt. See
[Context, Not Memory](context-not-memory.md) for the architecture boundary.
Teams migrating from an Obsidian-backed context workflow should follow the
[Context Packs Build Plan](context-packs-plan.md).

## Setup for a New Team

### 1. Create the knowledge repo

```bash
jurati quickstart ./jurati-knowledge \
  --remote git@github.com:your-org/jurati-knowledge.git \
  --pack engineering  # or --pack training, or omit for generic
```

This creates the scaffold, starter entries, and `.claude/settings.json` with
the 13-tool permission allowlist.

### 2. Push it

```bash
cd jurati-knowledge
git init && git add . && git commit -m "docs: initialize jurati knowledge repo"
git remote add origin git@github.com:your-org/jurati-knowledge.git
git push -u origin main
```

### 3. Install into each project repo

```bash
jurati install-claude-md --repo-path /path/to/your-project \
  --remote git@github.com:your-org/jurati-knowledge.git
```

This appends a CLAUDE.md section (so agents know to call `context()` first)
and creates `.claude/settings.json` (so agents don't prompt on every tool
call). Commit both files.

### 4. Generate MCP config

```bash
jurati mcp-config --remote git@github.com:your-org/jurati-knowledge.git
```

Paste the output into your MCP client config. Server names are hash-based
(`jurati-{hash}`) so multiple knowledge repos don't collide.

### 5. Verify

```bash
jurati doctor
jurati serve --check
```

Ask your agent to call `explain()` and `status()` to confirm the connection.

## Progressive Adoption Levels

### Read-only (zero risk)

Call `context()`, `query()`, `search()` — no setup beyond CLAUDE.md and
MCP config. No writes, no branches, no PRs.

### Write mode

Configure `JURATI_KNOWLEDGE_REMOTE` — `record()` and `propose()` become
available. All writes go through branches and pull requests.

### Active context (opt-in)

Set `JURATI_ACTIVE_REFS_ENABLED=true` — ephemeral L0 entries enabled.
Short-lived handoff notes, current focus, investigation context. Disabled
by default because L0 is the primary surveillance risk identified in design
review.

## Daily Workflow

### Start Work

The agent calls `context()` automatically (the CLAUDE.md section instructs it
to). This surfaces:

- active project context
- relevant prior decisions
- team workflow expectations
- coordination signals from labeled PRs

### During Work

Record explicit shareable context:

```text
record(type="project", title="Current focus", content="...")
```

This is intentional broadcast, not telemetry. It is not inferred from activity.

### Before Review

Check the team workflow:

```text
query(topic="review checklist", type="workflow")
```

### After A Decision

Propose durable knowledge:

```text
propose(type="decision", title="...", content="...")
```

Jurati opens a branch and pull request for team review.

## Visibility

Entries declare their distribution scope:

- **internal** (default) — visible within jurati's own MCP tools only
- **external** — opted in for cross-system distribution via the integration
  contract

L0 entries are always internal. L1 entries default to internal. L2/L3 entries
default to external.

External systems declare their access mode when querying. Each mode has
explicit filtering rules — no ordering ambiguity.

## Department-Neutral Examples

Training:

- lesson migration notes
- lab validation gotchas
- peer review expectations
- course release checklist
- recurring style or assessment decisions

Engineering:

- service ownership context
- release and rollback workflow
- architecture decisions
- incident follow-up notes
- coding standards and review expectations

Both:

- current project state
- active blockers
- handoff notes
- durable decisions
- "how we work here" preferences
