# MCP Client Setup

Jurati exposes one MCP server named `jurati`. The safest setup path is:

```bash
jurati quickstart ./jurati-knowledge --remote git@github.com:your-org/jurati-knowledge.git
jurati mcp-config --remote git@github.com:your-org/jurati-knowledge.git
```

Use the generated JSON in the client. The important values are:

- `command`: the installed `jurati` executable
- `args`: `["serve"]`
- `JURATI_KNOWLEDGE_REMOTE`: the git remote for the knowledge repo
- `JURATI_CLIENT_SLUG`: the stable client name used in active ref paths

## Claude Code

Add the generated server block to `~/.claude/mcp.json`:

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

Then restart Claude Code so it reloads MCP configuration.

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

Jurati should not claim to track reads, log query text, infer presence, or report
participation.

## Troubleshooting

Run these commands from the same shell environment the client uses:

```bash
jurati doctor
jurati serve --check
```

`doctor` checks local prerequisites and configuration. `serve --check` shows
which repo, cache, branch, and client slug the MCP server will use without
starting the MCP protocol.
