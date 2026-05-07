# CLAUDE.md Template for Jurati-Connected Projects

The fastest way to set this up is the CLI:

```bash
jurati install-claude-md --repo-path . \
  --remote git@github.com:your-org/jurati-knowledge.git
```

This appends the CLAUDE.md section below and creates `.claude/settings.json`
with the Jurati permission allowlist. If you prefer to set it up manually,
copy the section below into your project's `CLAUDE.md` and replace placeholders.

---

## Jurati — Team Knowledge

This project uses [Jurati](https://github.com/ostinato-forge/jurati) for cross-agent coordination.

Knowledge repo: `git@github.com:{{org}}/jurati-knowledge.git`

### Startup contract

**Before reading files, checking git state, or making edits, run the Jurati startup sequence.**

1. Call `sync()` silently so the local index is fresh.
2. Call `context(repo=<current repo>, goal=<user request>)`.
3. Summarize only relevant decisions, active work, and coordination blockers in 2-3 sentences for the developer.
4. Use `query(topic=...)` when the startup context points at a specific decision, workflow, or project you need to inspect.

Local git branches, diffs, and logs are useful after this sequence, but they are not a substitute for Jurati context.

### Tool quick-reference

| Tool | When to use |
|------|-------------|
| `sync()` | First, silently, before context(). |
| `context()` | Second, before local repo exploration. Pass `repo` and `goal`. |
| `query(topic=...)` | Deep-dive on a specific topic after context(). |
| `record(type, title, content)` | Capture a status update, in-progress work, or breaking change. |
| `propose(type, title, content)` | Record a team decision or workflow that needs review. |

### Normal request mapping

- "Save this handoff for the next agent." -> `record(type="active", ...)`
- "Capture this project update." -> `record(type="project", ...)`
- "Record this as a team decision." -> `propose(type="decision", ...)`

The developer should not need to know `record()` versus `propose()`. Translate the request for them.

### Rules

- **Never expose Jurati internals to the developer.** No entry IDs, ref paths, branch names, expiry dates, or lifecycle instructions. These are implementation details. Never say the word "Jurati" when confirming actions — the developer doesn't need to know which system stored the knowledge.
- **Never ask the developer to manage the knowledge repo.** Don't say "merge PR #X" or "run sync." Jurati handles its own lifecycle.
- **Confirm actions in one sentence focused on the work.** Say "Recorded the token format decision" — not "recording to Jurati," "saving to the knowledge repo," or "other agents will see this." Never reference agents, coordination mechanics, or visibility plumbing.
- **State coordination plainly.** If someone's PR blocks this work, say so directly: "Wait for Alice's auth PR to merge before changing the token format."

### Good developer-facing confirmations

- "Recorded the token format decision."
- "Saved the handoff for review."
- "Cleared the stale handoff."

Do not add entry IDs, branch names, ref paths, PR numbers, sync instructions, or expiry details to these confirmations unless the developer explicitly asks for debugging details.

### Auto-approve jurati tools

Run `jurati install-claude-md` to generate `.claude/settings.json`, or create
it manually:

```json
{
  "permissions": {
    "allow": [
      "mcp__jurati__context",
      "mcp__jurati__query",
      "mcp__jurati__search",
      "mcp__jurati__sync",
      "mcp__jurati__status",
      "mcp__jurati__read",
      "mcp__jurati__list_entries",
      "mcp__jurati__explain",
      "mcp__jurati__validate",
      "mcp__jurati__hygiene",
      "mcp__jurati__record",
      "mcp__jurati__propose",
      "mcp__jurati__expire"
    ]
  }
}
```

### Sibling repos

<!-- List repos that share this knowledge base. Agents use this for cross-repo awareness. -->

- `{{org}}/{{repo-1}}` — {{one-line description}}
- `{{org}}/{{repo-2}}` — {{one-line description}}
