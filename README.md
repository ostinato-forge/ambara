# Jurati

[![Development Status: 4 - Beta](https://img.shields.io/badge/Development%20Status-4%20--%20Beta-yellow)](https://pypi.org/classifiers/)

AI coding agents forget everything between sessions. Jurati fixes that.

## Get Started

```bash
pip install jurati
cd your-project
jurati onboard
```

Restart your coding agent. Done.

## What You Say

You don't learn an API. You just talk to your agent like you already do:

```text
"Save where I left off."
→ Saved. Next session picks it up.

"We decided to use gRPC for internal services. Record that."
→ Saved as a decision. Goes through PR review.

"What did we decide about the auth migration?"
→ Agent checks the context repo and tells you.

"Update the login flow to use the new token endpoint."
→ Agent checks for relevant context before working.
```

## What It Does

Jurati gives your coding agents shared context that survives across sessions,
repos, and people. You record a decision or hand off work, and the next agent
starts with that context before it touches code.

Under the hood, context lives in a git repository of Markdown files with YAML
frontmatter. Jurati indexes, ranks, and serves it through
[MCP](https://modelcontextprotocol.io/introduction) (the protocol that lets
AI coding tools connect to external tools) or through a plain context file
any agent can read. You don't need to know any of that to use it.

## Who It's For

| Use case | What Jurati gives you |
|----------|----------------------|
| Solo developers | Continuity across repos, days, and multiple agents. Future you and the next agent see the handoffs and decisions that matter. |
| Small teams | Shared work context and decisions without turning every useful note into a meeting. |
| Growing orgs | Reviewable agent guidance through pull requests, scoped by project, with lifecycle controls. |

## Setup

Jurati requires Python 3.12+.

### Solo / Local

```bash
pip install jurati
cd your-project
jurati onboard --yes
```

Creates a local context repo, adds agent instructions to your CLAUDE.md,
configures the MCP server, and enables handoffs. Restart your coding agent
and you're ready.

### Team

```bash
jurati onboard --remote git@github.com:your-org/team-context.git
```

Team members connect with the same command using the same remote URL.

### Verify

```bash
jurati doctor --check-startup
```

For troubleshooting, see [Install And Troubleshooting](docs/install-troubleshooting.md).

## What a Saved Entry Looks Like

When you say "record this as a decision," Jurati creates a Markdown file:

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

Decisions and workflows go through PR review. Handoffs are short-lived and
expire automatically.

## Privacy

Jurati does not log what agents read, track who's online, or create activity
feeds. It only stores what you explicitly ask it to save. There is no
collector for query text, read patterns, editor activity, or participation
data. The system can't track what it was never built to capture.

Security, privacy, and secret scanning are release gates for this product,
not optional hardening. See [Security Policy](SECURITY.md).

---

## Reference

Everything below here is reference material. You don't need it to get started.

### How It Works

```
              ┌──────────────────┐
              │  Context Repo    │  Reviewed Markdown + YAML frontmatter
              │  (normal git)    │  in git — PRs, history, provenance
              └────────┬─────────┘
                       │
              ┌────────▼─────────┐
              │  Jurati Server   │  Indexes, ranks, filters,
              │                  │  enforces privacy + secret scanning
              └────────┬─────────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
    ┌─────▼─────┐ ┌───▼───┐ ┌─────▼──────┐
    │Claude Code│ │Cursor │ │ Any MCP    │
    │           │ │       │ │ client     │
    └───────────┘ └───────┘ └────────────┘
```

When a developer starts a task, the agent calls `startup()` to get relevant
context, then works normally. When the developer says "save this" or "record
that decision," the agent handles the filing.

### What Agents See

| Tool | Purpose |
|------|---------|
| `startup()` | Get relevant context before working (recommended entry point) |
| `context()` | Relevant decisions, project state, and project signals |
| `sync()` | Refresh local index from the context repo |
| `read()` / `read_many()` | Full text for entries the agent directly relies on |
| `query()` | Deep-dive on a specific topic |
| `search()` | Keyword search across all entries |
| `record()` | Save a handoff, project update, or active note |
| `propose()` | Save a decision or workflow for team review via PR |
| `hygiene()` | Lifecycle advisories for stale context |
| `list_entries()` | Browse entries with optional filters |
| `expire()` | Mark an entry as expired |
| `explain()` | Print what Jurati does and does not track |
| `status()` | Show connection health and sync state |
| `validate()` | Check entries for schema or constraint violations |

### Entry Types

| Type | What it's for |
|------|---------------|
| `active` | Short-lived handoffs. "Left off at the token endpoint." Expires automatically. |
| `project` | Current project state. "Auth migration is in flight." |
| `decision` | Reviewed team decision. "Use gRPC for internal services." Goes through PR. |
| `workflow` | Recurring team process. "Run validation before review." Goes through PR. |
| `principle` | Durable standard. "Restricted data stays out of context entries." |

### Secret Scanning

All writes are checked before reaching the context repo:

- **Credentials and secrets** are blocked (API keys, tokens, passwords)
- **PII and personnel content** are flagged for review
- **Signal text** from PRs and issues is sanitized before surfacing

### Project Signals

Jurati reads labeled PRs and issues from configured repos and surfaces them
as project context: continue, reuse, revise, pause, handoff, or clarify.
GitHub and Jira are supported.

```bash
JURATI_PR_SIGNAL_REPOS=your-org/repo1,your-org/repo2
JURATI_SIGNAL_PROVIDER=jira
JURATI_JIRA_BASE_URL=https://jira.example.com
JURATI_JIRA_PROJECTS=PROJ1,PROJ2
```

### Curation

Context needs maintenance. Jurati generates cleanup PRs that expire stale
handoffs and flag durable entries for revalidation. Agents also get quiet
advisories inside `context()` so they know not to rely on stale entries.

### CLI Reference

| Command | Purpose |
|---------|---------|
| `jurati serve` | Start the MCP server over stdio |
| `jurati onboard` | Guided first-time setup |
| `jurati doctor` | Check configuration and connectivity |
| `jurati validate` | Validate context entries |
| `jurati import-docs` | Import ADRs, RFCs, or selected docs |
| `jurati import-context` | Import a packaged context pack |
| `jurati install-hook` | Install ambient commit capture hooks |
| `jurati install-claude-md` | Add or update agent instructions in CLAUDE.md |
| `jurati explain` | Print the product boundary |
| `jurati html` | Generate a static context browser |

Run `jurati --help` for the full list.

### Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `JURATI_KNOWLEDGE_REMOTE` | - | Git remote for the context repo |
| `JURATI_ACTIVE_REFS_ENABLED` | `true` | Enable session handoffs |
| `JURATI_ACTIVE_REF_TTL_HOURS` | `72` | How long handoffs stay active |
| `JURATI_SIGNAL_PROVIDER` | `github` | Signal source: `github` or `jira` |
| `JURATI_PR_SIGNAL_REPOS` | - | Repos for GitHub PR signals |
| `JURATI_JIRA_BASE_URL` | - | Jira instance URL |
| `JURATI_JIRA_PROJECTS` | - | Jira project keys |

### Documentation

| Guide | Audience |
|-------|----------|
| [Install And Troubleshooting](docs/install-troubleshooting.md) | Setup, configuration, and common issues |
| [Contributing](CONTRIBUTING.md) | Development setup, testing, code style |
| [Security](SECURITY.md) | Vulnerability reporting and supported versions |

### Development

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
