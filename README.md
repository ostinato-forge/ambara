# Jurati

Shared team memory for AI coding agents.

## What this means for you

Your agent reads the team's knowledge before every session. When you start
working on something, it already knows that someone switched the session store
last week, that there's an open PR migrating the module you're about to touch,
and that the team agreed to use gRPC for inter-service calls. You don't check
Slack, read a design doc, or ask around — the context is already there.

You contribute by writing `jurati:` in your commit messages when you make a
decision worth sharing. A git hook extracts it, creates a PR on the knowledge
repo, and most of the time auto-merges it. That's it. No separate tool, no
context switch.

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
workflows, principles, search results — is shared. A decision recorded by one
agent shows up in every other agent's context after sync.

A team with three developers on three different tools all writes to the same
knowledge repo, sees each other's decisions and active work, and benefits from
the same team memory.

## How it works

Two pieces:

- **A knowledge repo** — a git repository of markdown files containing your
  team's decisions, principles, workflows, and project state.
- **An MCP server** — a thin interface that lets agents query, read, and write
  to that repo through structured tools.

Agents search before they start, read what matters, and write back only when
explicitly asked — through branches and pull requests, never by silently mutating
your source of truth.

### Knowledge entries

Entries are markdown files with YAML frontmatter, organized by type:

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

### Ambient capture

Prefix a commit message with `jurati:` and the entry type, and a git hook or
GitHub Action extracts it:

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

Check everything works:

```bash
export JURATI_KNOWLEDGE_REMOTE=git@github.com:your-org/jurati-knowledge.git
jurati doctor
```

Add the MCP server to Claude Code (or any MCP client):

```bash
jurati mcp-config
```

Paste the output into your MCP config:

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

For more on the thinking behind this project, see
[The Replacement Story Is Too Small](https://gist.github.com/tempo-64/a106ec28f2894f5c92e2e0f3ba080858).

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Disclaimer

This is a personal project. It does not represent the views, policies, or
endorsement of my employer. All opinions expressed in this project and its
documentation are my own.
