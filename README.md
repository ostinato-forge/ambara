# Ambara

> **Status:** Beta. The CLI, the MCP server, the demo, and the local proof script run from a fresh clone. Earlier PyPI releases were withdrawn, so install from this repository for now. Maintained.

[![Development Status: 4 - Beta](https://img.shields.io/badge/Development%20Status-4%20--%20Beta-yellow)](https://pypi.org/classifiers/)

AI coding agents forget everything between sessions. Ambara fixes that.

## Start Here

Want to see the product before wiring it into a real project?

```bash
pip install ambara
ambara demo
cd ambara-demo
./run-proof.sh
```

That local proof gives you a knowledge repo, a wired project repo, a fixture
signal source, a static HTML view, and a runnable script that proves startup,
reads, writes, review branches, capture, and value receipts without needing a
network connection.

When you are ready to connect a real project:

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
→ Saved as a decision. Goes through the reviewed path.

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
local aggregate value ledger is on by default, so `ambara value` can show the
token savings that Ambara captured ambiently while you worked.

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
| Growing orgs | Reviewable agent guidance through review branches and requests, scoped by project, with lifecycle controls. |

## Why Not Built-In Agent Memory?

Built-in agent memory is useful for personal preferences and tool behavior.
Ambara is for project facts that need provenance: decisions, workflows,
handoffs, constraints, and status that should survive tool changes and team
changes.

Ambara keeps those facts in git, makes durable updates reviewable, and requires
explicit writes. It is not a replacement for a model or client's private memory;
it is the shared project context layer beside it.

## How You Verify It

Ambara is strongest when the human can inspect what happened directly.

- `ambara demo` gives you a no-network proof path before real setup
- `ambara startup` can write a plain context file that any agent can read
- `ambara html` renders a static context browser for direct human inspection
- the knowledge repo stays as normal Markdown in git, so review and history stay
  visible outside any one agent client

If Ambara only creates a review branch and does not open a review request, it
now says that explicitly. It does not claim an opened review request when only
a branch or compare link exists.

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
ambara onboard --remote <git-remote-url>
```

Team members connect with the same command using the same remote URL.

Example remotes:

- GitHub: `git@github.com:your-org/team-context.git`
- GitLab: `git@gitlab.com:your-group/team-context.git`

### Verify

```bash
ambara doctor --check-startup
```

For troubleshooting, see [Install And Troubleshooting](docs/install-troubleshooting.md).

### Try The Local Demo

```bash
ambara demo
cd ambara-demo
./run-proof.sh
```

Creates a no-network demo under `./ambara-demo` with a local knowledge repo,
a wired project repo, a runnable proof script, a value ledger path, a fixture
project signal, and a static HTML inspection path.

The proof script validates the knowledge repo, checks startup, compiles compact
context, proves restricted entries stay out of startup and static HTML, reads a
selected source body, records active context, proposes durable context on a
review branch, imports docs through a review branch, queues and flushes ambient
capture, checks local posture, and prints value accounting.

### CI Capture

Ambara also supports commit-driven capture in CI. The shared capture entrypoint
bootstraps the local knowledge repo from the declared remote, applies
forge-aware authenticated remotes when a token is provided, fetches the main
branch, and then evaluates commit capture with the same content-policy gate used
by interactive writes.

For GitHub, use the bundled composite action.

For GitLab CI, install Ambara in the job and run the same entrypoint directly:

```yaml
ambara_capture:
  image: python:3.12
  variables:
    AMBARA_KNOWLEDGE_REMOTE: https://gitlab.com/your-org/team-context.git
    AMBARA_KNOWLEDGE_TOKEN: $AMBARA_KNOWLEDGE_TOKEN
    AMBARA_MAIN_BRANCH: main
  script:
    - pip install ambara
    - python -m ambara.action.capture
```

This is for explicit `ambara:` commit messages and related workflow capture. It
is not a generic background collector.

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

Decisions and workflows go through reviewed durable write paths. Handoffs are
short-lived and expire automatically.

## Privacy

Ambara does not log what agents read, track who's online, or create activity
feeds. Durable shared context only stores what you explicitly ask it to save.
There is no collector for query text, read patterns, editor activity, or
participation data. The system can't track what it was never built to capture.

Value receipts and the automatic local value ledger keep the same boundary:
they record aggregate token estimates and omission/suppression counts only.
They do not store query text, response text, body snippets, caller identity, or
durable per-entry read receipts. Reported savings are Ambara app-payload
estimates with conservative low/high ranges, not total client/session/cache
billing or measured tokenizer truth. Currency estimates are only shown when a
deployment supplies its own token price; Ambara never invents a universal dollar
value.

Security, privacy, and secret scanning are release gates for this product,
not optional hardening. See [Security Policy](SECURITY.md).

## What Ambara Does Not Claim

Ambara is not a secrets manager, observability product, agent runtime, or total
LLM cost meter. It reports Ambara app-payload estimates with conservative ranges
only. It does not prove who read what, infer presence, bypass git review, or
replace human review for durable project knowledge.

Claude Code setup and the plain file adapter are first-class for this release.
`ambara client-smoke` verifies the file-adapter path for Claude Code, Codex,
Cursor, and Gemini against a local/no-network knowledge repo. Other MCP clients
should work through the protocol, but client-specific support is only claimed
after that client has been smoked.

---

## Reference

Everything below here is reference material. You don't need it to get started.

### How It Works

```
              ┌──────────────────┐
              │  Context Repo    │  Reviewed Markdown + YAML frontmatter
              │  (normal git)    │  in git — reviews, history, provenance
              └────────┬─────────┘
                       │
              ┌────────▼─────────┐
              │  Ambara Server   │  Indexes, ranks, filters,
              │                  │  applies privacy filters + secret scanning
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
| `context()` | Relevant decisions, project state, and project source inputs |
| `sync()` | Refresh local index from the context repo |
| `read()` / `read_many()` | Full text for entries the agent directly relies on |
| `query()` | Deep-dive on a specific topic |
| `search()` | Keyword search across all entries |
| `record()` | Save a handoff, project update, or active note |
| `propose()` | Save a decision or workflow for team review via a review branch/request |
| `promote(artifact_id)` | Promote a labeled source artifact (PR/issue/page) into durable reviewed knowledge; dry-run by default |
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

### Client Support

Ambara has first-class generated setup for Claude Code and a plain file adapter
for agents that cannot use MCP. Run `ambara client-smoke --client <name>` to
verify the file-adapter path for `claude-code`, `codex`, `cursor`, or `gemini`
against a local knowledge repo. Other MCP clients can connect to `ambara serve`
with the generated config, but client-specific docs should be treated as
protocol-compatible until smoked.

### Support Matrix

| Surface | Current truth |
|---------|---------------|
| Review backends | GitHub pull requests and GitLab merge requests are first-class. |
| Other git hosts | Compatible through branch-only fallback until a forge-specific review adapter exists. |
| CI capture | GitHub Actions and GitLab CI are first-class. Other CI runners can call `python -m ambara.action.capture` directly. |
| Agent setup | Claude Code generated setup is first-class. The file adapter is smoked for Claude Code, Codex, Cursor, and Gemini via `ambara client-smoke`. |
| Sources | Source Preview built-ins are GitHub review artifacts, GitLab review artifacts, Jira issues, and fixture/local JSON through the source manager. |

### Entry Types

| Type | What it's for |
|------|---------------|
| `active` | Short-lived handoffs. "Left off at the token endpoint." Expires automatically. |
| `project` | Current project state. "Auth migration is in flight." |
| `decision` | Reviewed team decision. "Use gRPC for internal services." Goes through the reviewed path. |
| `workflow` | Recurring team process. "Run validation before review." Goes through the reviewed path. |
| `principle` | Durable standard. "Restricted data stays out of context entries." |

### Secret Scanning

Write and render paths run policy checks before durable writes or startup
output:

- **Known credential-shaped patterns** are blocked or redacted before they
  reach durable writes or startup rendering
- **Configured PII, confidentiality, and personnel patterns** require review
- **Source text** from review artifacts and issues is normalized through the
  central policy path before surfacing

### Project Source Inputs

Ambara reads labeled GitHub pull requests, GitLab merge requests, and Jira
issues from configured sources and surfaces them as project context: continue,
reuse, revise, pause, handoff, or clarify.
GitHub, GitLab, and Jira are supported.

```bash
AMBARA_SOURCE_REPOS=your-org/repo1,your-org/repo2
AMBARA_SOURCE_PROVIDER=gitlab
AMBARA_GITLAB_BASE_URL=https://gitlab.example.com
```

```bash
AMBARA_SOURCE_REPOS=your-org/repo1,your-org/repo2
AMBARA_SOURCE_PROVIDER=github
```

```bash
AMBARA_SOURCE_PROVIDER=jira
AMBARA_JIRA_BASE_URL=https://jira.example.com
AMBARA_JIRA_PROJECTS=PROJ1,PROJ2
```

### Curation

Context needs maintenance. Ambara generates cleanup review branches that expire
stale handoffs and flag durable entries for revalidation. Agents also get quiet
advisories inside `context()` so they know not to rely on stale entries.

### CLI Reference

**Setup**

| Command | Purpose |
|---------|---------|
| `ambara onboard` | Guided first-time setup (knowledge repo, CLAUDE.md, MCP config) |
| `ambara quickstart` | Create a starter knowledge repo and print next steps |
| `ambara init` | Initialize a knowledge repo scaffold |
| `ambara demo` | Create a local no-network proof project |
| `ambara install-claude-md` | Add or update agent instructions in CLAUDE.md |
| `ambara mcp-config` | Print or write a collision-resistant MCP config block |
| `ambara install-hook` | Install ambient commit capture hooks |
| `ambara client-smoke` | Verify the file-adapter path for a named agent client |
| `ambara doctor` | Check configuration and connectivity (`--check-startup` to verify sync) |
| `ambara sources doctor` | Inspect configured source freshness without leaking contents |
| `ambara sources promote <id>` | Promote a labeled source artifact into durable knowledge (`--apply` opens the review branch) |
| `ambara source-smoke` | Smoke one source through registry, manager, and central safety |
| `ambara posture-check` | Check local agent-safe-start guardrails |

**Daily use**

| Command | Purpose |
|---------|---------|
| `ambara serve` | Start the MCP server over stdio |
| `ambara startup` | Compile compact startup context to a file or stdout |
| `ambara save` | Save a handoff in one command |
| `ambara record` | Record a handoff, status update, or active context |
| `ambara propose` | Propose a decision or workflow for review |
| `ambara active` | Broadcast active status without a commit |
| `ambara show` | List recent entries in the knowledge repo |
| `ambara search` / `ambara query` | Search context from the command line, by keyword or topic |
| `ambara read` | Read a single knowledge entry by ID |

**Import and lifecycle**

| Command | Purpose |
|---------|---------|
| `ambara import-docs` | Import ADRs, RFCs, or selected docs through review |
| `ambara import-context` | Import a packaged context pack |
| `ambara validate` | Validate context entries |
| `ambara clear` | Bulk-clear current context on a review branch |
| `ambara retire-scope` | Retire matching knowledge on a review branch |
| `ambara mute-scope` / `ambara unmute-scope` | Mute or unmute local project/repo/source-input/tag scopes |
| `ambara capture` | Process a commit message through the capture pipeline |
| `ambara flush` | Flush pending captures from the offline queue |

**Inspection and local ops**

| Command | Purpose |
|---------|---------|
| `ambara html` | Generate a static context browser |
| `ambara read-model` | Build or query the local SQLite read model |
| `ambara value` | Show local app-payload savings estimates |
| `ambara feedback` | Record local relevance feedback for an entry |
| `ambara explain` | Print the product boundary |
| `ambara privacy-salt` | Generate an `AMBARA_PRIVACY_SALT` value for opaque scoping |
| `ambara enable` / `ambara disable` | Re-enable or disable Ambara for a project |

Run `ambara --help` for the full list and per-command flags.

### Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `AMBARA_KNOWLEDGE_REMOTE` | - | Git remote for the context repo |
| `AMBARA_ACTIVE_REFS_ENABLED` | setup-dependent | Enable session handoffs |
| `AMBARA_ACTIVE_REF_TTL_HOURS` | `72` | How long handoffs stay active |
| `AMBARA_SOURCE_PROVIDER` | `github` | Source selector: `github`, `gitlab`, or `jira` |
| `AMBARA_SOURCE_REPOS` | - | Repos for GitHub PR or GitLab MR source inputs |
| `AMBARA_SOURCE_FIXTURE` | - | Local JSON fixture source for demos and no-network proof |
| `AMBARA_GITLAB_BASE_URL` | - | Base URL for GitLab.com or self-hosted GitLab |
| `AMBARA_JIRA_BASE_URL` | - | Jira instance URL |
| `AMBARA_JIRA_PROJECTS` | - | Jira project keys |
| `AMBARA_CONTEXT_BUDGET_MODE` | `balanced` | `quiet`, `balanced`, or `deep` context packing |
| `AMBARA_VALUE_LEDGER_PATH` | local cache | Local aggregate JSONL value ledger path |
| `AMBARA_VALUE_LEDGER_ENABLED` | `true` | Set `false` to disable local value capture |
| `AMBARA_INPUT_PRICE_PER_MILLION` | - | Optional managed input-token price for currency estimates |
| `AMBARA_PRICE_CURRENCY` | `USD` | Currency code for managed cost estimates |

### Documentation

| Guide | Audience |
|-------|----------|
| [Install And Troubleshooting](docs/install-troubleshooting.md) | Setup, configuration, and common issues |
| [Release Proof](docs/release-proof.md) | Local release verification |
| [Writing A Source Provider](docs/source-providers.md) | Source-provider contract |
| [v0.8.0 Release Notes](docs/release-v0.8.0.md) | Public-preview source, install, curation, and proof notes |
| [v0.7.0 Release Notes](docs/release-v0.7.0.md) | Cross-agent proof and provider-extension release notes |
| [v0.6.0 Release Notes](docs/release-v0.6.0.md) | Multi-forge foundation and first-class GitLab release notes |
| [v0.5.1 Release Notes](docs/release-v0.5.1.md) | Trust-and-reliability follow-up release notes |
| [v0.5.0 Release Notes](docs/release-v0.5.0.md) | Release notes, launch copy, and post-publish smoke |
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

Contributions are certified with the Developer Certificate of Origin 1.1. Sign
commits with `git commit -s`; see [DCO](DCO) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Disclaimer

This is a personal project. It does not represent the views, policies, or
endorsement of my employer.
