# User Guide

This guide is for developers using Jurati with Claude Code. It covers setup,
daily workflow, and common tasks.

## What Jurati Does

Jurati gives your AI coding agent shared team context. Before the agent reads
files or writes code, it checks what your team has decided, what's in flight,
and what coordination signals matter. The context lives in a normal git
repository of Markdown files that your team reviews through pull requests.

You interact with Jurati through natural language — not API calls. Say "save
this handoff" and the agent handles the rest.

## First-Time Setup

### Prerequisites

- Python 3.12 or newer
- A git remote for the knowledge repo (GitHub, GitLab, or any git host)
- Claude Code (or another MCP client)

### Install Jurati

```bash
pip install jurati
jurati --version
```

Or install from source:

```bash
pipx install git+https://github.com/ostinato-forge/jurati.git
```

For one-off use without installing:

```bash
uvx --from git+https://github.com/ostinato-forge/jurati.git \
  jurati onboard --remote git@github.com:your-org/team-knowledge.git
```

### Run Onboarding

From your project directory:

```bash
cd /path/to/your-project
jurati onboard
```

Jurati prompts for:

1. **Knowledge repo remote** — where team context is stored (e.g.,
   `git@github.com:your-org/team-knowledge.git`)
2. **Local knowledge repo path** — where to clone it locally
3. **Project repo path** — which project connects to this knowledge
4. **Starter pack** — pre-built templates: `engineering`, `training`, or
   `minimal`

Jurati then:

- Creates the knowledge repo scaffold with starter entries
- Adds the startup contract to your project's `CLAUDE.md`
- Writes `.claude/settings.json` with tool permissions
- Writes `.mcp.json` with the MCP server configuration

### Push the Knowledge Repo

If this is a new knowledge repo:

```bash
cd ./team-knowledge
git init -b main
git add .
git commit -m "docs: initialize knowledge repo"
git remote add origin git@github.com:your-org/team-knowledge.git
git push -u origin main
```

### Verify the Setup

```bash
jurati doctor --check-startup
```

This fetches the knowledge repo, rebuilds the index, and confirms that the
read path behind `sync()` and `context()` works.

If `doctor` reports problems:

```bash
jurati doctor --fix-project-config
jurati doctor --check-startup
```

Restart Claude Code, then ask the agent:

```text
"What's your Jurati setup? Run explain() and status()."
```

You should see the configured knowledge remote, cache path, entry counts,
and sync health.

## Multi-Project Setup

If you work across multiple projects that share the same knowledge repo, use
global onboarding:

```bash
jurati onboard --global \
  --remote git@github.com:your-org/team-knowledge.git
```

This writes MCP config to your user-level `~/.claude.json` instead of
project-local `.mcp.json`. Every project you open in Claude Code connects
to the same knowledge repo without per-project configuration.

You still need project-local `CLAUDE.md` and `.claude/settings.json` for
the startup contract and tool permissions:

```bash
cd /path/to/each-project
jurati install-claude-md --remote git@github.com:your-org/team-knowledge.git
```

## Daily Workflow

### Starting a Task

Just describe your task normally:

```text
"Add rate limiting to the /api/users endpoint."
```

The agent automatically:

1. Calls `sync()` to refresh its index
2. Calls `context()` with your repo and goal
3. Summarizes relevant team context (decisions, project state, signals)
4. Proceeds with the task

You don't need to tell the agent to check context — the startup contract in
`CLAUDE.md` handles that.

### Asking About Team Context

```text
"What did we decide about the database migration?"
"What's the team working on right now?"
"Are there any PRs I should know about?"
```

The agent queries the knowledge repo and surfaces relevant entries and
coordination signals.

### Saving a Handoff

When you're done for the day or switching tasks:

```text
"Save this handoff: finished the token endpoint, PR #42 needs review,
 the migration script has a known issue with large tables."
```

The agent writes an active record that expires automatically. The next
person (or agent) to work in this area sees it in their startup context.

### Recording a Decision

When your team makes a decision worth preserving:

```text
"Record this as a team decision: use server-driven token rotation
 instead of client-side refresh. Rationale: reduces attack surface
 and simplifies mobile client code."
```

The agent creates a decision entry through a pull request for team review.

### Updating Project Status

```text
"Update project status: auth migration is 80% complete, blocked on
 the legacy token format in the mobile app."
```

The agent writes a project entry capturing the current state.

## Natural Language Mapping

You don't need to know Jurati's API. Here's how common phrases map:

