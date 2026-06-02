# Install And Troubleshooting

This guide covers the public setup path for Jurati. The README explains the
product model; this page is for getting a project connected and diagnosing the
common failure modes.

## Requirements

- Python 3.12 or newer
- Git
- A git remote for the knowledge repo
- An MCP-capable coding agent client, such as Claude Code

## Install

```bash
pip install jurati
```

From source:

```bash
pipx install git+https://github.com/ostinato-forge/jurati.git
```

For one-off setup without installing into the current environment:

```bash
uvx --from git+https://github.com/ostinato-forge/jurati.git \
  jurati onboard --remote git@github.com:your-org/jurati-knowledge.git
```

## Onboard A Project

Run guided onboarding from the project repo:

```bash
cd /path/to/your-project
jurati onboard
```

For scripted setup:

```bash
jurati onboard \
  --remote git@github.com:your-org/jurati-knowledge.git \
  --knowledge-repo ./jurati-knowledge \
  --project-repo . \
  --pack engineering \
  --yes
```

If this is a new knowledge repo, initialize and push it:

```bash
cd ./jurati-knowledge
git init -b main
git add .
git commit -m "docs: initialize knowledge repo"
git remote add origin git@github.com:your-org/jurati-knowledge.git
git push -u origin main
```

## Verify

```bash
jurati doctor --team --check-startup
```

Then restart your MCP client and ask the agent to call `explain()` and
`status()`. You should see the configured knowledge remote, local cache, entry
counts, and sync health.

If project configuration is incomplete:

```bash
jurati doctor --fix-project-config --team
jurati doctor --team --check-startup
```

## Daily Use

You can use natural language with the coding agent:

```text
"Save this handoff for tomorrow."
"Record this as a project decision: use server-driven token rotation."
"What did we decide about the auth migration?"
```

The agent should translate those requests to `record()`, `propose()`, `query()`,
or `context()` as appropriate. You should not need to manage entry IDs, branch
names, active refs, or knowledge-repo internals during normal work.

## Configuration

| Variable | Purpose |
|----------|---------|
| `JURATI_KNOWLEDGE_REMOTE` | Git remote for the knowledge repo |
| `JURATI_ACTIVE_REFS_ENABLED` | Enable instant active context sharing |
| `JURATI_ACTIVE_REF_TTL_HOURS` | Maximum TTL for active context entries |
| `JURATI_SIGNAL_PROVIDER` | Signal source: `github` or `jira` |
| `JURATI_PR_SIGNAL_REPOS` | Repos for GitHub PR signals |
| `JURATI_JIRA_BASE_URL` | Jira instance URL |
| `JURATI_JIRA_PROJECTS` | Jira project keys |
| `JURATI_CONTEXT_BUDGET_MODE` | `quiet`, `balanced`, or `deep` context budget |
| `JURATI_VALUE_LEDGER_PATH` | Enables the local JSONL value ledger at this path |
| `JURATI_VALUE_LEDGER_ENABLED` | Force local value ledger on or off |

Value receipts are enabled in startup/context packets. The persistent ledger is
local and opt-in: set `JURATI_VALUE_LEDGER_PATH` or
`JURATI_VALUE_LEDGER_ENABLED=true`.

## Troubleshooting

### The Agent Skips Context

Run:

```bash
jurati doctor --team --check-startup --strict
```

If the startup contract or MCP permissions are missing, repair project config:

```bash
jurati doctor --fix-project-config --team
```

Restart the MCP client after changing project configuration.

### `sync()` Or `context()` Is Unavailable

Check the knowledge remote and local cache:

```bash
jurati doctor --team --check-startup
jurati status
```

If the knowledge repo moved, regenerate project config with the new remote. If
the cache is corrupted, remove the local Jurati cache for that remote and run
`jurati doctor --team --check-startup` again.

### Active Handoffs Do Not Appear

Active context is disabled by default. Enable it only when the repo policy
allows short-lived handoffs:

```yaml
active_refs_enabled: true
active_ref_ttl_hours: 72
```

Then regenerate MCP config and verify:

```bash
jurati mcp-config --remote <knowledge-remote> --write-project
jurati doctor --team --check-startup
```

### Writes Are Blocked

Jurati evaluates writes before publishing. Credentials and secrets are blocked.
PII, confidentiality terms, and personnel content can require review. Remove the
sensitive content or route the entry through the reviewed path.

### PR Or Jira Signals Do Not Appear

Only configured, labeled sources enter the signal path.

For GitHub:

```bash
JURATI_PR_SIGNAL_REPOS=your-org/repo1,your-org/repo2
```

For Jira:

```bash
JURATI_SIGNAL_PROVIDER=jira
JURATI_JIRA_BASE_URL=https://jira.example.com
JURATI_JIRA_PROJECTS=PROJ1,PROJ2
JIRA_API_TOKEN=your-token
```

Unlabeled PRs and issues are ignored by design.

### Value Receipts Look Wrong

Jurati value accounting reports app-payload estimates only. It does not know
the client's full session, cache, or model bill unless a client provides that
data separately. Use:

```bash
jurati value --explain
```

to see the estimator, baseline, and privacy boundary. Negative net savings are
allowed and should be treated as a signal that the context packet was not worth
its cost for that turn.

If context is too noisy, use a quieter budget or local feedback:

```bash
JURATI_CONTEXT_BUDGET_MODE=quiet
jurati feedback <entry-id> not-useful
jurati feedback <entry-id> pin
```
