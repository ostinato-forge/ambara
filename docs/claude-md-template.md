# CLAUDE.md Template for Jurati-Connected Projects

Copy the section below into your project's `CLAUDE.md`. Replace placeholders in `{{braces}}`.

---

## Jurati — Team Knowledge

This project uses [Jurati](https://github.com/ostinato-forge/jurati) for cross-agent coordination.

**You MUST call `context()` before starting any task.** This surfaces active work, team decisions, and cross-repo dependencies that affect your work. Summarize what you learn in 2-3 sentences for the developer.

### Tool quick-reference

| Tool | When to use |
|------|-------------|
| `context()` | First thing, every task. Pass `repo` and `goal` for better results. |
| `query(topic=...)` | Deep-dive on a specific topic after context(). |
| `record(type, title, content)` | Capture active context others should know about (e.g., breaking changes, in-progress work). |
| `propose(type, title, content)` | Record a team decision or workflow that needs review. |
| `sync()` | Call silently before context() to get fresh data. |

### Rules

- **Never expose Jurati internals to the developer.** No entry IDs, ref paths, branch names, expiry dates, or lifecycle instructions. These are implementation details.
- **Never ask the developer to manage the knowledge repo.** Don't say "merge PR #X" or "run sync." Jurati handles its own lifecycle.
- **Confirm actions in one sentence.** After recording or proposing, say something like "Recorded your auth refactor context" — not a multi-paragraph explanation of L0/L1/L2 escalation.
- **State coordination plainly.** If someone's PR blocks this work, say so directly: "Wait for Alice's auth PR to merge before changing the token format."

### Auto-approve jurati tools

Add `.claude/settings.json` to your repo so agents don't prompt for every jurati call:

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
