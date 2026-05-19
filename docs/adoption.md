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
[Context Pack Migration](context-pack-migration.md) guide.

## Setup for a New Team

### 1. Run guided onboarding

```bash
cd /path/to/your-project
jurati onboard
```

Jurati prompts for the knowledge repo remote, local knowledge repo path, project
repo path, and starter pack. It creates the knowledge repo scaffold, appends the
project `CLAUDE.md` startup contract, writes `.claude/settings.json`, and writes
project-local `.mcp.json`.

For scripted setup:

```bash
jurati onboard \
  --remote git@github.com:your-org/jurati-knowledge.git \
  --knowledge-repo ./jurati-knowledge \
  --project-repo /path/to/your-project \
  --pack engineering \
  --yes
```

### 2. Push the knowledge repo

```bash
cd jurati-knowledge
git init -b main
git add .
git commit -m "docs: initialize jurati knowledge repo"
git remote add origin git@github.com:your-org/jurati-knowledge.git
git push -u origin main
```

### 3. Verify

```bash
jurati doctor --check-startup
```

`doctor --check-startup` fetches the configured knowledge repo, rebuilds the
local index, and verifies the same read path that backs `sync()` and
`context()`. Ask your agent to call `explain()` and `status()` to confirm the
connection from the client side.

For the first user test, give the agent a normal task and watch the first tool
calls. It should call `sync()` and `context()` before reading local files or
checking git state, then summarize the relevant team context in plain language.

## Progressive Adoption Levels

### Read-only (zero risk)

Call `context()`, `query()`, `search()` — no setup beyond CLAUDE.md and
MCP config. No writes, no branches, no PRs.

### Write mode

Configure `JURATI_KNOWLEDGE_REMOTE` — `record()` and `propose()` become
available. All writes go through branches and pull requests.

### Context-pack migration

If your team already has curated Markdown notes, package only the shareable
team context into a context pack and run:

```bash
jurati import-context --dry-run --repo ./jurati-knowledge context-pack.tar.gz
```

Review the create/skip/reject summary before writing anything. When the dry-run
is clean, run the same command without `--dry-run`; Jurati creates a review
branch and commits generated entries for normal pull request review.

### Active context (opt-in)

Set `JURATI_ACTIVE_REFS_ENABLED=true` — ephemeral L0 entries enabled.
Short-lived handoff notes, current focus, investigation context. Disabled
by default because L0 is the primary surveillance risk identified in design
review.

## Daily Workflow

### Start Work

The agent runs the startup sequence from CLAUDE.md before local exploration:
`sync()` silently, then `context(repo=<current repo>, goal=<user request>)`.
This surfaces:

- active project context
- relevant prior decisions
- team workflow expectations
- coordination signals from labeled PRs

Those PR signals include enough detail for normal planning: state, title,
author, updated time, matched paths, merge time when available, and an
optional short excerpt when configured.

If that context points at a specific workflow, decision, or project, the agent
then calls `query(topic=...)` for the deeper entry before acting.

### During Work

Record explicit shareable context:

```text
record(type="project", title="Current focus", content="...")
```

This is intentional broadcast, not telemetry. It is not inferred from activity.
The developer-facing confirmation should stay work-focused, for example:
"Recorded the current focus." Do not mention entry IDs, refs, branches, sync, or
knowledge repo lifecycle mechanics unless debugging was explicitly requested.

Natural request: "Save this handoff for the next agent."
Agent action: `record(type="active", ...)`

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

The developer-facing confirmation should be a normal work sentence, for example:
"Submitted the decision for team review." The review plumbing stays inside the
knowledge workflow unless debugging was explicitly requested.

Natural request: "Record this as a team decision."
Agent action: `propose(type="decision", ...)`

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
