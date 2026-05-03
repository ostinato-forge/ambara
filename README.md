# Jurati

Shared team memory for AI coding agents.

AI agents start every session cold — no memory of past decisions, no awareness of
what teammates are working on, no access to the workflows your team actually
follows. Jurati fixes this by giving every agent the same context a good teammate
would have.

It works through two pieces:

- **A knowledge repo** — a normal git repository of markdown files containing
  your team's decisions, principles, workflows, and project state.
- **An MCP server** — a thin interface that lets agents query, read, and write
  to that repo through structured tools.

Agents search before they start, read what matters, and write back only when
explicitly asked — through branches and pull requests, never by silently mutating
your source of truth.

## Quick Start

Install:

```bash
pipx install git+https://github.com/ostinato-forge/jurati.git
```

Set up a knowledge repo:

```bash
jurati quickstart ./jurati-knowledge \
  --remote git@github.com:your-org/jurati-knowledge.git
```

Check everything works:

```bash
export JURATI_KNOWLEDGE_REMOTE=git@github.com:your-org/jurati-knowledge.git
jurati doctor
```

Add the MCP server to Claude Code (or any MCP client):

```bash
jurati mcp-config
```

Paste the output into `~/.claude/mcp.json`:

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

That's it. Agents now have access to your team's shared knowledge.

## How It Works

Knowledge entries are markdown files with YAML frontmatter, organized by type:

| Type | What it captures |
|------|-----------------|
| **Principles** | Long-lived engineering standards that span projects |
| **Decisions** | Design choices with rationale and alternatives |
| **Workflows** | Team processes — review gates, release steps, conventions |
| **Projects** | What's in flight, what's blocked, cross-project context |
| **Active** | Short-lived notes — current investigations, handoffs |

Every write goes through git. Lightweight entries (active work, project updates)
create low-ceremony PRs. Durable entries (decisions, principles) require human
review before they reach `main`. Nothing pushes directly to a protected branch.

### Ambient Capture

Jurati entries can also be captured from git commits. Prefix a commit message
with `jurati:` and the entry type, and a git hook or GitHub Action will extract
it:

```
jurati: decision — Use one validation command before review
```

This turns normal development activity into shared knowledge without requiring
anyone to stop and open a separate tool.

### Privacy

Jurati is a broadcast system, not an observation system. It does not log queries,
track who read what, measure participation, or infer presence from agent
activity. Git provenance exists for accountability — Jurati does not repurpose it
as surveillance.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `JURATI_KNOWLEDGE_REMOTE` | — | Git remote URL for the knowledge repo (required) |
| `JURATI_CLIENT_SLUG` | `claude-code` | Client identifier for active-work refs |
| `JURATI_CACHE_DIR` | `~/.cache/jurati` | Local clone location |
| `JURATI_MAIN_BRANCH` | `main` | Source-of-truth branch |
| `JURATI_SYNC_INTERVAL` | `300` | Seconds between background syncs |

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, testing, and pull request
guidelines.

## Why "Jurati"

The name comes from Dr. Agnes Jurati in *Star Trek: Picard*. A cybernetics
researcher, she merges with the Borg Queen and transforms the Collective from a
system built on assimilation into one built on consent — shared cognition with
governance, boundaries, and voluntary participation.

That felt like the right reference for a project concerned with what a group
knows, what it should forget, and who gets to decide.

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Disclaimer

This is a personal project by [Edgar Parenti](https://github.com/tempo-64). It
does not represent the views, policies, or endorsement of my employer. All
opinions expressed in this project and its documentation are my own.
