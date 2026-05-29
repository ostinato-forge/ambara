# Jurati

[![Development Status: 5 - Production/Stable](https://img.shields.io/badge/Development%20Status-5%20--%20Production%2FStable-brightgreen)](https://pypi.org/classifiers/)

Reviewable project context for AI coding agents, backed by git.

AI agents start every task from scratch. They see the current prompt and the
local checkout, but not the decisions you or your team made last week, the PR
that conflicts with what they're about to do, or the workflow that says "run
validation before review." Jurati fixes that.

Jurati gives your agents a shared context layer, which is a git repository of
reviewed Markdown entries, so they start with the decisions, workflows, project
state, and coordination signals that matter before they touch code.

## Who It's For

Jurati is for any developer workflow where context has to survive one chat, one
repo, or one person.

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

Entries are Markdown files with validated YAML frontmatter. Durable entries
go through pull request review. Active entries are short-lived and expire
automatically.

## Quick Start

Jurati requires Python 3.12+.

### Install

```bash
pip install jurati
```

Or from source:

```bash
pipx install git+https://github.com/ostinato-forge/jurati.git
```

### Set Up a Project

Run guided onboarding from your project directory:

```bash
cd /path/to/your-project
jurati onboard
```

This creates a knowledge repo, adds the startup contract to your project's
`CLAUDE.md`, configures MCP, and sets up tool permissions. For scripted
setup:

```bash
jurati onboard \
  --remote git@github.com:your-org/jurati-knowledge.git \
  --knowledge-repo ./jurati-knowledge \
  --project-repo . \
  --pack engineering \
  --yes
```

### Verify

```bash
jurati doctor --team --check-startup
```

Then restart your MCP client and ask the agent to call `explain()` and
`status()`.

For the full setup walkthrough, see the
[Install And Troubleshooting Guide](docs/install-troubleshooting.md).

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

See the [Install And Troubleshooting Guide](docs/install-troubleshooting.md)
for setup and common failure modes.

## Privacy

Jurati is a broadcast system, not an observation system. It does not log
queries, create read receipts, infer presence from activity, or track
participation. Writes happen only when explicitly requested. Active context
is disabled by default.

Security, privacy, and content safety are release gates for this product, not
optional hardening. See [Security Policy](SECURITY.md).

## Content Safety

All writes are evaluated against content safety rules before reaching the
knowledge repo:

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
| `jurati install-claude-md` | Add or update the startup contract in CLAUDE.md |
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
| [Product and Tech Slides](product-and-tech-slides.html) | Product and technical overview (HTML) |
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
