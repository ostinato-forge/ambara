# Jurati

Shared team memory for people and AI coding agents.

Jurati gives every agent the same context a good teammate would have: current
project state, durable decisions, workflow preferences, and engineering
principles. The knowledge lives in a normal git repo as markdown. Jurati serves
it to MCP clients and writes back only when explicitly asked.

## What It Does

- Searches shared knowledge before work starts.
- Reads full entries when an agent needs context.
- Records short-lived active work and handoff notes.
- Proposes durable project updates, workflows, decisions, and principles through
  git branches and pull requests.
- Shows exactly which repo, cache path, client slug, and write path it uses.

## What It Does Not Do

- No query logging.
- No read receipts.
- No participation tracking.
- No inferred presence from editors, terminals, or agent activity.
- No direct push to protected `main` for normal durable writes.

## Five-Minute Adoption

### 1. Install

```bash
pipx install git+ssh://git@github.com/RedHatTraining/jurati.git
```

For one-off use without a persistent install:

```bash
uvx --from git+ssh://git@github.com/RedHatTraining/jurati.git jurati --help
```

For local development:

```bash
git clone https://github.com/RedHatTraining/jurati.git
cd jurati
python3.13 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Create A Knowledge Repo

Jurati software and Jurati knowledge are separate repos. The knowledge repo is
the shared source of truth for the team.

```bash
jurati quickstart ./jurati-knowledge --remote git@github.com:your-org/jurati-knowledge.git
cd jurati-knowledge
git init
git add .
git commit -m "docs: initialize jurati knowledge repo"
git remote add origin git@github.com:your-org/jurati-knowledge.git
git push -u origin main
```

`jurati quickstart` creates the scaffold, writes valid starter entries, validates
the repo, explains the read/write/privacy boundaries, and prints the MCP config
when you pass `--remote`.

Optional starter packs add department-shaped examples without changing the core
knowledge model:

```bash
jurati quickstart ./jurati-knowledge --pack training --remote git@github.com:your-org/jurati-knowledge.git
jurati quickstart ./jurati-knowledge --pack engineering --remote git@github.com:your-org/jurati-knowledge.git
```

### 3. Check Your Setup

```bash
export JURATI_KNOWLEDGE_REMOTE=git@github.com:your-org/jurati-knowledge.git
jurati doctor
jurati serve --check
```

`doctor` explains whether this machine is ready. `serve --check` explains what
the MCP server will do without starting the protocol. If you prefer the smaller
building blocks, `jurati init`, `jurati validate`, and `jurati mcp-config` remain
available.

For a fuller rollout checklist, see [docs/adoption.md](docs/adoption.md).

### 4. Add It To An MCP Client

```bash
jurati mcp-config --remote git@github.com:your-org/jurati-knowledge.git
```

Paste the JSON from `quickstart` or `mcp-config` into your MCP client config, for
example `~/.claude/mcp.json` for Claude Code:

```json
{
  "mcpServers": {
    "jurati": {
      "command": "jurati",
      "args": ["serve"],
      "env": {
        "JURATI_KNOWLEDGE_REMOTE": "git@github.com:your-org/jurati-knowledge.git",
        "JURATI_CLIENT_SLUG": "claude-code"
      }
    }
  }
}
```

For client-specific setup and verification, see [docs/clients.md](docs/clients.md).

### 5. Use It During Normal Work

Before work:

```text
query(topic="release workflow")
query(topic="grading infrastructure", type="decision")
```

During work:

```text
record(
  type="active",
  title="Investigating flaky lab validation",
  content="E2E fails after the inventory refresh step. Checking generated vars.",
  tags=["active", "validation"]
)
```

After work:

```text
propose(
  type="decision",
  title="Use one validation command before review",
  content="Course and engineering repos should expose one documented validation command..."
)
```

## Daily Workflow

Jurati is meant to be boring in the best way. It sits beside normal work and
answers three questions.

| Moment | User Question | Jurati Action | What The User Sees |
|--------|---------------|---------------|--------------------|
| Start work | What should I know first? | `query`, `read`, `list_entries` | Prior decisions, current project state, known workflow rules |
| During work | What should my teammates or future agents know? | `record(type="active")` | Short-lived active context on a non-main active ref |
| Before review | Is there a team workflow for this? | `query(type="workflow")` | The review, test, release, or handoff process |
| After a decision | Should this become durable? | `propose(type="decision")` | Branch and PR, never silent source-of-truth mutation |
| Cleanup | Is old context still visible? | `expire(id=...)` | Active ref deletion or expiry PR, depending on entry type |

This fits training work and engineering work equally well. A course developer
may use it for lesson status, lab validation decisions, and review workflows. An
engineer may use it for architecture decisions, incident context, service
standards, and release practices.

## Knowledge Model

Every entry is a markdown file with YAML frontmatter stored in git.

| Type | Level | Write Tool | Captures |
|------|-------|------------|----------|
| `active` | L0 | `record` | Current work, investigations, handoff notes |
| `project` | L1 | `record` | Ongoing initiatives, goals, status updates |
| `workflow` | L2 | `propose` | Team processes and recurring work |
| `decision` | L2/L3 | `propose` | Design choices with rationale |
| `principle` | L3 | `propose` | Long-lived engineering principles |

Escalation levels control the write path:

- L0: active ref, no PR, expires from normal results.
- L1: lightweight PR.
- L2: reviewed PR.
- L3: reviewed PR for foundational entries.

## Tool Surface

Reading:

- `explain()`
- `status()`
- `query(topic, type?, project?, status?, include_expired?)`
- `read(id, include_expired?)`
- `list_entries(type?, project?, status?, include_expired?)`

Writing:

- `record(type, title, content, ...)`
- `propose(type, title, content, ...)`
- `expire(id, reason?)`

Maintenance:

- `sync()`
- `validate(id?)`
- `hygiene(stale_after_days?)`

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JURATI_KNOWLEDGE_REMOTE` | Yes | - | Git remote URL for the knowledge repo |
| `JURATI_CLIENT_SLUG` | No | `claude-code` | Client name used in L0 active ref paths |
| `JURATI_CACHE_DIR` | No | `~/.cache/jurati` | Local clone location |
| `JURATI_MAIN_BRANCH` | No | `main` | Branch containing durable entries |
| `JURATI_BRANCH_PREFIX` | No | `jurati` | Prefix for branches created by writes |
| `JURATI_ACTIVE_REF_PREFIX` | No | `jurati/active` | Git ref namespace for active entries |
| `JURATI_SYNC_INTERVAL` | No | `300` | Seconds between automatic syncs |

## Development

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

For release and package-smoke steps, see [docs/release.md](docs/release.md).

## License

MIT
