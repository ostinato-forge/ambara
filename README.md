# Ambara

[![Development Status: 4 - Beta](https://img.shields.io/badge/Development%20Status-4%20--%20Beta-yellow)](https://pypi.org/classifiers/)

AI coding agents forget everything between sessions. Ambara fixes that.

## Get Started

```bash
pip install ambara
cd your-project
ambara onboard
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

Ambara gives your coding agents shared context that survives across sessions,
repos, and people. You record a decision or hand off work, and the next agent
starts with that context before it touches code.

Ambara also shows value as restraint: startup/context packets include a compact
receipt showing the small Ambara payload, full bodies deferred to explicit
reads, and estimated tokens avoided versus a full eligible context dump. A
local value ledger can be enabled for longer-running proof with `ambara value`.

Under the hood, context lives in a git repository of Markdown files with YAML
frontmatter. Ambara indexes, ranks, and serves it through
[MCP](https://modelcontextprotocol.io/introduction) (the protocol that lets
AI coding tools connect to external tools) or through a plain context file
any agent can read. You don't need to know any of that to use it.

## Who It's For

| Use case | What Ambara gives you |
|----------|----------------------|
| Solo developers | Continuity across repos, days, and multiple agents. Future you and the next agent see the handoffs and decisions that matter. |
| Small teams | Shared work context and decisions without turning every useful note into a meeting. |
| Growing orgs | Reviewable agent guidance through pull requests, scoped by project, with lifecycle controls. |

## Setup

Ambara requires Python 3.12+.

### Solo / Local

```bash
pip install ambara
cd your-project
ambara onboard --yes
```

Creates a local context repo, adds agent instructions to your CLAUDE.md,
configures the MCP server, and enables handoffs. Restart your coding agent
and you're ready.

### Team

```bash
ambara onboard --remote git@github.com:your-org/team-context.git
```

Team members connect with the same command using the same remote URL.

### Verify

```bash
ambara doctor --check-startup
```

For troubleshooting, see [Install And Troubleshooting](docs/install-troubleshooting.md).

## What a Saved Entry Looks Like

When you say "record this as a decision," Ambara creates a Markdown file:

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

Ambara does not log what agents read, track who's online, or create activity
feeds. It only stores what you explicitly ask it to save. There is no
collector for query text, read patterns, editor activity, or participation
data. The system can't track what it was never built to capture.

Value receipts and the optional local value ledger keep the same boundary:
they record aggregate token estimates and omission/suppression counts only.
They do not store query text, response text, body snippets, caller identity, or
durable per-entry read receipts. Reported savings are Ambara app-payload
estimates, not total client/session/cache billing.

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
              │  Ambara Server   │  Indexes, ranks, filters,
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
| `feedback(entry_id, signal)` | Mark context as useful, noisy, stale, duplicate, or pinned locally |
| `explain()` | Print what Ambara does and does not track |
| `status()` | Show connection health and sync state |
| `validate()` | Check entries for schema or constraint violations |

Startup packets include a compact `value` receipt. Compiler packets include
`cost_accounting` detail for debugging and proof. Full bodies stay deferred
until `read()` or `read_many()` is explicitly needed.

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

Ambara reads labeled PRs and issues from configured repos and surfaces them
as project context: continue, reuse, revise, pause, handoff, or clarify.
GitHub and Jira are supported.

```bash
AMBARA_PR_SIGNAL_REPOS=your-org/repo1,your-org/repo2
AMBARA_SIGNAL_PROVIDER=jira
AMBARA_JIRA_BASE_URL=https://jira.example.com
AMBARA_JIRA_PROJECTS=PROJ1,PROJ2
```

### Curation

Context needs maintenance. Ambara generates cleanup PRs that expire stale
handoffs and flag durable entries for revalidation. Agents also get quiet
advisories inside `context()` so they know not to rely on stale entries.

### CLI Reference

| Command | Purpose |
|---------|---------|
| `ambara serve` | Start the MCP server over stdio |
| `ambara onboard` | Guided first-time setup |
| `ambara doctor` | Check configuration and connectivity |
| `ambara validate` | Validate context entries |
| `ambara import-docs` | Import ADRs, RFCs, or selected docs |
| `ambara import-context` | Import a packaged context pack |
| `ambara install-hook` | Install ambient commit capture hooks |
| `ambara install-claude-md` | Add or update agent instructions in CLAUDE.md |
| `ambara explain` | Print the product boundary |
| `ambara value` | Show local app-payload savings estimates |
| `ambara feedback` | Record local relevance feedback for an entry |
| `ambara html` | Generate a static context browser |

Run `ambara --help` for the full list.

### Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `AMBARA_KNOWLEDGE_REMOTE` | - | Git remote for the context repo |
| `AMBARA_ACTIVE_REFS_ENABLED` | `true` | Enable session handoffs |
| `AMBARA_ACTIVE_REF_TTL_HOURS` | `72` | How long handoffs stay active |
| `AMBARA_SIGNAL_PROVIDER` | `github` | Signal source: `github` or `jira` |
| `AMBARA_PR_SIGNAL_REPOS` | - | Repos for GitHub PR signals |
| `AMBARA_JIRA_BASE_URL` | - | Jira instance URL |
| `AMBARA_JIRA_PROJECTS` | - | Jira project keys |
| `AMBARA_CONTEXT_BUDGET_MODE` | `balanced` | `quiet`, `balanced`, or `deep` context packing |
| `AMBARA_VALUE_LEDGER_PATH` | - | Enables local JSONL value ledger at this path |
| `AMBARA_VALUE_LEDGER_ENABLED` | path-dependent | Force local value ledger on/off |

### Documentation

| Guide | Audience |
|-------|----------|
| [Install And Troubleshooting](docs/install-troubleshooting.md) | Setup, configuration, and common issues |
| [Contributing](CONTRIBUTING.md) | Development setup, testing, code style |
| [Security](SECURITY.md) | Vulnerability reporting and supported versions |

### Development

```bash
git clone https://github.com/ostinato-forge/ambara.git
cd ambara
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q && ruff check . && mypy src
```

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Disclaimer

This is a personal project. It does not represent the views, policies, or
endorsement of my employer.
