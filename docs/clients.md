# MCP Client Setup

Jurati exposes one MCP server per knowledge repo. Server names use a hash of
the remote URL (`jurati-{hash}`) so multiple knowledge repos don't collide in
global config.

The fastest setup:

```bash
jurati onboard
```

For scripted setup:

```bash
jurati onboard \
  --remote git@github.com:your-org/jurati-knowledge.git \
  --knowledge-repo ./jurati-knowledge \
  --project-repo . \
  --yes
```

Jurati writes project-local `.mcp.json`. The important values are:

- `command`: the installed `jurati` executable
- `args`: `["serve"]`
- `JURATI_KNOWLEDGE_REMOTE`: the git remote for the knowledge repo
- `JURATI_CLIENT_SLUG`: the stable client name used in active ref paths

If the shell running `jurati mcp-config` has non-secret PR-signal settings,
Jurati also carries them into the generated server env:

- `JURATI_PR_SIGNAL_REPOS`: comma-separated repos to read for labeled PR
  coordination signals
- `JURATI_PR_SIGNAL_FIXTURE`: local JSON fixture for repeatable tests or
  offline coordination gates

## Claude Code

Add the generated server block to `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "jurati-a1b2c3d4": {
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

The hash suffix (`a1b2c3d4`) is derived from your remote URL. Use `jurati
mcp-config` to generate the correct name — don't construct it manually.

Then restart Claude Code so it reloads MCP configuration.

For project-local config, let Jurati update `.mcp.json` with the same hash-based
server name:

```bash
jurati mcp-config --remote git@github.com:your-org/jurati-knowledge.git --write-project
```

Use one active definition per server name. If you previously installed a global
server named `jurati`, remove it or regenerate the project config with the
hash-based name above before reconnecting the client.

### Disposable connected-agent checks

When running a disposable Claude Code pilot, keep Claude Code's normal `HOME`.
Claude's auth and provider configuration may live there, especially in
enterprise or Vertex-backed environments. Isolate Jurati through the project
MCP config and server env instead:

```bash
jurati mcp-config \
  --remote file:///tmp/jurati-pilot/jurati-knowledge.git \
  --command /tmp/jurati-pipx/bin/jurati \
  --write-project

claude -p \
  --mcp-config .mcp.json \
  --strict-mcp-config \
  --setting-sources project \
  "Give me your initial plan after checking project instructions and context."