| What you say | What the agent does |
|-------------|---------------------|
| "Save this handoff" / "Leave this for tomorrow" | `record(type="active", ...)` |
| "Update the project status" / "Note this down" | `record(type="project", ...)` |
| "We decided to..." / "Record this decision" | `propose(type="decision", ...)` |
| "This is how we do X" / "Save this workflow" | `propose(type="workflow", ...)` |
| "What did we decide about X?" | `query(topic="X")` |
| "What's the team working on?" | `context()` |

The agent confirms in one sentence focused on the work:

- "Recorded the token format decision."
- "Saved the handoff for review."
- "Cleared the stale handoff."

## Active Context (Instant Sharing)

By default, shared context goes through pull requests. For instant
sharing — like handoffs between back-to-back coding sessions — enable
active refs as a repo policy:

Set `active_refs_enabled: true` in the project `.jurati/config.yaml`, then run:

```bash
jurati mcp-config --remote <knowledge-remote> --write-project
jurati doctor --team
```

With active refs enabled, `record(type="active", ...)` writes are
immediately visible to other agents on `sync()`, without waiting for
a PR merge. Active entries expire automatically from the repo TTL policy
(default: 72 hours).

## Coordination Signals

Jurati reads labeled PRs and issues to surface coordination effects.

### GitHub PR Signals

Label PRs with `jurati` to make them visible in `context()`:

```bash
JURATI_PR_SIGNAL_REPOS=your-org/repo1,your-org/repo2
```

The agent sees PR state, title, author, matched paths, and merge time.
Effects include: continue, reuse, revise, pause, handoff, clarify.

### Jira Issue Signals

```bash
JURATI_SIGNAL_PROVIDER=jira
JURATI_JIRA_BASE_URL=https://jira.example.com
JURATI_JIRA_PROJECTS=PROJ1,PROJ2
JIRA_API_TOKEN=your-token
```

Label issues with `jurati` to surface them. Both providers emit the same
signal format, so switching between them doesn't change agent behavior.

## Ambient Capture

Jurati can capture context from commit messages. Install the hook:

```bash
jurati install-hook --with-pre-push
```

Then use `jurati:` lines in commits:

```text
feat: add rate limiting

jurati: rate limiting uses sliding window, 100 req/min per user
jurati(decision): chose sliding window over fixed window for burst handling
```

A bare `jurati:` line becomes a project update. Tagged lines create
decisions, workflows, or principles. Content goes through validation and
secret scanning before it reaches the knowledge repo.

## Content Safety

All writes go through content safety rules:

- **Blocked**: API keys, tokens, passwords, private keys — the write is
  rejected and you need to remove the sensitive material
- **Flagged for review**: email addresses, phone numbers, SSNs,
  personnel judgments — the entry is accepted but marked for human review
- **Sanitized**: PR titles, Jira summaries, and other external text are
  cleaned before surfacing in context

If a write is blocked, the agent tells you what was blocked and why. Remove
the sensitive material and try again.

## Troubleshooting

### Agent skips startup context

Check that `CLAUDE.md` has the Jurati startup contract:

```bash
jurati doctor --check-startup
```

If missing, repair it:

```bash
jurati doctor --fix-project-config
```

### Agent can't find the knowledge repo

Verify the remote is configured:

```bash
jurati serve --check
```

This shows the repo, cache, branch, and client slug without starting MCP.

### Duplicate server definitions

If you have both global and project-local MCP config pointing to the same
Jurati server:

```bash
jurati doctor  # shows duplicate warnings
claude mcp remove jurati -s user  # remove the duplicate
jurati doctor  # verify clean
```

### Context seems stale

The agent calls `sync()` at startup, but if the knowledge repo hasn't been
fetched recently:

```text
"Sync and check context again."
```

### Entries not showing up

Entries created with `propose()` go through PR review. They're not visible
until the PR merges (unless you're using active refs for `record()` calls).

Check entry status:

```bash
jurati validate /path/to/knowledge-repo
```

## CLI Quick Reference

```bash
jurati onboard              # Guided first-time setup
jurati onboard --global     # User-level MCP config for multi-project
jurati doctor               # Check configuration
jurati doctor --check-startup  # Verify full read path
jurati doctor --fix-project-config  # Repair project config
jurati validate <path>      # Validate knowledge entries
jurati import-docs --dry-run --mode adr --repo <knowledge-repo> docs/adr
jurati import-context --dry-run --repo <knowledge-repo> context-pack.tar.gz
jurati install-hook         # Install commit capture hooks
jurati explain              # Print product boundary
jurati html <path>          # Static knowledge browser
jurati mcp-config           # Show/write MCP config
jurati serve --check        # Verify MCP environment
jurati read-model           # Build local SQLite index
```
