# Jurati

[![Development Status: 4 - Beta](https://img.shields.io/badge/Development%20Status-4%20--%20Beta-yellow)](https://pypi.org/classifiers/)

Reviewable project context for AI coding agents, backed by git.

## Get Started

```bash
pip install jurati
cd your-project
jurati onboard
```

Start a new coding session. Say "save where I left off" and the next session
picks it up.

## What It Does

AI agents start every task from scratch. They see the code but not what you
decided last week, what someone else is working on, or where you left off
yesterday. Jurati gives agents a shared context layer so they start with the
decisions, handoffs, and project state that matter before they touch code.

The context lives in a git repository of reviewed Markdown entries. Jurati
indexes, ranks, and serves it through
[MCP](https://modelcontextprotocol.io/introduction) (the standard protocol
that lets AI coding tools connect to external tools) or through a plain
context file any agent can read.

## Who It's For

Jurati works for any developer workflow where context has to survive one chat,
one repo, or one person.

| Use case | What Jurati gives you |
|----------|------------------------|
| Solo developers | Continuity across repos, days, and multiple agents. Future you and the next agent see the blockers, handoffs, and decisions that matter. |
| Small teams | Shared active work, workflow expectations, and decisions without turning every useful note into a meeting. |
| Growing orgs | Reviewable agent guidance through pull requests, scoped by project, with lifecycle controls for stale context. |

## How It Works

```
                  ┌──────────────────┐
                  │  Knowledge Repo  │  Reviewed Markdown + YAML frontmatter
                  │    (normal git)  │  in git — PRs, history, provenance
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │   Jurati Server  │  MCP server — indexes, ranks, filters,
                  │                  │  enforces privacy + content safety
                  └────────┬─────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼───── ┐ ┌───▼───┐ ┌──────▼──────┐
        │ Claude Code│ │Cursor │ │ Any MCP     │
        │            │ │       │ │ client      │
        └─────────── ┘ └───────┘ └─────────────┘
```

When a developer starts a task, the agent:

1. Calls `sync()` to refresh its local index
2. Calls `context(repo=..., goal=...)` to get relevant shared context
3. Follows the returned verdict or coordination guidance
4. Reads source text only for entries it directly relies on
5. Summarizes what matters, then works normally

When the developer says "save this handoff" or "record this decision," the
agent translates that into the right API call. The developer never needs to
learn the tool interface.

## What Agents See

| Tool | Purpose |
|------|---------|
| `startup()` | Combined sync + context in one call (recommended entry point) |
| `context()` | Relevant decisions, project state, and coordination signals |
| `sync()` | Refresh local index from the knowledge repo |
| `read()` / `read_many()` | Source text for entries the agent directly relies on |
| `query()` | Deep-dive on a specific topic |
| `search()` | BM25 keyword search across all entries |
| `list_entries()` | Browse entries with optional filters |
| `hygiene()` | Lifecycle and curation advisories for stale context |
| `record()` | Write a project update, handoff, or active note |
| `propose()` | Submit a decision or workflow for deliberate review via PR |
| `expire()` | Mark an entry as expired |
| `explain()` | Print what Jurati does and does not track |
| `status()` | Show connection health and sync state |
| `validate()` | Check entries for schema or constraint violations |

## What Goes in the Knowledge Repo

| Type | Examples |
|------|----------|
| `decision` | "Use gRPC between internal services" — with rationale |
| `workflow` | "Run validation before review" — recurring process |
| `project` | "Auth migration is in flight" — current state |
| `active` | "Left off at the token endpoint" — short-lived handoff |
| `principle` | "Restricted data stays out of context entries" — durable standard |

Entries are Markdown files with validated YAML frontmatter. Here's what a
decision entry looks like:

```yaml
---
type: decision
title: Use gRPC for internal services
status: active
projects: [api-platform]
created: 2026-01-15T10:00:00Z
---

REST endpoints between auth and billing are creating versioning friction.
Use gRPC for all new internal service communication. REST stays for public APIs.
```

Durable entries go through pull request review. Handoffs are short-lived and
expire automatically.

## Quick Start

Jurati requires Python 3.12+.

### Solo / Local Setup

```bash
pip install jurati
cd /path/to/your-project
jurati onboard --yes
```

This creates a local knowledge repo, adds agent instructions to your project's
`CLAUDE.md`, and configures the MCP server. Handoffs are enabled by default.
Restart your coding agent and you're ready to go.

### Team Setup

To share context across a team, provide a git remote:

```bash
jurati onboard --remote git@github.com:your-org/team-knowledge.git
```

Team members connect to an existing knowledge repo with the same command
using the same remote URL.

### Verify

```bash
jurati doctor --check-startup
```

For troubleshooting, see [Install And Troubleshooting](docs/install-troubleshooting.md).

## Daily Use

You don't need to learn Jurati's API. Just talk to your agent normally:

```text
"Update the login flow to use the new token endpoint."
→ Agent checks shared context automatically before working

"Save this handoff for tomorrow."
→ Agent writes an active record

"Record this as a project decision: use server-driven token rotation."
→ Agent proposes a reviewed decision via PR

"What did we decide about the auth migration?"
→ Agent queries the knowledge repo
```

Run `jurati --help` for the full command list.

## Privacy

Jurati is a broadcast system, not an observation system. It does not log
queries, create read receipts, infer presence from activity, or track
participation. Writes happen only when explicitly requested. Active context
is disabled by default.

Security, privacy, and content safety are release gates for this product, not
optional hardening. See [Security Policy](SECURITY.md).

## Secret Scanning and Content Safety

All writes are checked before reaching the knowledge repo:

- **Credentials and secrets** are blocked (API keys, tokens, passwords)
- **PII and personnel content** are flagged for review
- **Signal text** from PRs and issues is sanitized before surfacing

## Coordination Signals

Jurati reads labeled PRs and issues from configured repos and surfaces
coordination effects: continue, reuse, revise, pause, handoff, or clarify.
GitHub PR signals and Jira issue signals are supported.

Configure with environment variables:

```bash
# GitHub
JURATI_PR_SIGNAL_REPOS=your-org/repo1,your-org/repo2

# Jira
JURATI_SIGNAL_PROVIDER=jira
JURATI_JIRA_BASE_URL=https://jira.example.com
JURATI_JIRA_PROJECTS=PROJ1,PROJ2
```

## Curation

Shared context needs maintenance. Jurati can generate reviewable curation
branches that expire stale active context and mark durable decisions,
workflows, projects, and principles for revalidation when completed work
touches related metadata. Agents also receive quiet curation advisories inside
`context()` so they know when not to rely on stale entries during normal work.

## CLI Reference

| Command | Purpose |
|---------|---------|
| `jurati serve` | Start the MCP server over stdio |
| `jurati onboard` | Guided first-time setup |
| `jurati doctor` | Check configuration and connectivity |
| `jurati validate` | Validate knowledge entries |
| `jurati import-docs` | Import ADRs, RFCs, selected docs, or note exports |
| `jurati import-context` | Import a packaged context pack |
| `jurati install-hook` | Install ambient commit capture hooks |
| `jurati install-claude-md` | Add or update Jurati agent instructions in CLAUDE.md |
| `jurati explain` | Print the product boundary |
| `jurati html` | Generate a static knowledge browser |

Run `jurati --help` for the full list.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `JURATI_KNOWLEDGE_REMOTE` | - | Git remote for the knowledge repo |
| `JURATI_ACTIVE_REFS_ENABLED` | `false` | Enable instant active context sharing |
| `JURATI_ACTIVE_REF_TTL_HOURS` | `72` | Maximum TTL for active context entries |
| `JURATI_SIGNAL_PROVIDER` | `github` | Signal source: `github` or `jira` |
| `JURATI_PR_SIGNAL_REPOS` | - | Repos for GitHub PR signals |
| `JURATI_JIRA_BASE_URL` | - | Jira instance URL |
| `JURATI_JIRA_PROJECTS` | - | Jira project keys |

See [Install And Troubleshooting](docs/install-troubleshooting.md) for setup
and common client issues.

## Documentation

| Guide | Audience |
|-------|----------|
| [Install And Troubleshooting](docs/install-troubleshooting.md) | Setup, configuration, and common issues |
| [Contributing](CONTRIBUTING.md) | Development setup, testing, code style |
| [Security](SECURITY.md) | Vulnerability reporting and supported versions |

## Development

```bash
git clone https://github.com/ostinato-forge/jurati.git
cd jurati
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q && ruff check . && mypy src
```

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Disclaimer

This is a personal project. It does not represent the views, policies, or
endorsement of my employer.
