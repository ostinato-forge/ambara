# Jurati

Reviewable team context for AI coding agents, backed by git.

AI agents start every task from scratch. They see the current prompt and the
local checkout, but not the decisions your team made last week, the PR that
conflicts with what they're about to do, or the workflow that says "run
validation before review." Jurati fixes that.

Jurati gives your agents a shared context layer, which is a git repository of reviewed
Markdown entries, so they start with the team's decisions, workflows, project
state, and coordination signals before they touch code.

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
2. Calls `context(repo=..., goal=...)` to get relevant team context
3. Follows the returned verdict or coordination guidance
4. Reads source text only for entries it directly relies on
5. Summarizes what matters, then works normally

When the developer says "save this handoff" or "record this decision," the
agent translates that into the right API call. The developer never needs to
learn the tool interface.

## What Agents See

| Tool | Purpose |
|------|---------|
| `context()` | Relevant decisions, project state, and coordination signals |
| `read()` / `read_many()` | Source text for entries the agent directly relies on |
| `query()` | Deep-dive on a specific topic |
| `search()` | BM25 keyword search across all entries |
| `hygiene()` | Lifecycle and curation advisories for stale context |
| `record()` | Write a project update, handoff, or active note |
| `propose()` | Submit a decision or workflow for team review via PR |

## What Goes in the Knowledge Repo

| Type | Examples |
|------|----------|
| `decision` | "Use gRPC between internal services" — with rationale |
| `workflow` | "Run validation before review" — team process |
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
  --remote git@github.com:your-org/team-knowledge.git \
  --knowledge-repo ./team-knowledge \
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

For the full setup walkthrough, see the [User Guide](docs/guide.md).

## Daily Use

You don't need to learn Jurati's API. Just talk to your agent normally:

```text
"Update the login flow to use the new token endpoint."
→ Agent checks team context automatically before working

"Save this handoff for the next person."
→ Agent writes an active record

"Record this as a team decision: use server-driven token rotation."
→ Agent proposes a reviewed decision via PR

"What did we decide about the auth migration?"
→ Agent queries the knowledge repo
```

See the [User Guide](docs/guide.md) for the full daily workflow.

## Privacy

Jurati is a broadcast system, not an observation system. It does not log
queries, create read receipts, infer presence from activity, or track
participation. Writes happen only when explicitly requested. Active context
is disabled by default. See [Privacy Boundary](docs/context-not-memory.md)
for the full design.

Security, privacy, and content safety are release gates for this product, not
optional hardening. See the
[Security, Privacy, And Content Safety Gate](docs/security-privacy-content-safety.md)
and [current audit](docs/security-privacy-content-safety-audit.md).

## Content Safety

All writes are evaluated against content safety rules before reaching the
knowledge repo:

- **Credentials and secrets** are blocked (API keys, tokens, passwords)
- **PII and personnel content** are flagged for review
- **Signal text** from PRs and issues is sanitized before surfacing

## Coordination Signals

Jurati reads labeled PRs and issues from configured repos and surfaces
coordination effects: continue, reuse, revise, pause, handoff, or clarify.
GitHub PR signals and Jira issue signals ship today.

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

Team context needs maintenance. Jurati can generate reviewable curation
branches that expire stale active context and mark durable decisions,
workflows, projects, and principles for revalidation when completed work
touches related metadata. Agents also receive quiet curation advisories inside
`context()` so they know when not to rely on stale entries during normal work.

## CLI Reference

| Command | Purpose |
|---------|---------|
| `jurati onboard` | Guided first-time setup |
| `jurati doctor` | Check configuration and connectivity |
| `jurati validate` | Validate knowledge entries |
| `jurati import-docs` | Import ADRs, RFCs, selected docs, or note exports |
| `jurati import-context` | Import a packaged context pack |
| `jurati install-hook` | Install ambient commit capture hooks |
| `jurati explain` | Print the product boundary |
| `jurati html` | Generate a static knowledge browser |

Run `jurati --help` for the full list.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `JURATI_KNOWLEDGE_REMOTE` | - | Git remote for the knowledge repo |
| `JURATI_ACTIVE_REFS_ENABLED` | `false` | Enable instant active context sharing from repo policy |
| `JURATI_ACTIVE_REF_TTL_HOURS` | `72` | Maximum TTL for active context entries |
| `JURATI_SIGNAL_PROVIDER` | `github` | Signal source: `github` or `jira` |
| `JURATI_PR_SIGNAL_REPOS` | - | Repos for GitHub PR signals |
| `JURATI_JIRA_BASE_URL` | - | Jira instance URL |
| `JURATI_JIRA_PROJECTS` | - | Jira project keys |

See [Configuration Reference](docs/clients.md) for all variables.

## Documentation

| Guide | Audience |
|-------|----------|
| [User Guide](docs/guide.md) | Developers using Jurati with Claude Code |
| [Adoption Guide](docs/adoption.md) | Teams evaluating or rolling out Jurati |
| [MCP Client Setup](docs/clients.md) | Client configuration and troubleshooting |
| [Context, Not Memory](docs/context-not-memory.md) | Architecture and design boundary |
| [Trust Gate](docs/security-privacy-content-safety.md) | Security, privacy, and content-safety release gate |
| [Overview Slides](docs/jurati-slides.html) | Product and technical overview (HTML) |
| [Detailed Slides](docs/jurati-slides-detailed.html) | Architecture deep-dive with diagrams (HTML) |
| [Contributing](CONTRIBUTING.md) | Development setup, testing, code style |
| [Release Checklist](docs/release.md) | Publishing and release process |

## Development

```bash
git clone https://github.com/ostinato-forge/jurati.git
cd jurati
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q && ruff check . && mypy src
```

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Disclaimer

This is a personal project. It does not represent the views, policies, or
endorsement of my employer.
