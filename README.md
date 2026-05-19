# Jurati

Reviewable team context for AI agents, backed by git.

Jurati helps AI coding agents start with the team's decisions, workflows,
project state, handoffs, and coordination signals before they touch a repo. The
source of truth is a normal git repository of Markdown files with YAML
frontmatter, so people can review changes in pull requests while agents get a
structured MCP interface for context retrieval and writeback.

The goal is not to give every agent a private notebook. The goal is to make the
team's shared context visible, reviewable, and useful at the moment an agent is
about to act.

## What Changes

Without Jurati, an agent usually sees the current prompt and the local checkout.
With Jurati installed, the agent is instructed to:

1. call `sync()` silently so its local index is fresh
2. call `context(repo=..., goal=...)` before local repo exploration
3. use `query()` or `search()` when a specific decision or workflow matters
4. write back only when someone explicitly asks to share context

That means an agent can learn that the team chose gRPC last week, that someone
has an open PR touching the module it is about to edit, or that a release
workflow requires a specific validation command before review. The person using
the agent should not have to hunt through chat history or remember which doc
contains the rule.

## The Model

Jurati has four main surfaces:

| Surface | Job |
|---------|-----|
| Knowledge repo | Git repository containing reviewed Markdown context |
| Runtime index | Derived local indexes built from the knowledge repo |
| MCP server | Agent-facing tools such as `context()`, `query()`, and `record()` |
| Git review | Branches and pull requests for durable writeback |

Project repos do not become knowledge repos. A project repo gets instructions
and MCP config that tell the agent where the shared knowledge repo lives. The
knowledge repo remains the reviewed context source for one team, project family,
or organization.

Jurati is MCP-based. The protocol surface is client-neutral, and the most
complete setup path today is documented for Claude Code in
[MCP Client Setup](docs/clients.md).

## Knowledge Entries

Knowledge entries are Markdown files with validated YAML frontmatter.

| Type | What it captures |
|------|------------------|
| `principle` | Long-lived standards that should shape future work |
| `decision` | Design or process choices with rationale |
| `workflow` | Recurring team process, review gates, and release steps |
| `project` | Current project state, blockers, goals, and useful context |
| `active` | Short-lived handoffs and current-focus notes |

Durable context goes through normal git review. Short-lived active context is
opt-in and expires. Restricted entries are excluded from broad context, search,
and ranking results.

For the architectural boundary, see [Context, Not Memory](docs/context-not-memory.md).
For adoption guidance, see [Jurati Adoption Guide](docs/adoption.md).

## Quick Start

Jurati requires Python 3.13 or newer.

Install the CLI:

```bash
pipx install git+https://github.com/ostinato-forge/jurati.git
jurati --version
```

Then run the guided onboarding from the project repo that should use Jurati:

```bash
cd /path/to/project
jurati onboard
```

`jurati onboard` prompts for the knowledge repo remote URL, local knowledge repo
path, project repo path, and starter pack. It creates the knowledge repo
scaffold, installs the Jurati section in `CLAUDE.md`, updates
`.claude/settings.json`, and writes project-local MCP config.

For scripted setup, pass the values directly:

```bash
jurati onboard \
  --remote git@github.com:your-org/jurati-knowledge.git \
  --knowledge-repo ./jurati-knowledge \
  --project-repo . \
  --pack engineering \
  --yes
```

If this is a new knowledge repo, push it once:

```bash
cd ./jurati-knowledge
git init -b main
git add .
git commit -m "docs: initialize jurati knowledge repo"
git remote add origin git@github.com:your-org/jurati-knowledge.git
git push -u origin main
```

Verify the connected read path after the knowledge repo has been pushed:

```bash
jurati doctor --check-startup
```

Review the generated project instructions and settings, then commit the files
your team wants shared with the repo.

For one-off use without a persistent install:

```bash
uvx --from git+https://github.com/ostinato-forge/jurati.git \
  jurati onboard --remote git@github.com:your-org/jurati-knowledge.git
```

`doctor --check-startup` fetches and indexes the configured knowledge repo, then
checks the read path behind `sync()` and `context()`.

After restarting your MCP client, ask the agent to explain its Jurati setup with
`explain()` and `status()`. For a real first task, the agent's first Jurati calls
should be `sync()` followed by `context(repo=..., goal=...)`.

## Daily Workflow

Start work normally:

```text
"Update the login flow to use the new token endpoint."
```

The agent should refresh Jurati, ask for context about the repo and goal, and
summarize only the relevant team context before it edits files.

Share a handoff in normal language:

