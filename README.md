# Jurati

Shared agent context for people and AI agents.

## What this does for you

Your agent reads the team's reviewable context before every session. When you start
working, it already knows someone switched the session store last week, that
there's an open PR migrating the module you're about to touch, and that the
team agreed to use gRPC for inter-service calls. You don't check Slack, read a
design doc, or ask around — the context is already there.

You contribute by writing `jurati:` in your commit messages when you make a
decision worth sharing. A git hook extracts it, creates a PR on the knowledge
repo, and most of the time auto-merges it. No separate tool, no context switch.

The agent doesn't just answer your questions — it asks better questions of
itself before it answers yours. If the team decided something, the agent won't
propose the opposite. If someone's mid-migration on code you're about to
change, the agent flags the conflict before you create a mess. The team's
decisions, in-flight work, and conventions shape every suggestion the agent
makes.

## Works with any agent

Jurati uses MCP, so it works with any agent that speaks the protocol — Claude
Code, Copilot, Cursor, or your own tooling. Each agent identifies itself with a
client slug (`JURATI_CLIENT_SLUG`), and its short-lived active context is
namespaced so agents don't step on each other. Everything above that — decisions,
workflows, principles, search results — is shared.

A team with three developers on three different tools all writes to the same
knowledge repo, sees each other's decisions and active work, and benefits from
the same team context.

## How it works

Two pieces:

- **A knowledge repo** — a git repository of markdown files containing your
  team's decisions, principles, workflows, and project state.
- **An MCP server** — a thin interface that lets agents query, read, and write
  to that repo through structured tools.

Agents search before they start, read what matters, and write back only when
explicitly asked — through branches and pull requests, never by silently mutating
your source of truth.

Jurati is not a personal second brain, CRM, graph database, or telemetry
system. Markdown is the human-reviewable source format; the MCP server builds
structured indexes from it so agents can retrieve only the context they need.
See [Context, Not Memory](docs/context-not-memory.md) for the architecture
boundary and [Context Packs Build Plan](docs/context-packs-plan.md) for the
Obsidian-backed workflow migration path. For hands-on migration steps, see
[Context Pack Migration](docs/context-pack-migration.md).

### Knowledge entries

Entries are markdown files with YAML frontmatter, organized by type:

| Type | What it captures |
|------|-----------------|
| **Principles** | Long-lived standards that span projects |
| **Decisions** | Design choices with rationale and alternatives |
| **Workflows** | Team processes — review gates, release steps, conventions |
| **Projects** | What's in flight, what's blocked, cross-project context |
| **Active** | Short-lived notes — current investigations, handoffs (opt-in) |

Every write goes through git. Lightweight entries (active work, project updates)
create low-ceremony PRs. Durable entries (decisions, principles) require human
review before they reach `main`. Nothing pushes directly to a protected branch.

### Escalation levels

| Level | Mechanism | Review | Example |
|-------|-----------|--------|---------|
| L0 | Active ref overlay | None | Current focus, handoff notes |
| L1 | Lightweight PR | Auto-merge | Project status updates |
| L2 | Reviewed PR | Required | Workflow changes, design decisions |
| L3 | Reviewed PR | Required | Engineering principles |

`record()` handles L0/L1. `propose()` handles L2/L3. The boundary is enforced
in code — higher-stakes tools cannot create lower-stakes content and vice versa.

### Visibility and access modes

Entries declare their distribution scope:

- **internal** (default) — visible within jurati's own MCP tools
- **external** — opted in for cross-system distribution

External systems consume jurati through named access modes that filter entries
by visibility, sensitivity, and branch location:

| Access mode | What it sees |
|-------------|-------------|
| `context` | All non-restricted entries (MCP tools use this) |
| `external_context` | Only `visibility=external` entries |
| `gate_evidence` | External entries on the source-of-truth branch |
| `durable_source` | All entries on the source-of-truth branch |

### Ambient capture

Prefix a commit message with `jurati:` and the entry type, and a git hook
extracts it:

```
jurati: decision — Use one validation command before review
```

This turns normal development activity into shared knowledge without requiring
anyone to stop and open a separate tool.

### Coordination signals

Jurati watches labeled PRs in configured repos and classifies them into
coordination effects: continue, reuse, revise, pause, handoff, or clarify.
When you start work, your agent sees whether someone's open PR affects the
code you're about to touch.

Signal providers are pluggable — GitHub PRs ship built-in, and the provider
protocol supports Jira, Linear, or any system that produces coordination
artifacts.

### Privacy

Jurati is a broadcast system, not an observation system. It does not log
queries, track who read what, measure participation, or infer presence from
agent activity. Git provenance exists for accountability — Jurati does not
repurpose it as surveillance.

Restricted entries (`sensitivity: restricted`) are excluded from all search
results, context responses, and the BM25 index. They are only accessible via
explicit `read(id=...)` calls.

When entries cross integration boundaries, author identities are salted per
requesting system to prevent cross-system correlation.

## Quick start

Install:

```bash
pipx install git+https://github.com/ostinato-forge/jurati.git
```

Set up a knowledge repo:

```bash
jurati quickstart ./jurati-knowledge \
  --remote git@github.com:your-org/jurati-knowledge.git
```

This creates the knowledge repo scaffold, starter entries, and a
`.claude/settings.json` allowlist so read-only startup tools do not prompt on
every context check.

Check everything works:

```bash
export JURATI_KNOWLEDGE_REMOTE=git@github.com:your-org/jurati-knowledge.git
jurati doctor
jurati doctor --check-startup
```

`doctor --check-startup` fetches and indexes the configured knowledge repo, so
you know the read path behind `sync()` and `context()` works before depending
on it in an agent session.

### Zero-setup for existing repos

Install the CLAUDE.md section and settings.json into any repo that should use
the shared knowledge:

```bash
jurati install-claude-md --repo-path . \
  --remote git@github.com:your-org/jurati-knowledge.git
```

### MCP config

Generate the MCP server config for your client:

```bash
jurati mcp-config --remote git@github.com:your-org/jurati-knowledge.git
```

For project-local Claude Code config, let Jurati write the hash-named server
entry so it does not collide with older global `jurati` entries:

```bash
jurati mcp-config --remote git@github.com:your-org/jurati-knowledge.git --write-project
```

Server names use a hash of the remote URL (`jurati-{hash}`) so multiple
knowledge repos don't collide in global config.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `JURATI_KNOWLEDGE_REMOTE` | — | Git remote URL for the knowledge repo (required) |
| `JURATI_CLIENT_SLUG` | `claude-code` | Client identifier for active-work refs |
| `JURATI_CACHE_DIR` | `~/.cache/jurati` | Local clone location |
| `JURATI_MAIN_BRANCH` | `main` | Source-of-truth branch |
| `JURATI_SYNC_INTERVAL` | `300` | Seconds between background syncs |
| `JURATI_ACTIVE_REFS_ENABLED` | `false` | Enable L0 active context (read and write) |
| `JURATI_REVISE_KEYWORDS` | — | Comma-separated override for coordination revise keywords |
| `JURATI_HANDOFF_KEYWORDS` | — | Comma-separated override for coordination handoff keywords |

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, testing, and pull request
guidelines.

For more on the thinking behind this project, see
[The Replacement Story Is Too Small](https://gist.github.com/tempo-64/a106ec28f2894f5c92e2e0f3ba080858).

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Disclaimer

This is a personal project. It does not represent the views, policies, or
endorsement of my employer. All opinions expressed in this project and its
documentation are my own.
