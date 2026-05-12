# MCP Client Setup

Jurati exposes one MCP server per knowledge repo. Server names use a hash of
the remote URL (`jurati-{hash}`) so multiple knowledge repos don't collide in
global config.

The fastest setup:

```bash
jurati quickstart ./jurati-knowledge \
  --remote git@github.com:your-org/jurati-knowledge.git
jurati mcp-config --remote git@github.com:your-org/jurati-knowledge.git
```

Use the generated JSON in your client. The important values are:

- `command`: the installed `jurati` executable
- `args`: `["serve"]`
- `JURATI_KNOWLEDGE_REMOTE`: the git remote for the knowledge repo
- `JURATI_CLIENT_SLUG`: the stable client name used in active ref paths

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
handoff for the next agent" or "Record this as a team decision." The agent
should choose `record()` or `propose()` on its own and confirm the result in
one sentence without asking the user to pick the API.

## Troubleshooting

Run these commands from the same shell environment the client uses:

```bash
jurati doctor
jurati doctor --check-startup
export JURATI_KNOWLEDGE_REMOTE=git@github.com:your-org/jurati-knowledge.git
jurati serve --check
```

`doctor` checks local prerequisites and configuration. It discovers the
knowledge remote from `JURATI_KNOWLEDGE_REMOTE`, `CLAUDE.md`, `.jurati-remote`,
or `.claude/settings.json` (scanning all `mcpServers` entries). `serve --check`
shows which repo, cache, branch, and client slug the MCP server will use
without starting the MCP protocol, but it still expects
`JURATI_KNOWLEDGE_REMOTE` in the process environment just like the live MCP
server does.

`doctor --check-startup` goes one step further: it fetches the configured
knowledge repo, rebuilds the local index, and confirms that the startup read
path behind `sync()` and `context()` is usable.

If `doctor` reports missing `mcp__jurati-{hash}__*` permissions, rerun
`jurati install-claude-md --repo-path . --remote <url>`. Older settings that
only include `mcp__jurati__*` work for stable server names but still prompt when
Claude Code loads a hash-named project MCP server.

### Duplicate server definitions

`jurati doctor` scans supported Claude Code config locations, including project
`.mcp.json`, project `.claude/mcp.json`, user `~/.claude/mcp.json`, and
`~/.claude.json`. If the same server name appears in more than one place, keep
one definition and remove the other.

For Claude Code, a common cleanup is:

```bash
claude mcp remove jurati -s user
jurati mcp-config --remote git@github.com:your-org/jurati-knowledge.git --write-project
jurati doctor
```

Do not fall back to raw MCP protocol messages. Fix the config, restart the
client, and confirm the tools are available through `status()` or `context()`.