```text
"Save this handoff for the next agent."
```

The agent should translate that into an active `record(...)` call. The person
using the agent should not need to choose the API.

Capture a durable decision the same way:

```text
"Record this as a team decision: use server-driven token rotation."
```

The agent should translate that into a reviewed `propose(...)` call and confirm
the outcome in one work-focused sentence.

## Ambient Capture

Jurati can also capture explicit context from commit messages. Install the hook
in a source repo:

```bash
jurati install-hook --with-pre-push
```

Use `jurati:` lines for shareable context:

```text
jurati: auth migration is in flight for the web app
jurati(decision): use gRPC between internal services
jurati(workflow): run one validation command before review
jurati(principle): restricted data stays out of context entries
```

A bare `jurati:` line becomes a project update. Tagged lines request more
durable entry types. Capture runs through validation and secret scanning before
it writes to the knowledge workflow.

## Coordination Signals

Jurati can read labeled PRs from configured repos and surface coordination
effects through `context()`: continue, reuse, revise, pause, handoff, or clarify.
The agent receives enough evidence to plan safely, including PR state, title,
author, updated time, matched paths, merge time when available, and an optional
short excerpt.

GitHub PR signals ship today. The provider interface is meant to support other
systems such as Jira, Linear, or internal review tools.

## Privacy Boundary

Jurati is a broadcast system, not an observation system.

It does not:

- log query text
- create read receipts
- infer presence from editor, terminal, or agent activity
- measure participation
- bypass git provenance or review

Writes happen only when an agent explicitly calls `record()`, `propose()`, or
`expire()`. Active context is disabled by default because it is the highest-risk
sharing mode. Restricted entries stay out of context responses, search results,
and the BM25 index; they require an explicit `read(id=...)` call.

## What Jurati Is Not

Jurati is not a personal second brain, CRM, vector database, graph database,
chat-transcript archive, or telemetry layer. Markdown is the human-reviewable
source format, not the query engine. Retrieval is handled by validation,
indexes, privacy filters, and explicit MCP contracts.

Teams migrating from curated Markdown or Obsidian-backed workflows should start
with [Context Pack Migration](docs/context-pack-migration.md).

## Useful Commands

| Command | Use |
|---------|-----|
| `jurati explain` | Print the plain-language product boundary |
| `jurati onboard` | Guided first-time setup for a knowledge repo and project repo |
| `jurati quickstart` | Create a starter knowledge repo |
| `jurati install-claude-md` | Add project instructions and Claude Code settings |
| `jurati mcp-config` | Generate or write MCP server config |
| `jurati doctor` | Check local configuration |
| `jurati serve --check` | Check the MCP runtime environment without starting stdio |
| `jurati validate` | Validate knowledge entries |
| `jurati import-context` | Import a context-pack tarball through a review branch |
| `jurati html` | Generate a static browser for a local knowledge repo |
| `jurati read-model` | Build and query a derived local SQLite read model |
| `jurati install-hook` | Install ambient commit capture hooks |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `JURATI_KNOWLEDGE_REMOTE` | - | Git remote URL for the knowledge repo |
| `JURATI_CLIENT_SLUG` | `claude-code` | Stable client name for active refs |
| `JURATI_CACHE_DIR` | `~/.cache/jurati` | Local clone and index location |
| `JURATI_MAIN_BRANCH` | `main` | Source-of-truth branch |
| `JURATI_SYNC_INTERVAL` | `300` | Seconds between background syncs |
| `JURATI_ACTIVE_REFS_ENABLED` | `false` | Enable opt-in active context |
| `JURATI_PR_SIGNAL_REPOS` | - | Comma-separated repos for PR coordination signals |
| `JURATI_PR_SIGNAL_FIXTURE` | - | Local fixture for repeatable PR-signal tests |
| `JURATI_REVISE_KEYWORDS` | - | Override keywords for revise signals |
| `JURATI_HANDOFF_KEYWORDS` | - | Override keywords for handoff signals |

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, testing, and pull request
guidelines.

Common local checks:

```bash
python -m pytest -q
python -m ruff check .
python -m mypy src
```

For release and client validation, see [Release Checklist](docs/release.md) and
[MCP Client Setup](docs/clients.md).

For the broader product argument, see
[The Replacement Story Is Too Small](docs/blog-the-replacement-story-is-too-small.md).

## License

Apache 2.0 - see [LICENSE](LICENSE).

## Disclaimer

This is a personal project. It does not represent the views, policies, or
endorsement of my employer. All opinions expressed in this project and its
documentation are my own.