```

Do not set `HOME=/tmp/...` for Claude Code just to isolate a Jurati trial. Use
`JURATI_CACHE_DIR`, `JURATI_KNOWLEDGE_REMOTE`, and an absolute `jurati` command
path inside `.mcp.json` instead.

### Auto-approve tools

Run `jurati install-claude-md` in your project repo to create
`.claude/settings.json` with the Jurati permission allowlist, including the
read-only startup tools `sync()`, `context()`, `query()`, and `search()`.
When you pass `--remote`, the generated settings include both the stable
`mcp__jurati__*` tool names and the hash-specific names for your generated MCP
server, such as `mcp__jurati-a1b2c3d4__sync`. See
[claude-md-template.md](claude-md-template.md) for the manual setup.

## Other MCP Clients

Any client that speaks MCP (Copilot, Cursor, custom tooling) works the same
way. Adjust the config format to match your client's MCP setup. The server
name, command, args, and env vars are the same.

## Verification

Ask the client to call these tools before doing real work:

```text
explain()
status()
query(topic="onboarding")
```

The user should see:

- what Jurati reads and writes
- the configured knowledge remote
- the local cache path
- the active ref prefix and client slug
- entry counts and sync health

Jurati should not claim to track reads, log query text, infer presence, or
report participation.

When testing writes, the user should be able to speak normally: "Save this
handoff for the next agent" or "Record this as a project decision." The agent
should choose `record()` or `propose()` on its own and confirm the result in
one sentence without asking the user to pick the API.

## Troubleshooting

Run these commands from the same shell environment the client uses:

```bash
jurati doctor
jurati doctor --team
jurati doctor --check-startup
export JURATI_KNOWLEDGE_REMOTE=git@github.com:your-org/jurati-knowledge.git
jurati serve --check
```

`doctor` checks local prerequisites and configuration. It discovers the
knowledge remote from `JURATI_KNOWLEDGE_REMOTE`, repo-owned
`.jurati/config.yaml`, `CLAUDE.md`, `.jurati-remote`, or MCP config files
(scanning all `mcpServers` entries). `doctor --team` adds a repo-level
readiness view: participation marker, project MCP config, startup contract,
read-only tool permissions, write-path availability, and active-ref policy. It
does not report teammate installation, presence, reads, or participation.
`serve --check` shows which repo, cache, branch, and client slug the MCP server
will use without starting the MCP protocol, but it still expects
`JURATI_KNOWLEDGE_REMOTE` in the process environment just like the live MCP
server does.

`doctor --check-startup` goes one step further: it fetches the configured
knowledge repo, rebuilds the local index, and confirms that the startup read
path behind `sync()`, `context()`, and direct entry reads is usable.

If `doctor` reports missing project setup, repair the safe project-local files
and rerun the startup check:

```bash
jurati doctor --fix-project-config --team
jurati doctor --team --check-startup
```

If the startup probe fails because the cache directory is not writable, set
`JURATI_CACHE_DIR` to a writable location and rerun the check:

```bash
JURATI_CACHE_DIR=/tmp/jurati-cache jurati doctor --check-startup
```

For fixture-backed coordination tests, set `JURATI_PR_SIGNAL_REPOS` and
`JURATI_PR_SIGNAL_FIXTURE` before running `jurati mcp-config --write-project`.
The generated `.mcp.json` will pass those non-secret values to `jurati serve`
when the MCP client starts.

If `doctor` reports missing `mcp__jurati-{hash}__*` permissions, rerun
`jurati doctor --fix-project-config` or
`jurati install-claude-md --repo-path . --remote <url>`. Older settings that only
include `mcp__jurati__*` work for stable server names but still prompt when
Claude Code loads a hash-named project MCP server.

### Repo Readiness In CI

For participating project repos, `doctor --team --strict` can be used as a
normal GitHub status check. It only inspects repo-local Jurati setup and local
tool availability; it does not call the knowledge repo, report teammate
installation status, or record participation.

```yaml
name: jurati-readiness

on:
  pull_request:
  push:
    branches: [main]

jobs:
  readiness:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install jurati
      - run: jurati doctor --team --strict
```

If the knowledge repo is public or the workflow has explicit read credentials,
add `--check-startup` as a separate step. Keep private knowledge credentials in
repository or organization secrets, not in `.jurati/config.yaml`.

### Fresh teammate clones

For a project that already committed `.jurati/config.yaml`, `CLAUDE.md`,
`.claude/settings.json`, and `.mcp.json`, a teammate should not need personal
MCP setup instructions to verify the connection. From a normal fresh clone, run:

```bash
jurati doctor --team --check-startup --strict
```

The command discovers the repo-owned knowledge remote, checks the project MCP
config and startup contract, fetches/indexes the knowledge repo, and reports
repo readiness only. It must not report teammate installation status, presence,
reads, or participation.

### Duplicate server definitions

`jurati doctor` scans supported Claude Code config locations, including project
`.mcp.json`, project `.claude/mcp.json`, user `~/.claude/mcp.json`, and
`~/.claude.json`. If the same Jurati server name appears in more than one place,
keep one definition and remove the other. Duplicate non-Jurati server names are
reported for visibility but do not block Jurati startup.

For Claude Code, a common cleanup is:

```bash
claude mcp remove jurati -s user
jurati mcp-config --remote git@github.com:your-org/jurati-knowledge.git --write-project
jurati doctor
```

Do not fall back to raw MCP protocol messages. Fix the config, restart the
client, and confirm the tools are available through `status()` or `context()`.
