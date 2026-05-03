# Jurati

Shared team intelligence layer for agentic workflows.

Jurati gives AI coding agents (and humans) a shared memory — architectural principles, workflow preferences, decision history, and cross-project state — backed by a plain git repository and served via MCP.

## Quick Start

```bash
pip install jurati
jurati serve
```

Configure your MCP client (e.g. `~/.claude/mcp.json` for Claude Code):

```json
{
  "mcpServers": {
    "jurati": {
      "command": "jurati",
      "args": ["serve"],
      "env": {
        "JURATI_KNOWLEDGE_REMOTE": "git@github.com:your-org/jurati-knowledge.git"
      }
    }
  }
}
```

The server clones the knowledge repo to `~/.cache/jurati` on startup and syncs periodically.

## User Guide

### Knowledge Model

Every piece of knowledge is a markdown file with YAML frontmatter stored in a git repo. Entries have a **type** that determines their escalation level and how they're written:

| Type | Level | Write Tool | What It Captures |
|------|-------|------------|-----------------|
| `active` | L0 | `record` | Ephemeral state — current work, investigations, session context |
| `project` | L1 | `record` | Ongoing initiatives, goals, status updates |
| `workflow` | L2 | `propose` | Team processes, how things get done |
| `decision` | L2/L3 | `propose` | Architectural and design choices with rationale |
| `principle` | L3 | `propose` | Core beliefs that guide all other decisions |

**Escalation levels** control the write path:
- **L0** — pushed via git active refs (no PR, no review, instant)
- **L1** — lightweight PR with `low-ceremony` label (auto-mergeable)
- **L2** — review PR with `review-required` label
- **L3** — review PR (highest ceremony, for foundational entries)

### MCP Tools

#### Reading

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `query` | Semantic search across entries | `topic` (required), `type`, `project`, `status` |
| `read` | Fetch a single entry by ID | `id` (required) |
| `list_entries` | Browse entries with filters | `type`, `project`, `status`, `include_expired` |

#### Writing

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `record` | Create L0/L1 entries (low ceremony) | `type`, `title`, `content` (all required); `entry_id`, `level`, `projects`, `tags`, `expires_at` |
| `propose` | Create L2/L3 entries via review PR | `type`, `title`, `content` (all required); `entry_id`, `level`, `projects`, `tags` |

#### Maintenance

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `sync` | Fetch latest from remote and rebuild index | _(none)_ |
| `validate` | Check entry schema/frontmatter correctness | `id` (optional — validates all if omitted) |
| `expire` | Remove an entry (L0 deletes ref, L1+ opens PR) | `id` (required), `reason` |

### Examples

**Record what you're working on:**
```
record(type="active", title="Investigating auth latency spike",
       content="p99 jumped from 120ms to 800ms after deploy 4.2.1. Checking middleware chain.",
       tags=["incident", "auth"])
```

**Capture a team decision:**
```
propose(type="decision", title="Use PostgreSQL for event sourcing",
        content="Evaluated Kafka, EventStoreDB, and PG. PG chosen for operational simplicity...",
        projects=["billing-v2"], tags=["architecture", "database"])
```

**Search for prior art:**
```
query(topic="authentication middleware")
query(topic="database migrations", type="decision")
```

**Clean up expired state:**
```
expire(id="abc123def456", reason="Investigation resolved, root cause was connection pool exhaustion")
```

### Configuration

All configuration is via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JURATI_KNOWLEDGE_REMOTE` | Yes | — | Git remote URL for the knowledge repo |
| `JURATI_CLIENT_SLUG` | No | `claude-code` | Identifies the client in L0 active ref paths |
| `JURATI_CACHE_DIR` | No | `~/.cache/jurati` | Local clone location |
| `JURATI_MAIN_BRANCH` | No | `main` | Branch to read committed entries from |
| `JURATI_BRANCH_PREFIX` | No | `jurati` | Prefix for branches created by record/propose |
| `JURATI_ACTIVE_REF_PREFIX` | No | `jurati/active` | Git ref namespace for L0 entries |
| `JURATI_SYNC_INTERVAL` | No | `300` | Seconds between automatic syncs |

## Privacy

Jurati is a broadcast system, not an observation system. No telemetry, no participation tracking, no query logging, no absence signals. Sharing is always explicit and intentional.

## Development

```bash
git clone https://github.com/RedHatTraining/jurati.git
cd jurati
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

MIT
