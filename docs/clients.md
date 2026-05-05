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

### Auto-approve tools

Run `jurati install-claude-md` in your project repo to create
`.claude/settings.json` with the 13-tool permission allowlist, or see
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

## Troubleshooting

Run these commands from the same shell environment the client uses:

```bash
jurati doctor
jurati serve --check
```

`doctor` checks local prerequisites and configuration. It discovers the
knowledge remote from `JURATI_KNOWLEDGE_REMOTE`, `CLAUDE.md`, `.jurati-remote`,
or `.claude/settings.json` (scanning all `mcpServers` entries). `serve --check`
shows which repo, cache, branch, and client slug the MCP server will use
without starting the MCP protocol.
