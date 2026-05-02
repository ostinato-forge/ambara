# Jurati

Shared team intelligence layer for agentic workflows.

Jurati gives AI coding agents (and humans) a shared memory — architectural principles, workflow preferences, decision history, and cross-project state — backed by a plain git repository and served via MCP.

## Quick Start

```bash
pip install jurati
jurati serve
```

Configure your MCP client:

```json
{
  "mcpServers": {
    "jurati": {
      "command": "jurati",
      "args": ["serve"],
      "env": {
        "JURATI_REMOTE": "git@github.com:your-org/jurati-knowledge.git"
      }
    }
  }
}
```

## How It Works

Knowledge lives in a git repo as markdown files with YAML frontmatter. The MCP server provides seven tools for agents to query and contribute:

| Tool | Purpose |
|------|---------|
| `query` | Search the knowledge index |
| `read` | Get full entry content |
| `propose` | Create entry via branch + PR (principles, decisions, workflows) |
| `record` | Create entry via direct commit (project state, active work) |
| `list` | Filtered listing of entries |
| `sync` | Pull latest + reindex |
| `forget` | Remove expired entries |

## Privacy

Jurati is a broadcast system, not an observation system. No telemetry, no participation tracking, no query logging, no absence signals. Sharing is always explicit and intentional.

## Development

```bash
git clone https://github.com/RedHatTraining/jurati.git
cd jurati
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

MIT
